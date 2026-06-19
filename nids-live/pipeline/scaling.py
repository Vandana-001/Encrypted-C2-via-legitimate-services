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
    """Transform continuous feature columns using the active PowerTransformer.

    Applies the Yeo-Johnson transform to the 12 base ALL_FEATURES columns and
    clips output values strictly to the [-4.0, 4.0] interval, preserving raw
    TotBytes for downstream TCN coefficient of variation calculations.

    Args:
        df_feat (pd.DataFrame): Dataframe containing base engineered features.

    Returns:
        pd.DataFrame: Dataframe with scaled and clipped columns, plus 'TotBytes_raw'.
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
