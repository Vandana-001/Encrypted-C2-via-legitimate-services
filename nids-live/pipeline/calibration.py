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
    def __init__(self):
        self._lock = threading.Lock()
        self.calibrating = False
        self.started_at = None
        self.xgb_buffer = collections.deque(maxlen=config.CALIBRATION_MAX_BUFFER)
        self.tcn_buffer = collections.deque(maxlen=config.CALIBRATION_MAX_BUFFER)

    def is_active(self) -> bool:
        with self._lock:
            return self.calibrating

    def start(self) -> dict:
        """Start a new calibration recording window."""
        with self._lock:
            self.calibrating = True
            self.started_at = datetime.now(timezone.utc).isoformat()
            self.xgb_buffer.clear()
            self.tcn_buffer.clear()
            return {"calibrating": True, "started_at": self.started_at}

    def add_score(self, xgb_prob: float, tcn_prob: float):
        """Append scores if a calibration window is active."""
        with self._lock:
            if not self.calibrating:
                return
            self.xgb_buffer.append(xgb_prob)
            self.tcn_buffer.append(tcn_prob)

    def stop(self, percentile: float = config.CALIBRATION_DEFAULT_PERCENTILE, current_thresholds: dict = None) -> dict:
        """
        Stop calibration and return suggestions based on recorded scores.
        Clears buffers after computation so stale data cannot be reused.
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
        with self._lock:
            return {
                "calibrating": self.calibrating,
                "started_at": self.started_at,
                "n_samples": len(self.xgb_buffer)
            }

# ── Singleton instance ────────────────────────────────────────────────
_assistant = CalibrationAssistant()

def get_calibration_assistant() -> CalibrationAssistant:
    return _assistant
