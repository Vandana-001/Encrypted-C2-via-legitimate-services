"""
pipeline/active_scaler.py — Thread-safe access to the live scaler.

Holds the globally active PowerTransformer used by scale_features.
"""

import os
import threading
import joblib
import logging
from config import MODEL_DIR

logger = logging.getLogger(__name__)

_scaler_lock = threading.Lock()
_active_scaler = None


def get_active_scaler():
    """Return the currently active scaler."""
    with _scaler_lock:
        return _active_scaler


def set_active_scaler(s):
    """Set the currently active scaler."""
    global _active_scaler
    with _scaler_lock:
        _active_scaler = s


def reset_active_scaler(base_scaler):
    """Reset the active scaler to the base scaler and remove adapted pkl."""
    set_active_scaler(base_scaler)
    adapted_path = os.path.join(MODEL_DIR, "scaler_adapted.pkl")
    if os.path.exists(adapted_path):
        try:
            os.remove(adapted_path)
            logger.info("Removed scaler_adapted.pkl")
        except Exception as exc:
            logger.error("Failed to remove scaler_adapted.pkl: %s", exc)
