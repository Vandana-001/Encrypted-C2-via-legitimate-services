"""
pipeline/calibration.py — Guided Calibration Assistant (Layer 2).

Maintains bounded buffers of raw scores during an explicit operator-driven
calibration window. Stopping calibration computes a suggested threshold
based on a given percentile, which the operator can then choose to apply.
"""

import collections
import threading
import numpy as np
from datetime import datetime, timezone

import config
from pipeline.threshold_manager import clip

class CalibrationAssistant:
    """Manages the Guided Calibration Assistant (Layer 2).

    Records model anomaly scores over an operator-specified window, then evaluates
    empirical percentiles to suggest target alert thresholds.
    """

    def __init__(self):
        """Initialize the calibration tracker and scoring queues."""
        self._lock = threading.Lock()
        self.calibrating = False
        self.started_at = None
        self.xgb_buffer = collections.deque(maxlen=config.CALIBRATION_MAX_BUFFER)
        self.tcn_buffer = collections.deque(maxlen=config.CALIBRATION_MAX_BUFFER)

    def is_active(self) -> bool:
        """Check if calibration is currently recording.

        Returns:
            bool: True if recording, False otherwise.
        """
        with self._lock:
            return self.calibrating

    def start(self) -> dict:
        """Start a new calibration recording window.

        Clears existing buffers.

        Returns:
            dict: Active status and timestamp.
        """
        with self._lock:
            self.calibrating = True
            self.started_at = datetime.now(timezone.utc).isoformat()
            self.xgb_buffer.clear()
            self.tcn_buffer.clear()
            return {"calibrating": True, "started_at": self.started_at}

    def add_score(self, xgb_prob: float, tcn_prob: float):
        """Append model anomaly scores to the calibration buffers.

        Args:
            xgb_prob: Raw probability score from XGBoost.
            tcn_prob: Raw probability score from TCN.
        """
        with self._lock:
            if not self.calibrating:
                return
            self.xgb_buffer.append(xgb_prob)
            self.tcn_buffer.append(tcn_prob)

    def stop(self, percentile: float = config.CALIBRATION_DEFAULT_PERCENTILE, current_thresholds: dict = None) -> dict:
        """Stop guided calibration and return threshold recommendations based on baseline percentiles.

        Clears baseline score buffers upon stopping to prevent stale reuse.

        Args:
            percentile: Cumulative percentile index to read (e.g. 99.5).
            current_thresholds: Active threshold settings.

        Returns:
            dict: Recommendations containing counts, histograms, and suggested thresholds.
        """
        with self._lock:
            if not self.calibrating:
                return {"error": "Not currently calibrating"}

            n_samples = len(self.xgb_buffer)
            if n_samples == 0:
                result = {"error": "No scores recorded during calibration window"}
            else:
                suggested_xgb_raw = float(np.percentile(self.xgb_buffer, percentile))
                suggested_tcn_raw = float(np.percentile(self.tcn_buffer, percentile))
                
                suggested_xgb = clip(suggested_xgb_raw, config.XGB_THRESHOLD_FLOOR, config.XGB_THRESHOLD_CEILING)
                suggested_tcn = clip(suggested_tcn_raw, config.TCN_THRESHOLD_FLOOR, config.TCN_THRESHOLD_CEILING)

                # Generate a simple 10-bin histogram for the UI
                def make_histogram(buffer):
                    if not buffer:
                        return {"bins": [], "counts": []}
                    counts, bin_edges = np.histogram(buffer, bins=10)
                    return {"bins": [float(b) for b in bin_edges], "counts": [int(c) for c in counts]}

                result = {
                    "n_samples": n_samples,
                    "percentile": percentile,
                    "suggestions": {
                        "xgb": {
                            "suggested": suggested_xgb,
                            "raw": suggested_xgb_raw,
                            "current": current_thresholds.get("xgb") if current_thresholds else None,
                            "histogram": make_histogram(self.xgb_buffer)
                        },
                        "tcn": {
                            "suggested": suggested_tcn,
                            "raw": suggested_tcn_raw,
                            "current": current_thresholds.get("tcn") if current_thresholds else None,
                            "histogram": make_histogram(self.tcn_buffer)
                        }
                    }
                }

            self.calibrating = False
            self.started_at = None
            self.xgb_buffer.clear()
            self.tcn_buffer.clear()

            return result

    def get_status(self) -> dict:
        """Get the current state of the calibration assistant.

        Returns:
            dict: State dictionary containing calibrating flag, start time, and sample count.
        """
        with self._lock:
            return {
                "calibrating": self.calibrating,
                "started_at": self.started_at,
                "n_samples": len(self.xgb_buffer)
            }

# ── Singleton instance ────────────────────────────────────────────────
_assistant = CalibrationAssistant()

def get_calibration_assistant() -> CalibrationAssistant:
    """Retrieve the singleton CalibrationAssistant instance.

    Returns:
        CalibrationAssistant: The global calibration assistant.
    """
    return _assistant
