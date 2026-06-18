"""
pipeline/recalibration.py — Isotonic recalibration for deployment domain.

Fits a two-stage (Logistic + Isotonic) recalibration layer to map raw
XGBoost and TCN predict_proba outputs to true probabilities.
"""

import os
import threading
import logging
import joblib
import numpy as np

from sklearn.linear_model import LogisticRegression
from sklearn.isotonic import IsotonicRegression
from sklearn.model_selection import StratifiedShuffleSplit
from sklearn.metrics import roc_auc_score, average_precision_score

from config import MODEL_DIR

logger = logging.getLogger(__name__)

class ModelRecalibrator:
    """
    Fits and applies recalibrators for XGB and TCN independently.
    """

    def __init__(self):
        self.xgb_lr = None
        self.xgb_iso = None
        self.tcn_lr = None
        self.tcn_iso = None
        self.xgb_weights = None
        self.tcn_weights = None
        self._lock = threading.Lock()
        self._fitted = {"xgb": False, "tcn": False}
        self._load_if_exists()

    def _load_if_exists(self):
        """Load from models/ if fitted artifacts exist."""
        xgb_path = os.path.join(MODEL_DIR, "recal_xgb.pkl")
        tcn_path = os.path.join(MODEL_DIR, "recal_tcn.pkl")

        if os.path.exists(xgb_path):
            try:
                data = joblib.load(xgb_path)
                self.xgb_lr = data["lr"]
                self.xgb_iso = data["iso"]
                self.xgb_weights = data["weights"]
                self._fitted["xgb"] = True
                logger.info("Loaded XGB recalibrator")
            except Exception as exc:
                logger.error("Failed to load %s: %s", xgb_path, exc)

        if os.path.exists(tcn_path):
            try:
                data = joblib.load(tcn_path)
                self.tcn_lr = data["lr"]
                self.tcn_iso = data["iso"]
                self.tcn_weights = data["weights"]
                self._fitted["tcn"] = True
                logger.info("Loaded TCN recalibrator")
            except Exception as exc:
                logger.error("Failed to load %s: %s", tcn_path, exc)

    def is_fitted(self, model: str) -> bool:
        with self._lock:
            return self._fitted.get(model, False)

    def get_status(self) -> dict:
        with self._lock:
            return dict(self._fitted)

    def reset(self):
        with self._lock:
            self.xgb_lr = None
            self.xgb_iso = None
            self.tcn_lr = None
            self.tcn_iso = None
            self.xgb_weights = None
            self.tcn_weights = None
            self._fitted = {"xgb": False, "tcn": False}
        
        xgb_path = os.path.join(MODEL_DIR, "recal_xgb.pkl")
        tcn_path = os.path.join(MODEL_DIR, "recal_tcn.pkl")
        if os.path.exists(xgb_path): os.remove(xgb_path)
        if os.path.exists(tcn_path): os.remove(tcn_path)

    def _compute_weights(self, X, y):
        n_features = X.shape[1]
        weights = np.zeros(n_features)
        for i in range(n_features):
            try:
                auc = roc_auc_score(y, X[:, i])
            except ValueError:
                auc = 0.5
            weights[i] = (auc - 0.5) ** 2
        
        ws = weights.sum()
        if ws > 0:
            weights = weights / ws
        else:
            weights = np.ones(n_features) / n_features
        return weights

    def fit_xgb(self, X_aug: np.ndarray, y_true: np.ndarray, raw_probs: np.ndarray):
        with self._lock:
            self.xgb_weights = self._compute_weights(X_aug, y_true)
            
            # Build recal feature matrix
            X_recal = np.column_stack([
                raw_probs,
                X_aug * self.xgb_weights
            ])

            lr, iso = self._fit_pipeline(X_recal, y_true)
            self.xgb_lr = lr
            self.xgb_iso = iso
            self._fitted["xgb"] = True
            
            joblib.dump({
                "lr": lr,
                "iso": iso,
                "weights": self.xgb_weights
            }, os.path.join(MODEL_DIR, "recal_xgb.pkl"))

    def fit_tcn(self, X_seq_scaled: np.ndarray, y_true: np.ndarray, raw_probs: np.ndarray):
        with self._lock:
            # Build per-window feature matrix
            X_base_mean = X_seq_scaled[:, :, :12].mean(axis=1)  # (N, 12)
            X_win_feat = X_seq_scaled[:, -1, 12:]              # (N, 7)
            X_tcn_feat = np.hstack([X_base_mean, X_win_feat])  # (N, 19)

            self.tcn_weights = self._compute_weights(X_tcn_feat, y_true)
            
            X_recal = np.column_stack([
                raw_probs,
                X_tcn_feat * self.tcn_weights
            ])

            lr, iso = self._fit_pipeline(X_recal, y_true)
            self.tcn_lr = lr
            self.tcn_iso = iso
            self._fitted["tcn"] = True

            joblib.dump({
                "lr": lr,
                "iso": iso,
                "weights": self.tcn_weights
            }, os.path.join(MODEL_DIR, "recal_tcn.pkl"))

    def _fit_pipeline(self, X, y):
        sss = StratifiedShuffleSplit(n_splits=1, test_size=0.7, random_state=42)
        train_idx, eval_idx = next(sss.split(X, y))

        lr = LogisticRegression(C=0.1, max_iter=1000, class_weight="balanced")
        lr.fit(X[train_idx], y[train_idx])

        # predict on eval set
        p_eval = lr.predict_proba(X[eval_idx])[:, 1]
        
        iso = IsotonicRegression(out_of_bounds="clip")
        iso.fit(p_eval, y[eval_idx])

        return lr, iso

    def transform_xgb(self, raw_probs: np.ndarray, X_aug: np.ndarray) -> np.ndarray:
        with self._lock:
            if not self._fitted["xgb"]:
                return raw_probs

            X_recal = np.column_stack([
                raw_probs,
                X_aug * self.xgb_weights
            ])
            p_lr = self.xgb_lr.predict_proba(X_recal)[:, 1]
            return self.xgb_iso.predict(p_lr).astype(np.float32)

    def transform_tcn(self, raw_probs: np.ndarray, X_seq_scaled: np.ndarray) -> np.ndarray:
        with self._lock:
            if not self._fitted["tcn"]:
                return raw_probs

            X_base_mean = X_seq_scaled[:, :, :12].mean(axis=1)
            X_win_feat = X_seq_scaled[:, -1, 12:]
            X_tcn_feat = np.hstack([X_base_mean, X_win_feat])

            X_recal = np.column_stack([
                raw_probs,
                X_tcn_feat * self.tcn_weights
            ])
            p_lr = self.tcn_lr.predict_proba(X_recal)[:, 1]
            return self.tcn_iso.predict(p_lr).astype(np.float32)

# ── Singleton instance ────────────────────────────────────────────────
_recalibrator = ModelRecalibrator()

def get_recalibrator() -> ModelRecalibrator:
    return _recalibrator
