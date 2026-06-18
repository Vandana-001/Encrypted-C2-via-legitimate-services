"""
pipeline/scaling.py — Exact port of notebook Cell 5 PowerTransformer scaling.

Applies the TRAINING PowerTransformer (Yeo-Johnson) to the 12 base
ALL_FEATURES and clips to [-4, 4] — exactly as Cell 7 of training.

Never re-fit scaler.  Always clip to [-4, 4] after transform.
"""

import numpy as np

from config import ALL_FEATURES
from pipeline.active_scaler import get_active_scaler

def scale_features(df_feat):
    """
    Exact port of notebook Cell 5 / Cell 12.

    Parameters
    ----------
    df_feat : pd.DataFrame
        Output of engineer_features(), containing ALL_FEATURES columns.
    scaler : sklearn.preprocessing.PowerTransformer
        Fitted PowerTransformer from training.  NEVER re-fit.

    Returns
    -------
    pd.DataFrame
        Copy of df_feat with ALL_FEATURES columns scaled and clipped to [-4, 4],
        plus a TotBytes_raw column preserving the unscaled TotBytes for TCN.
    """
    scaler = get_active_scaler()
    X = df_feat[ALL_FEATURES].values.astype(np.float32)
    X_scaled = np.clip(scaler.transform(X), -4, 4).astype(np.float32)

    df_scaled = df_feat.copy()
    for i, col in enumerate(ALL_FEATURES):
        df_scaled[col] = X_scaled[:, i]

    # Keep unscaled TotBytes for TCN within-window payload CV computation
    df_scaled["TotBytes_raw"] = df_feat["TotBytes"].values

    return df_scaled
