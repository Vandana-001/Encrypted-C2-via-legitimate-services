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
    """Retrieve the currently active PowerTransformer.

    Returns:
        sklearn.preprocessing.PowerTransformer: The active scaling transformer.
    """
    with _scaler_lock:
        return _active_scaler


def set_active_scaler(s):
    """Set the globally active PowerTransformer.

    Args:
        s (sklearn.preprocessing.PowerTransformer): The transformer to set as active.
    """
    global _active_scaler
    with _scaler_lock:
        _active_scaler = s


def reset_active_scaler(base_scaler):
    """Reset the active scaler back to the training baseline.

    Removes any adapted scaler binary (`scaler_adapted.pkl`) from the filesystem.

    Args:
        base_scaler (sklearn.preprocessing.PowerTransformer): The training baseline scaler.
    """
    set_active_scaler(base_scaler)
    adapted_path = os.path.join(MODEL_DIR, "scaler_adapted.pkl")
    if os.path.exists(adapted_path):
        try:
            os.remove(adapted_path)
            logger.info("Removed scaler_adapted.pkl")
        except Exception as exc:
            logger.error("Failed to remove scaler_adapted.pkl: %s", exc)
