"""
pipeline/xgb_inference.py — Exact port of notebook Cell 6 XGBoost inference.

Runs per-flow, independently of TCN.  No ensembling, no averaging.
This is exactly what MODE="both" does in the notebook.
"""

import numpy as np

from config import (
    EPSILON,
    ALL_FEATURES,
    INTERACTION_NAMES,
)
from pipeline.recalibration import get_recalibrator


def add_xgb_interactions(X, feature_names):
    """
    Append 6 engineered interaction features — exact replica of notebook Cell 8/14.

    Features added:
      byte_per_pkt_rate  : ByteRate / PktRate  — high in bulk transfers
      src_dominance_dur  : SrcBytesRatio × log(1+Dur)  — C2 beacon signal
      port_symmetry      : Sport_cat == Dport_cat  — P2P / lateral movement
      pkt_density        : TotPkts / TotBytes  — scan burst proxy
      proto_dport_cross  : Proto_enc × 10 + Dport_cat  — protocol-port combo
      byte_asym_mag      : |2 × SrcBytesRatio − 1|  — asymmetry magnitude

    Parameters
    ----------
    X : np.ndarray, shape (n, 12)
        Base features (ALL_FEATURES columns).
    feature_names : list[str]
        Names corresponding to columns of X.

    Returns
    -------
    X_aug : np.ndarray, shape (n, 18)
        Base features + 6 interaction features.
    aug_names : list[str]
        Updated feature name list.
    """
    eps = EPSILON
    idx = {f: i for i, f in enumerate(feature_names)}

    dur = X[:, idx["Dur"]]
    tot_pkts = X[:, idx["TotPkts"]]
    tot_bytes = X[:, idx["TotBytes"]]
    pkt_rate = X[:, idx["PktRate"]]
    byte_rate = X[:, idx["ByteRate"]]
    src_ratio = X[:, idx["SrcBytesRatio"]]
    sport = X[:, idx["Sport_cat"]]
    dport = X[:, idx["Dport_cat"]]
    proto = X[:, idx["Proto_enc"]]

    interactions = np.column_stack([
        np.clip(byte_rate / (pkt_rate + eps), 0, 1e4),
        src_ratio * np.log1p(dur),
        (sport == dport).astype(np.float32),
        np.clip(tot_pkts / (tot_bytes + eps), 0, 1e3),
        proto * 10 + dport,
        np.clip(np.abs(2 * src_ratio - 1), 0, 1),
    ]).astype(np.float32)

    aug_names = feature_names + INTERACTION_NAMES
    return np.hstack([X, interactions]), aug_names


def run_xgb_inference(df_scaled, xgb_model, threshold: float):
    """
    Run XGBoost inference on scaled flow data.

    Parameters
    ----------
    df_scaled : pd.DataFrame
        Scaled feature DataFrame with ALL_FEATURES columns.
    xgb_model : xgboost.XGBClassifier
        Fitted XGBoost classifier expecting 18 input columns.
    threshold : float
        The live decision threshold.

    Returns
    -------
    probs_raw : np.ndarray, shape (n,)
        Per-flow raw malicious probability.
    probs_recal : np.ndarray, shape (n,)
        Per-flow recalibrated malicious probability.
    alerts : np.ndarray, shape (n,)
        Per-flow alert flag (1 if probs_recal >= threshold).
    """
    X_base = df_scaled[ALL_FEATURES].values.astype(np.float32)
    X_aug, _ = add_xgb_interactions(X_base, list(ALL_FEATURES))
    probs_raw = xgb_model.predict_proba(X_aug)[:, 1].astype(np.float32)
    
    recalibrator = get_recalibrator()
    probs_recal = recalibrator.transform_xgb(probs_raw, X_aug)
    
    alerts = (probs_recal >= threshold).astype(int)
    return probs_raw, probs_recal, alerts
