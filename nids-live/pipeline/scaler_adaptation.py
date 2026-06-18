"""
pipeline/scaler_adaptation.py — Byte-column scaler adaptation logic.

Re-fits the Yeo-Johnson lambdas only for the three byte columns
(TotBytes, SrcBytes, BytesPerPkt) on a sample of live traffic.
"""

import copy
import threading
import numpy as np
from sklearn.preprocessing import PowerTransformer

from config import ALL_FEATURES

BYTE_COLS = ["TotBytes", "SrcBytes", "BytesPerPkt"]
BYTE_IDXS = [ALL_FEATURES.index(c) for c in BYTE_COLS]

MIN_SAMPLES_FOR_ADAPTATION = 50_000   # operator must collect at least this many flows
ADAPTATION_SAMPLE_CAP      = 200_000  # cap to match notebook's sample(min(200_000, n))

_adapt_lock = threading.Lock()

class ScalerAdaptationBuffer:
    """
    Collects raw (pre-scaling) byte column values from live traffic.
    When enough samples are available, fits new lambdas for the three
    byte columns and returns an adapted copy of the base scaler.
    Does NOT modify the base scaler in-place.
    """

    def __init__(self):
        self._buf = {col: [] for col in BYTE_COLS}
        self._active = False

    def start(self):
        with _adapt_lock:
            self._buf = {col: [] for col in BYTE_COLS}
            self._active = True

    def stop(self):
        with _adapt_lock:
            self._active = False

    def is_active(self):
        with _adapt_lock:
            return self._active

    def add(self, row_dict: dict):
        """Call with a raw (pre-feature-engineering) flow dict for every new flow."""
        if not self._active:
            return
        with _adapt_lock:
            for col in BYTE_COLS:
                v = row_dict.get(col)
                if v is not None:
                    try:
                        self._buf[col].append(float(v))
                    except (TypeError, ValueError):
                        pass

    def sample_count(self) -> int:
        with _adapt_lock:
            return min(len(self._buf[c]) for c in BYTE_COLS)

    def compute_adapted_scaler(self, base_scaler):
        """
        Exact port of notebook Cell 5a.
        Returns (adapted_scaler, lambda_deltas_dict) or raises ValueError if
        fewer than MIN_SAMPLES_FOR_ADAPTATION samples have been collected.
        Does NOT modify base_scaler.
        """
        with _adapt_lock:
            n = self.sample_count()
            if n < MIN_SAMPLES_FOR_ADAPTATION:
                raise ValueError(
                    f"Only {n:,} samples collected; need {MIN_SAMPLES_FOR_ADAPTATION:,}. "
                    "Keep collecting and try again."
                )

            # Build sample matrix in BYTE_COLS column order
            sample_data = np.column_stack([
                np.array(self._buf[c][:ADAPTATION_SAMPLE_CAP], dtype=np.float64)
                for c in BYTE_COLS
            ])

        # Replace inf/nan
        sample_data = np.where(np.isfinite(sample_data), sample_data, np.nan)
        mask = ~np.any(np.isnan(sample_data), axis=1)
        sample_data = sample_data[mask]

        if len(sample_data) < MIN_SAMPLES_FOR_ADAPTATION:
            raise ValueError(
                f"After dropping NaN/inf, only {len(sample_data):,} clean samples remain; "
                f"need {MIN_SAMPLES_FOR_ADAPTATION:,}."
            )

        # Sub-sample to cap (mirrors notebook's .sample(min(200_000, len(sample))))
        rng = np.random.default_rng(42)
        if len(sample_data) > ADAPTATION_SAMPLE_CAP:
            idx = rng.choice(len(sample_data), ADAPTATION_SAMPLE_CAP, replace=False)
            sample_data = sample_data[idx]

        # Fit new PowerTransformer on byte columns only
        byte_pt = PowerTransformer(method="yeo-johnson", standardize=True)
        byte_pt.fit(sample_data)

        # Deep-copy base scaler and surgically replace byte-column stats
        adapted = copy.deepcopy(base_scaler)
        for pos, col_idx in enumerate(BYTE_IDXS):
            adapted.lambdas_[col_idx]         = byte_pt.lambdas_[pos]
            adapted._scaler.mean_[col_idx]    = byte_pt._scaler.mean_[pos]
            adapted._scaler.var_[col_idx]     = byte_pt._scaler.var_[pos]
            adapted._scaler.scale_[col_idx]   = byte_pt._scaler.scale_[pos]

        # Report lambda deltas for the audit log / UI
        lambda_deltas = {}
        for pos, col in enumerate(BYTE_COLS):
            col_idx = BYTE_IDXS[pos]
            lambda_deltas[col] = {
                "original": float(base_scaler.lambdas_[col_idx]),
                "adapted":  float(adapted.lambdas_[col_idx]),
            }

        return adapted, lambda_deltas

    def clear(self):
        with _adapt_lock:
            self._buf = {col: [] for col in BYTE_COLS}
            self._active = False

# ── Singleton instance ────────────────────────────────────────────────
_buffer = ScalerAdaptationBuffer()

def get_adaptation_buffer() -> ScalerAdaptationBuffer:
    return _buffer
