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
    """Append six interaction features to the base feature matrix.

    Generates the exact interaction feature formulations specified in training.
    Features:
      - byte_per_pkt_rate: Ratio of ByteRate to PktRate.
      - src_dominance_dur: Product of SrcBytesRatio and log1p(Dur).
      - port_symmetry: Binary flag if Sport_cat matches Dport_cat.
      - pkt_density: Ratio of TotPkts to TotBytes.
      - proto_dport_cross: Combined protocol and Dport_cat category score.
      - byte_asym_mag: Magnitude of SrcBytesRatio deviation from 0.5.

    Args:
        X (np.ndarray): Base feature array of shape (N, 12).
        feature_names (list[str]): Names of the columns corresponding to X.

    Returns:
        tuple[np.ndarray, list[str]]: Augmented features of shape (N, 18), and augmented name list.
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
    """Run XGBoost model classification inference on scaled traffic flows.

    Applies interaction feature generation, computes raw XGBoost predictions,
    performs isotonic probability calibration if fitted, and flags anomalies.

    Args:
        df_scaled (pd.DataFrame): Scaled feature dataframe with ALL_FEATURES columns.
        xgb_model: Fitted XGBoost classifier expecting 18 input columns.
        threshold: Alert threshold float limit.

    Returns:
        tuple[np.ndarray, np.ndarray, np.ndarray]:
            - probs_raw: Raw float probability outputs.
            - probs_recal: Recalibrated float probability outputs.
            - alerts: Binary array (1 if anomaly, 0 otherwise).
    """
    X_base = df_scaled[ALL_FEATURES].values.astype(np.float32)
    X_aug, _ = add_xgb_interactions(X_base, list(ALL_FEATURES))
    probs_raw = xgb_model.predict_proba(X_aug)[:, 1].astype(np.float32)
    
    recalibrator = get_recalibrator()
    probs_recal = recalibrator.transform_xgb(probs_raw, X_aug)
    
    alerts = (probs_recal >= threshold).astype(int)
    return probs_raw, probs_recal, alerts
