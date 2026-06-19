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
    """Collects raw byte column values from live traffic.

    When enough samples are collected, fits new Yeo-Johnson lambdas for the three
    byte columns (TotBytes, SrcBytes, BytesPerPkt) and returns an adapted copy of
    the baseline scaler without in-place modification.
    """

    def __init__(self):
        """Initialize the adaptation buffer dictionary and inactive status."""
        self._buf = {col: [] for col in BYTE_COLS}
        self._active = False

    def start(self):
        """Start collecting raw byte-column traffic values in the buffer."""
        with _adapt_lock:
            self._buf = {col: [] for col in BYTE_COLS}
            self._active = True

    def stop(self):
        """Stop buffer collection."""
        with _adapt_lock:
            self._active = False

    def is_active(self):
        """Check if buffer collection is currently enabled.

        Returns:
            bool: True if active, False otherwise.
        """
        with _adapt_lock:
            return self._active

    def add(self, row_dict: dict):
        """Append byte metrics from a new flow record into the buffer.

        Args:
            row_dict: Dictionary containing raw flow metrics.
        """
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
        """Get the current sample size in the buffer.

        Returns:
            int: The minimum count of collected values across the three columns.
        """
        with _adapt_lock:
            return min(len(self._buf[c]) for c in BYTE_COLS)

    def compute_adapted_scaler(self, base_scaler):
        """Fit Yeo-Johnson lambdas on the collected samples and return an adapted copy of base_scaler.

        Surgically overrides lambdas, means, variances, and scale attributes for
        only the three byte columns while leaving other columns unchanged.

        Args:
            base_scaler (sklearn.preprocessing.PowerTransformer): The base scaler to copy.

        Returns:
            tuple[sklearn.preprocessing.PowerTransformer, dict]:
                The adapted PowerTransformer instance, and a dictionary of original/adapted lambdas.

        Raises:
            ValueError: If the buffer contains fewer than MIN_SAMPLES_FOR_ADAPTATION samples.
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
        """Discard all buffer contents and mark collection as inactive."""
        with _adapt_lock:
            self._buf = {col: [] for col in BYTE_COLS}
            self._active = False

# ── Singleton instance ────────────────────────────────────────────────
_buffer = ScalerAdaptationBuffer()

def get_adaptation_buffer() -> ScalerAdaptationBuffer:
    """Retrieve the singleton ScalerAdaptationBuffer instance.

    Returns:
        ScalerAdaptationBuffer: The global adaptation buffer instance.
    """
    return _buffer
