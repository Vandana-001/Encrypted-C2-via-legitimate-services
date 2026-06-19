"""
pipeline/orchestrator.py — Ties capture → features → scaling → models → state.

Runs the main pipeline loop in a background thread so Flask request
handling is never blocked.
"""

import queue
import threading
import logging
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from config import ALL_FEATURES
from pipeline.state import PipelineState
from pipeline.feature_engineering import engineer_features, reset_iat_state
from pipeline.scaling import scale_features
from pipeline.xgb_inference import run_xgb_inference
from pipeline.tcn_inference import process_flow_for_tcn, reset_tcn_state
from pipeline.model_loader import ModelArtifacts
from capture.base import CaptureEngine

from pipeline.threshold_manager import get_manager
from pipeline.calibration import get_calibration_assistant
from pipeline.auto_tuner import get_auto_tuner
from pipeline.scaler_adaptation import get_adaptation_buffer

logger = logging.getLogger(__name__)


class Orchestrator:
    """Orchestrator class tying together flow ingestion, inference, and UI state reporting.

    Pulls completed traffic flow records from the capture engine, directs them
    through the feature engineering, scaling, and model prediction steps, and updates
    the shared thread-safe PipelineState.
    """

    def __init__(self, state: PipelineState, artifacts: ModelArtifacts):
        """Initialize the Orchestrator with references to shared state and models.

        Args:
            state (PipelineState): Thread-safe container for dashboard metrics.
            artifacts (ModelArtifacts): Container containing pre-loaded neural and tree models.
        """
        self.state = state
        self.artifacts = artifacts
        self._engine: CaptureEngine | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._domain_shift_buffer = []
        self._last_domain_shift_time = time.time()

    def start(self, engine: CaptureEngine, interface: str):
        """Start the background orchestrator loop and the sniffer engine.

        Clears historical sequence and IAT trackers before starting.

        Args:
            engine (CaptureEngine): Target packet sniffing engine.
            interface: Interface name to listen on.
        """
        # Reset all state for a new session
        self.state.reset()
        reset_iat_state()
        reset_tcn_state()

        self._engine = engine
        self.state.set_engine(engine.name)

        # Start the capture engine
        try:
            engine.start(interface)
        except Exception as exc:
            self.state.set_status("error", str(exc))
            raise

        # Start the orchestrator loop
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True
        )
        self._thread.start()

        self.state.set_status("running")
        logger.info("Orchestrator started (engine=%s, interface=%s)", engine.name, interface)

    def stop(self):
        """Signal the orchestrator loop to stop and wait for threads to join."""
        self._stop_event.set()

        if self._engine is not None:
            try:
                self._engine.stop()
            except Exception as exc:
                logger.error("Error stopping engine: %s", exc)
            self._engine = None

        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

        self.state.set_status("stopped")
        logger.info("Orchestrator stopped.")

    def is_running(self) -> bool:
        """Check if the orchestrator thread is active and capture is running.

        Returns:
            bool: True if active, False otherwise.
        """
        return (
            self._engine is not None
            and self._engine.is_running()
            and not self._stop_event.is_set()
        )

    def _run_loop(self):
        """Worker thread loop continuously reading completed flows from the engine queue.

        Groups incoming completed flows into mini-batches for feature translation.
        """
        flow_queue = self._engine.get_flow_queue()
        batch_buffer = []
        batch_timeout = 0.5  # collect flows for up to 0.5s before processing

        while not self._stop_event.is_set():
            try:
                # Collect flows in a mini-batch
                try:
                    flow = flow_queue.get(timeout=batch_timeout)
                    # Check for error messages from the engine
                    if isinstance(flow, dict) and "__error__" in flow:
                        self.state.set_status("error", flow["__error__"])
                        logger.error("Capture error: %s", flow["__error__"])
                        break
                    batch_buffer.append(flow)
                except queue.Empty:
                    pass

                # Drain any additional flows that are immediately available
                while len(batch_buffer) < 100:
                    try:
                        flow = flow_queue.get_nowait()
                        if isinstance(flow, dict) and "__error__" in flow:
                            self.state.set_status("error", flow["__error__"])
                            logger.error("Capture error: %s", flow["__error__"])
                            return
                        batch_buffer.append(flow)
                    except queue.Empty:
                        break

                if not batch_buffer:
                    continue

                # Process the mini-batch
                self._process_batch(batch_buffer)
                batch_buffer = []

            except Exception as exc:
                logger.exception("Error in orchestrator loop: %s", exc)
                self.state.set_status("error", str(exc))
                time.sleep(1)

    def _process_batch(self, flows: list[dict]):
        """Direct a batch of flows through the complete feature and model inference sequence.

        Args:
            flows: List of raw completed flow records.
        """
        if not flows:
            return

        # Build DataFrame from flow dicts
        df = pd.DataFrame(flows)
        
        # ── Scaler Adaptation ─────────────────────────────────────────
        adapt_buffer = get_adaptation_buffer()
        if adapt_buffer.is_active():
            for flow in flows:
                adapt_buffer.add(flow)

        # ── Feature engineering ───────────────────────────────────────
        df_feat = engineer_features(
            df,
            self.artifacts.clip_bounds,
            self.artifacts.le_proto,
            self.artifacts.le_dir,
        )

        if len(df_feat) == 0:
            return

        # ── Scaling ───────────────────────────────────────────────────
        df_scaled = scale_features(df_feat)

        # ── Get live thresholds ───────────────────────────────────────
        thresholds = get_manager().get()
        xgb_threshold = thresholds["xgb"]
        tcn_threshold = thresholds["tcn"]

        # ── XGBoost inference (always, per flow) ──────────────────────
        xgb_probs_raw, xgb_probs_recal, xgb_alerts = run_xgb_inference(
            df_scaled, self.artifacts.xgb_model, xgb_threshold
        )

        # ── TCN inference (per flow, rolling buffer) ──────────────────
        for i in range(len(df_scaled)):
            row = df_scaled.iloc[i]

            # Build result dict
            result = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "SrcAddr": str(row.get("SrcAddr", "")),
                "DstAddr": str(row.get("DstAddr", "")),
                "Proto": "",
                "xgb_prob": float(xgb_probs_raw[i]),
                "xgb_prob_recal": float(xgb_probs_recal[i]),
                "xgb_alert": int(xgb_alerts[i]),
                "xgb_threshold": xgb_threshold,
                "tcn_prob": 0.0,
                "tcn_prob_recal": 0.0,
                "tcn_alert": 0,
                "tcn_threshold": tcn_threshold,
            }

            # Try to recover Proto from the encoded value or original data
            if "Proto_enc" in row.index:
                try:
                    result["Proto"] = self.artifacts.le_proto.inverse_transform(
                        [int(row["Proto_enc"])]
                    )[0]
                except Exception:
                    result["Proto"] = "?"

            # Prepare TCN row data
            tcn_row_data = {
                "SrcAddr": result["SrcAddr"],
                "DstAddr": result["DstAddr"],
                "Dport": row.get("Dport", "0"),
                "features": row[ALL_FEATURES].values.astype(np.float32),
                "IAT_raw": float(row.get("IAT_raw", 0.0)),
                "TotBytes_raw": float(row.get("TotBytes_raw", 0.0)),
                "flow_asymmetry": float(row.get("flow_asymmetry", 0.0)),
            }

            # Run TCN inference
            tcn_result = process_flow_for_tcn(
                tcn_row_data, self.artifacts.tcn_model, self.artifacts.win_scaler, tcn_threshold
            )

            if tcn_result is not None:
                result["tcn_prob"] = tcn_result["tcn_prob"]
                result["tcn_prob_recal"] = tcn_result.get("tcn_prob_recal", 0.0)
                result["tcn_alert"] = tcn_result["tcn_alert"]

            # Feed the adaptive threshold layers (calibration & auto-tuning)
            # Use recalibrated probs for adaptation/tuning if available.
            # If not fitted, recal == raw.
            if tcn_result is not None:
                get_calibration_assistant().add_score(result["xgb_prob_recal"], result["tcn_prob_recal"])
                get_auto_tuner().add_score(result["xgb_prob_recal"], bool(result["xgb_alert"]), result["tcn_prob_recal"], bool(result["tcn_alert"]))
            else:
                get_calibration_assistant().add_score(result["xgb_prob_recal"], 0.0)
                get_auto_tuner().add_score(result["xgb_prob_recal"], bool(result["xgb_alert"]), 0.0, False)

            # Write to PipelineState
            self.state.add_flow_result(result)
            
        # ── Domain-Shift Diagnostic ───────────────────────────────────
        self._update_domain_shift_diagnostic(df_scaled)

    def _update_domain_shift_diagnostic(self, df_scaled: pd.DataFrame):
        """Update domain-shift metrics indicating ratio of values near clipping bounds.

        Args:
            df_scaled: Scaled features dataframe.
        """
        import time
        from config import DOMAIN_SHIFT_DIAGNOSTIC_INTERVAL_SEC, DOMAIN_SHIFT_WINDOW_ROWS, ALL_FEATURES
        
        self._domain_shift_buffer.append(df_scaled[ALL_FEATURES].values.astype(np.float32))
        
        now = time.time()
        if now - self._last_domain_shift_time >= DOMAIN_SHIFT_DIAGNOSTIC_INTERVAL_SEC:
            if not self._domain_shift_buffer:
                return
            
            # Concatenate and trim
            X_all = np.vstack(self._domain_shift_buffer)
            if len(X_all) > DOMAIN_SHIFT_WINDOW_ROWS:
                X_all = X_all[-DOMAIN_SHIFT_WINDOW_ROWS:]
            
            # Keep trimmed buffer
            self._domain_shift_buffer = [X_all]
            self._last_domain_shift_time = now
            
            # Near boundary check
            near_bound = np.abs(X_all) >= 3.999
            for i, col in enumerate(ALL_FEATURES):
                self.state.clip_boundary_stats[col] = float(near_bound[:, i].mean())
