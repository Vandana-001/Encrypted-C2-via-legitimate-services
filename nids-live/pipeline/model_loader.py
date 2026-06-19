"""
pipeline/model_loader.py — Load and validate all 7 pre-trained model artifacts.

Singleton pattern: artifacts are loaded once at app startup and reused
across all requests.  Never refits/retrains any artifact.
"""

import os
import logging
import joblib

from config import MODEL_DIR
from pipeline.active_scaler import set_active_scaler

logger = logging.getLogger(__name__)


# ── Artifact container ────────────────────────────────────────────────

class ModelArtifacts:
    """Container for the seven pre-trained model artifacts loaded at startup.

    Attributes:
        clip_bounds (dict): Columns clipping bounds.
        scaler (sklearn.preprocessing.PowerTransformer): Byte transformer.
        le_proto (LabelEncoder): Protocol label encoder.
        le_dir (LabelEncoder): Direction label encoder.
        xgb_model (xgboost.XGBClassifier): XGBoost classifier.
        tcn_model (keras.Model): Temporal Convolutional Network.
        win_scaler (sklearn.preprocessing.StandardScaler): StandardScaler for windows.
    """

    def __init__(self):
        """Initialize all artifact slots to None."""
        self.clip_bounds = None
        self.scaler      = None
        self.le_proto    = None
        self.le_dir      = None
        self.xgb_model   = None
        self.tcn_model   = None
        self.win_scaler  = None
        self._loaded     = False

    @property
    def is_loaded(self):
        """Check if artifacts are loaded.

        Returns:
            bool: True if loaded, False otherwise.
        """
        return self._loaded


# ── Singleton instance ────────────────────────────────────────────────

_artifacts = ModelArtifacts()


def get_artifacts() -> ModelArtifacts:
    """Retrieve the singleton ModelArtifacts instance.

    Returns:
        ModelArtifacts: The global artifacts container.
    """
    return _artifacts


def load_artifacts() -> ModelArtifacts:
    """Load the seven pre-trained artifacts from the model directory.

    Performs check tests, loads joblib pickles, handles custom Keras TCN
    de-serialization object registers, and runs a dummy forward pass warm-up.

    Returns:
        ModelArtifacts: The populated artifacts singleton.

    Raises:
        RuntimeError: If any required file is missing or loader fails.
    """
    import os
    import tensorflow as tf

    # Disable XLA JIT compilation — causes ELU graph execution errors on some
    # CPU configurations with TF 2.14.0 when TCN inference runs in a thread.
    # Must be set before load_model() is called.
    os.environ["TF_XLA_FLAGS"]          = "--tf_xla_enable_xla_devices=false"
    os.environ["TF_ENABLE_ONEDNN_OPTS"] = "0"
    tf.config.optimizer.set_jit(False)

    global _artifacts

    if _artifacts.is_loaded:
        return _artifacts

    required_files = {
        "clip_bounds": "clip_bounds.pkl",
        "scaler":      "scaler.pkl",
        "le_proto":    "le_proto.pkl",
        "le_dir":      "le_dir.pkl",
        "xgb_model":   "xgb_model.pkl",
        "win_scaler":  "win_scaler.pkl",
    }

    # ── Check that all required files exist ───────────────────────────
    missing = []
    for name, filename in required_files.items():
        path = os.path.join(MODEL_DIR, filename)
        if not os.path.exists(path):
            missing.append(filename)

    # TCN: try .keras first, then SavedModel directory
    tcn_keras_path      = os.path.join(MODEL_DIR, "tcn_best.keras")
    tcn_savedmodel_path = os.path.join(MODEL_DIR, "tcn_model_savedmodel")
    tcn_dir_path        = os.path.join(MODEL_DIR, "tcn_model")
    tcn_path            = None

    if os.path.exists(tcn_keras_path):
        tcn_path = tcn_keras_path
    elif os.path.isdir(tcn_savedmodel_path):
        tcn_path = tcn_savedmodel_path
    elif os.path.isdir(tcn_dir_path):
        tcn_path = tcn_dir_path
    else:
        missing.append("tcn_best.keras (or tcn_model_savedmodel/ or tcn_model/ directory)")

    if missing:
        raise RuntimeError(
            f"Missing model artifacts in {MODEL_DIR}: {', '.join(missing)}. "
            f"Please place all required model files in the models/ directory."
        )

    # ── Load joblib-pickled artifacts ─────────────────────────────────
    try:
        _artifacts.clip_bounds = joblib.load(
            os.path.join(MODEL_DIR, "clip_bounds.pkl")
        )
        logger.info(
            "clip_bounds loaded: %d columns → %s",
            len(_artifacts.clip_bounds),
            list(_artifacts.clip_bounds.keys()),
        )

        # Prefer adapted scaler if it exists (created by byte-column adaptation)
        adapted_scaler_path = os.path.join(MODEL_DIR, "scaler_adapted.pkl")
        if os.path.exists(adapted_scaler_path):
            try:
                _artifacts.scaler = joblib.load(adapted_scaler_path)
                logger.info(
                    "scaler_adapted loaded (overriding base scaler): %s",
                    type(_artifacts.scaler).__name__,
                )
            except Exception as exc:
                logger.error(
                    "Failed to load scaler_adapted.pkl, falling back to base scaler: %s", exc
                )
                _artifacts.scaler = joblib.load(os.path.join(MODEL_DIR, "scaler.pkl"))
                logger.info("scaler loaded (base): %s", type(_artifacts.scaler).__name__)
        else:
            _artifacts.scaler = joblib.load(os.path.join(MODEL_DIR, "scaler.pkl"))
            logger.info("scaler loaded: %s", type(_artifacts.scaler).__name__)

        # Set as the globally active scaler used by scale_features()
        set_active_scaler(_artifacts.scaler)

        _artifacts.le_proto = joblib.load(os.path.join(MODEL_DIR, "le_proto.pkl"))
        logger.info(
            "le_proto loaded: classes = %s", list(_artifacts.le_proto.classes_)
        )

        _artifacts.le_dir = joblib.load(os.path.join(MODEL_DIR, "le_dir.pkl"))
        logger.info(
            "le_dir loaded: classes = %s", list(_artifacts.le_dir.classes_)
        )

        _artifacts.xgb_model = joblib.load(os.path.join(MODEL_DIR, "xgb_model.pkl"))
        logger.info(
            "xgb_model loaded (best_iter=%s)",
            getattr(_artifacts.xgb_model, "best_iteration", "?"),
        )

        _artifacts.win_scaler = joblib.load(os.path.join(MODEL_DIR, "win_scaler.pkl"))
        logger.info("win_scaler loaded: %s", type(_artifacts.win_scaler).__name__)

    except Exception as exc:
        raise RuntimeError(f"Failed to load model artifacts: {exc}") from exc

    # ── Load TCN model ────────────────────────────────────────────────
    # The .keras file was saved with registered_name "Custom>TCN".
    # keras-tcn 3.5.0 does not register that alias automatically, so we
    # force-register it under every name Keras might look it up by before
    # calling load_model().
    try:
        import tensorflow as tf
        import keras as _keras
        from tcn import TCN

        # Register TCN under all names the deserializer may look up.
        # "Custom>TCN" is what the saved config.json contains; the others
        # are defensive aliases for different keras-tcn / Keras versions.
        _keras.utils.get_custom_objects().update({
            "TCN":        TCN,
            "Custom>TCN": TCN,   # ← the critical one for this saved model
            "tcn>TCN":    TCN,
        })

        logger.info("Loading TCN model from: %s", tcn_path)

        with tf.keras.utils.custom_object_scope({
            "TCN":        TCN,
            "Custom>TCN": TCN,
        }):
            _artifacts.tcn_model = tf.keras.models.load_model(
                tcn_path, compile=False
            )

        logger.info(
            "tcn_model loaded: input_shape=%s  output_shape=%s",
            _artifacts.tcn_model.input_shape,
            _artifacts.tcn_model.output_shape,
        )

        # Warm-up call after load — initializes weights in eager mode,
        # prevents a slow first-inference delay in the orchestrator thread
        import numpy as np
        _dummy = np.zeros((1, 20, 19), dtype=np.float32)
        with tf.device('/CPU:0'):
            _ = _artifacts.tcn_model(_dummy, training=False)
        logger.info("TCN warm-up inference completed.")

    except Exception as exc:
        raise RuntimeError(
            f"Failed to load TCN model from {tcn_path}: {exc}\n\n"
            "Troubleshooting:\n"
            "  1. pip install keras-tcn==3.5.6  (match the training environment)\n"
            "  2. Ensure tensorflow==2.15.0 is installed\n"
            "  3. Or re-export the model as a SavedModel directory from the "
            "training environment and place it at models/tcn_model_savedmodel/"
        ) from exc

    _artifacts._loaded = True
    logger.info("✅ All 7 model artifacts loaded successfully.")
    return _artifacts