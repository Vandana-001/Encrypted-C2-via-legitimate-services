"""
pipeline/feature_engineering.py — Exact port of notebook Cell 4 feature engineering.

The only allowed deviation from the notebook is the streaming IAT adaptation
(§5.1): instead of groupby("SrcAddr")["StartTime_epoch"].diff() over a
complete static DataFrame, we maintain a persistent dict of last-seen
epoch per source IP, guarded by a threading.Lock.
"""

import threading
import logging

import numpy as np
import pandas as pd

from config import (
    EPSILON,
    CLIP_COLS,
    ALL_FEATURES,
)

logger = logging.getLogger(__name__)


# ── Persistent IAT state (streaming adaptation §5.1) ──────────────────

_iat_lock = threading.Lock()
_last_epoch_by_src: dict[str, float] = {}


def reset_iat_state():
    """Reset the IAT tracking state dictionary.

    Called during capture restarts to purge any previous connection timestamps.
    """
    global _last_epoch_by_src
    with _iat_lock:
        _last_epoch_by_src = {}


def _categorize_port(p) -> int:
    """Categorize port numbers into one of six pre-defined categories.

    Categories:
        0: Well-known system ports (0 - 1023)
        1: Registered ports (1024 - 49151)
        2: Ephemeral dynamic ports (49152 - 65535)
        3: Unparseable ports
        4: Common HTTP/HTTPS ports (80, 443)
        5: DNS port (53)

    Args:
        p: Raw port representation (string, float, or int).

    Returns:
        int: Categorization class (0 to 5).
    """
    try:
        p = int(float(str(p).strip()))
        if p in (443, 80):
            return 4   # HTTPS / HTTP
        if p == 53:
            return 5   # DNS
        if p <= 1023:
            return 0   # well-known
        if p <= 49151:
            return 1   # registered
        return 2        # ephemeral
    except Exception:
        return 3        # unparseable


def engineer_features(df, clip_bounds, le_proto, le_dir):
    """Apply feature engineering transformations to raw flow records.

    Calculates behavior ratios, clips numeric values, encodes protocols/direction,
    assigns port classes, calculates Inter-Arrival Times (IAT), and computes flow
    asymmetry metrics.

    Args:
        df (pd.DataFrame): Dataframe of raw completed flows.
        clip_bounds (dict): Column clipping limits loaded from training.
        le_proto (LabelEncoder): LabelEncoder for protocols.
        le_dir (LabelEncoder): LabelEncoder for flow directions.

    Returns:
        pd.DataFrame: Transformed dataframe ready for scaling and inference.
    """
    df = df.copy()

    # ── 1. Numerics ───────────────────────────────────────────────────
    for col in ["Dur", "TotPkts", "TotBytes", "SrcBytes"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df.replace([np.inf, -np.inf], np.nan, inplace=True)
    df.dropna(subset=["Dur", "TotPkts", "TotBytes", "SrcBytes"], inplace=True)
    df.reset_index(drop=True, inplace=True)

    if len(df) == 0:
        return df

    # ── 2. Behavioral ratios ──────────────────────────────────────────
    df["BytesPerPkt"] = (
        df["TotBytes"] / (df["TotPkts"] + EPSILON)
    ).astype(np.float32)
    df["PktRate"] = (
        df["TotPkts"] / (df["Dur"] + EPSILON)
    ).astype(np.float32)
    df["ByteRate"] = (
        df["TotBytes"] / (df["Dur"] + EPSILON)
    ).astype(np.float32)
    df["SrcBytesRatio"] = (
        df["SrcBytes"] / (df["TotBytes"] + EPSILON)
    ).clip(0, 1).astype(np.float32)

    # ── 3. P99 clip (training bounds — never recompute bounds live) ───
    for col in CLIP_COLS:
        if col in clip_bounds:
            df[col] = df[col].clip(upper=clip_bounds[col]).astype(np.float32)

    # ── 4. Protocol encoding (use training encoder, never refit) ──────
    proto_str = df["Proto"].astype(str).str.lower().str.strip()
    unknown_protos = set(proto_str.unique()) - set(le_proto.classes_)
    if unknown_protos:
        logger.warning(
            "Unknown proto values unseen in training, mapped to '%s': %s",
            le_proto.classes_[0],
            unknown_protos,
        )
        proto_str = proto_str.apply(
            lambda x: x if x in le_proto.classes_ else le_proto.classes_[0]
        )
    df["Proto_enc"] = le_proto.transform(proto_str).astype(np.int16)

    # ── 5. Direction encoding (use training encoder, never refit) ─────
    dir_str = df["Dir"].astype(str).str.strip()
    unknown_dirs = set(dir_str.unique()) - set(le_dir.classes_)
    if unknown_dirs:
        logger.warning(
            "Unknown Dir values unseen in training, mapped to '%s': %s",
            le_dir.classes_[0],
            unknown_dirs,
        )
        dir_str = dir_str.apply(
            lambda x: x if x in le_dir.classes_ else le_dir.classes_[0]
        )
    df["Dir_enc"] = le_dir.transform(dir_str).astype(np.int16)

    # ── 6. Port categories ────────────────────────────────────────────
    df["Sport_cat"] = df["Sport"].apply(_categorize_port).astype(np.int8)
    df["Dport_cat"] = df["Dport"].apply(_categorize_port).astype(np.int8)

    # ── 7. StartTime → epoch ──────────────────────────────────────────
    df["StartTime_epoch"] = (
        pd.to_datetime(df["StartTime"], errors="coerce")
        .astype(np.int64) // 10**9
    ).astype(np.float64)

    # ── 8. Sort by IP + time (streaming IAT adaptation §5.1) ──────────
    # When processing a mini-batch of flows that finished in the same tick,
    # sort by (SrcAddr, StartTime_epoch) before computing IAT — exactly
    # like the notebook's sort_values(["SrcAddr", "StartTime_epoch"]) step.
    df.sort_values(["SrcAddr", "StartTime_epoch"], inplace=True)
    df.reset_index(drop=True, inplace=True)

    # ── 9. Per-flow IAT (streaming adaptation) ────────────────────────
    # The notebook computes:
    #   df.groupby("SrcAddr")["StartTime_epoch"].diff().fillna(0)
    # In live mode, flows arrive one (or a few) at a time across calls,
    # so we use a persistent dict to track the last epoch per SrcAddr.
    iat_values = []
    with _iat_lock:
        for _, row in df.iterrows():
            src_addr = str(row["SrcAddr"])
            start_epoch = float(row["StartTime_epoch"])
            prev = _last_epoch_by_src.get(src_addr)
            iat_raw = (start_epoch - prev) if prev is not None else 0.0
            _last_epoch_by_src[src_addr] = start_epoch
            iat_values.append(iat_raw)

    df["IAT_raw"] = np.array(iat_values, dtype=np.float32)

    # ── 10. Flow asymmetry (per-row) ──────────────────────────────────
    src_b = df["SrcBytes"].astype(np.float32)
    dst_b = (df["TotBytes"] - df["SrcBytes"]).astype(np.float32)
    df["flow_asymmetry"] = (
        (src_b - dst_b).abs() / (df["TotBytes"].astype(np.float32) + EPSILON)
    ).astype(np.float32)

    # ── 11. Drop raw helpers no longer needed (keep DstAddr, Dport for TCN) ─
    df.drop(
        columns=["Proto", "Dir", "Sport", "StartTime"],
        inplace=True,
        errors="ignore",
    )
    df.dropna(subset=ALL_FEATURES, inplace=True)
    df.reset_index(drop=True, inplace=True)

    return df
