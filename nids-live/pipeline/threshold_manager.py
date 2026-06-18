"""
pipeline/threshold_manager.py — Adaptive Threshold Manager.

Thread-safe singleton managing the live XGBoost and TCN thresholds.
Maintains state in models/runtime_thresholds.json and appends all changes
to an audit log in logs/threshold_audit.jsonl.
"""

import os
import json
import logging
import threading
from datetime import datetime, timezone

import config

logger = logging.getLogger(__name__)

RUNTIME_THRESHOLDS_PATH = os.path.join(config.MODEL_DIR, "runtime_thresholds.json")
AUDIT_LOG_PATH = os.path.join(config.BASE_DIR, "logs", "threshold_audit.jsonl")


def clip(value, floor, ceiling):
    return max(floor, min(value, ceiling))


class ThresholdManager:
    """Thread-safe singleton for managing live decision thresholds."""

    def __init__(self):
        self._lock = threading.Lock()
        self._state = self._load_or_default()

    def _load_or_default(self) -> dict:
        """Load from persistent JSON or initialize with notebook defaults."""
        default_state = {
            "xgb": config.XGB_THRESHOLD,
            "tcn": config.TCN_THRESHOLD
        }

        if not os.path.exists(RUNTIME_THRESHOLDS_PATH):
            self._persist_dict(default_state)
            return default_state

        try:
            with open(RUNTIME_THRESHOLDS_PATH, "r") as f:
                state = json.load(f)
                
            # Validate loaded state against bounds
            state["xgb"] = clip(state.get("xgb", default_state["xgb"]), config.XGB_THRESHOLD_FLOOR, config.XGB_THRESHOLD_CEILING)
            state["tcn"] = clip(state.get("tcn", default_state["tcn"]), config.TCN_THRESHOLD_FLOOR, config.TCN_THRESHOLD_CEILING)
            return state
        except Exception as exc:
            logger.error("Failed to load runtime thresholds: %s", exc)
            return default_state

    def _persist_dict(self, state: dict):
        """Write current state to persistent JSON."""
        try:
            # Ensure models directory exists
            os.makedirs(config.MODEL_DIR, exist_ok=True)
            with open(RUNTIME_THRESHOLDS_PATH, "w") as f:
                json.dump(state, f, indent=4)
        except Exception as exc:
            logger.error("Failed to persist runtime thresholds: %s", exc)

    def _persist(self):
        self._persist_dict(self._state)

    def _audit(self, model: str, old: float, new: float, reason: str, candidate_raw: float = None, n_samples: int = None):
        """Append a threshold change event to the audit log."""
        if abs(new - old) < 1e-6:
            return  # No change

        # Ensure logs directory exists
        os.makedirs(os.path.dirname(AUDIT_LOG_PATH), exist_ok=True)
        
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "component": "threshold",
            "model": model,
            "old": old,
            "new": new,
            "reason": reason,
        }
        if candidate_raw is not None:
            entry["candidate_raw"] = candidate_raw
        if n_samples is not None:
            entry["n_samples"] = n_samples

        try:
            with open(AUDIT_LOG_PATH, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as exc:
            logger.error("Failed to write to threshold audit log: %s", exc)

    def audit_event(self, component: str, event: str, **kwargs):
        """Append an arbitrary component event to the audit log."""
        os.makedirs(os.path.dirname(AUDIT_LOG_PATH), exist_ok=True)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "component": component,
            "event": event,
        }
        entry.update(kwargs)
        try:
            with open(AUDIT_LOG_PATH, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as exc:
            logger.error("Failed to write to threshold audit log: %s", exc)

    def get(self) -> dict:
        """Get the current live thresholds."""
        with self._lock:
            return dict(self._state)

    def set(self, xgb: float = None, tcn: float = None, reason: str = "manual", candidate_raw_xgb=None, candidate_raw_tcn=None, n_samples=None):
        """Set one or both thresholds, respecting floor/ceiling bounds."""
        with self._lock:
            old_xgb = self._state["xgb"]
            old_tcn = self._state["tcn"]

            if xgb is not None:
                xgb_clipped = clip(xgb, config.XGB_THRESHOLD_FLOOR, config.XGB_THRESHOLD_CEILING)
                self._state["xgb"] = xgb_clipped
                self._audit("xgb", old_xgb, xgb_clipped, reason, candidate_raw_xgb, n_samples)

            if tcn is not None:
                tcn_clipped = clip(tcn, config.TCN_THRESHOLD_FLOOR, config.TCN_THRESHOLD_CEILING)
                self._state["tcn"] = tcn_clipped
                self._audit("tcn", old_tcn, tcn_clipped, reason, candidate_raw_tcn, n_samples)

            if xgb is not None or tcn is not None:
                self._persist()

    def reset(self):
        """Reset both thresholds to the startup defaults."""
        self.set(xgb=config.XGB_THRESHOLD, tcn=config.TCN_THRESHOLD, reason="reset")

# ── Singleton instance ────────────────────────────────────────────────
_manager = ThresholdManager()

def get_manager() -> ThresholdManager:
    return _manager
