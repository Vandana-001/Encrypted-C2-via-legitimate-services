"""
pipeline/tcn_inference.py — Streaming-adapted port of notebook Cell 7 TCN inference.

This streaming implementation evaluates the single most-recent SEQ_LEN-flow
window per source IP on every new flow, equivalent to the last element
produced by the notebook's build_tcn_sequences(..., step=1) for that IP at
that point in time.  It intentionally does not re-emit predictions for every
historical window already scored, since live monitoring only needs the
freshest assessment per IP.

Uses TotBytes_raw (unscaled) for w_tb_mean/w_tb_std — this matches the
notebook's df_for_tcn["TotBytes"] = df_scaled["TotBytes_raw"] substitution.
"""

import collections
import threading
import logging

import numpy as np
import tensorflow as tf

from config import (
    SEQ_LEN,
    EPSILON,
    MIN_SEQ,
    N_WITHIN,
    ALL_FEATURES,
)
from pipeline.recalibration import get_recalibrator

logger = logging.getLogger(__name__)


# ── Per-source-IP rolling buffer ──────────────────────────────────────

_buffer_lock = threading.Lock()
_ip_buffers: dict[str, collections.deque] = {}


def reset_tcn_state():
    """Reset all per-IP rolling buffers to clear sequence histories.

    Called during capture restarts or status resets.
    """
    global _ip_buffers
    with _buffer_lock:
        _ip_buffers = {}


def scale_within_window(X: np.ndarray, win_scaler, n_base: int, clip: float = 4.0) -> np.ndarray:
    """Apply the within-window RobustScaler to the 7 within-window dimensions.

    Scales columns from index n_base to the end across all sequence steps and
    clips scaled values between -clip and +clip.

    Args:
        X (np.ndarray): Unscaled TCN feature matrix of shape (N, SEQ_LEN, 19).
        win_scaler: Loaded within-window RobustScaler.
        n_base: Index split where within-window features begin (typically 12).
        clip: Clipping boundary limit.

    Returns:
        np.ndarray: Scaled and clipped feature matrix.
    """
    N, L, F  = X.shape
    n_win    = F - n_base
    win_feat = X[:, :, n_base:].reshape(N * L, n_win)
    win_scaled = np.clip(win_scaler.transform(win_feat), -clip, clip).astype(np.float32)
    X_out = X.copy()
    X_out[:, :, n_base:] = win_scaled.reshape(N, L, n_win)
    return X_out


def _within_window_features(IATs, TBYTs, FASYMs, DSTs, DPORTs) -> np.ndarray:
    """Compute 7 within-window behavioral features for a sequence window.

    Metrics calculated:
      - Inter-Arrival Time (IAT) mean and standard deviation.
      - Beacon regularity coefficient of variation.
      - Payload bytes coefficient of variation.
      - Flow asymmetry average.
      - Destination IP fanout uniqueness.
      - Destination port entropy.

    Args:
        IATs: Sequence of Inter-Arrival Times.
        TBYTs: Sequence of raw total byte counts.
        FASYMs: Sequence of flow asymmetry values.
        DSTs: Sequence of destination addresses.
        DPORTs: Sequence of destination ports.

    Returns:
        np.ndarray: Computed array of 7 window features of shape (7,).
    """
    eps = EPSILON

    def _to_int(v):
        try:
            return int(float(str(v)))
        except Exception:
            return -1

    w_iat_mean = float(IATs.mean())
    w_iat_std = float(IATs.std())
    w_beacon = float(np.clip(w_iat_std / (w_iat_mean + eps), 0, 100))

    w_tb_mean = float(TBYTs.mean())
    w_tb_std = float(TBYTs.std())
    w_pay_cv = float(np.clip(w_tb_std / (w_tb_mean + eps), 0, 100))

    w_fasym_mean = float(FASYMs.mean())

    w_dst_fanout = float(np.clip(len(set(DSTs.tolist())), 0, SEQ_LEN))

    w_dports_int = np.array([_to_int(v) for v in DPORTs], dtype=np.int32)
    vals, cnts = np.unique(w_dports_int, return_counts=True)
    probs = cnts / cnts.sum()
    w_dport_ent = float(-np.sum(probs * np.log(probs + 1e-12)))

    return np.array([
        w_iat_mean, w_iat_std, w_beacon,
        w_pay_cv, w_fasym_mean,
        w_dst_fanout, w_dport_ent,
    ], dtype=np.float32)


def process_flow_for_tcn(row_data: dict, tcn_model, win_scaler, threshold: float) -> dict | None:
    """Process a single completed traffic flow through the TCN rolling sequence buffer.

    Performs cyclic sequence padding, windows feature aggregation, within-window scaling,
    runs a raw forward pass through the keras model, applies isotonic recalibration, and
    flags anomalous alerts.

    Args:
        row_data: Flow metrics dictionary with keys 'SrcAddr', 'features', 'IAT_raw', etc.
        tcn_model: Loaded TCN model instance.
        win_scaler: Loaded within-window RobustScaler.
        threshold: Threshold float boundary.

    Returns:
        dict | None: Dictionary of results if sequence length >= MIN_SEQ; None otherwise.
    """
    src_addr = str(row_data["SrcAddr"])

    entry = {
        "features": row_data["features"],       # (12,) scaled
        "IAT_raw": float(row_data["IAT_raw"]),
        "TotBytes_raw": float(row_data["TotBytes_raw"]),
        "flow_asymmetry": float(row_data["flow_asymmetry"]),
        "DstAddr": str(row_data["DstAddr"]),
        "Dport": row_data["Dport"],
    }

    with _buffer_lock:
        if src_addr not in _ip_buffers:
            _ip_buffers[src_addr] = collections.deque(maxlen=SEQ_LEN)
        buf = _ip_buffers[src_addr]
        buf.append(entry)

        buf_len = len(buf)
        if buf_len < MIN_SEQ:
            # Not enough history yet — identical to the notebook's
            # if count < MIN_SEQ: continue
            return None

        # Build a single window from the current buffer
        buf_list = list(buf)

    # ── Build window (outside lock for performance) ───────────────────

    n_rows = len(buf_list)
    features_arr = np.array([e["features"] for e in buf_list], dtype=np.float32)
    iat_arr = np.array([e["IAT_raw"] for e in buf_list], dtype=np.float32)
    tbyt_arr = np.array([e["TotBytes_raw"] for e in buf_list], dtype=np.float32)
    fasym_arr = np.array([e["flow_asymmetry"] for e in buf_list], dtype=np.float32)
    dst_arr = np.array([e["DstAddr"] for e in buf_list])
    dport_arr = np.array([e["Dport"] for e in buf_list])

    # Cyclic padding for short sequences
    if n_rows < SEQ_LEN:
        import math
        repeats = math.ceil(SEQ_LEN / n_rows)
        features_arr = np.tile(features_arr, (repeats, 1))[:SEQ_LEN]
        iat_arr = np.tile(iat_arr, repeats)[:SEQ_LEN]
        tbyt_arr = np.tile(tbyt_arr, repeats)[:SEQ_LEN]
        fasym_arr = np.tile(fasym_arr, repeats)[:SEQ_LEN]
        dst_arr = np.tile(dst_arr, repeats)[:SEQ_LEN]
        dport_arr = np.tile(dport_arr, repeats)[:SEQ_LEN]

    # Compute within-window features (7 values)
    w_feats = _within_window_features(
        iat_arr, tbyt_arr, fasym_arr, dst_arr, dport_arr
    )

    # Broadcast within-window features across all timesteps
    w_broadcast = np.tile(w_feats, (SEQ_LEN, 1))   # (SEQ_LEN, 7)

    # Concatenate base features + within-window features → (SEQ_LEN, 19)
    window = np.concatenate([features_arr, w_broadcast], axis=1)

    # ── Run TCN inference ─────────────────────────────────────────────
    N_BASE = len(ALL_FEATURES)
    window_scaled = scale_within_window(window[np.newaxis, ...], win_scaler, N_BASE)
    
    # Eager inference — bypasses JIT compilation entirely
    with tf.device('/CPU:0'):
        prob_raw = float(
            tcn_model(window_scaled, training=False).numpy().flatten()[0]
        )
    
    recalibrator = get_recalibrator()
    prob_recal = float(recalibrator.transform_tcn(np.array([prob_raw]), window_scaled)[0])
    
    alert = int(prob_recal >= threshold)

    return {
        "SrcAddr": src_addr,
        "tcn_prob": prob_raw,
        "tcn_prob_recal": prob_recal,
        "tcn_alert": alert,
    }
