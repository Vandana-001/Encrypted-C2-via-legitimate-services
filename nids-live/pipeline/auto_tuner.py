"""
pipeline/auto_tuner.py — Bounded Continuous Auto-Tuning (Layer 3).

A background thread that evaluates candidate thresholds periodically based
on a trailing window of scores. Explicitly excludes flows that were already
flagged as alerts, clamps step sizes, and respects hard floor/ceiling limits.
"""

import collections
import threading
import time
import logging
import numpy as np

import config
from pipeline.threshold_manager import get_manager, clip

logger = logging.getLogger(__name__)

class ScoreEvent:
    """Represents a single model anomaly score observation.

    Attributes:
        ts (float): Epoch timestamp when the observation occurred.
        prob (float): Anomaly score/probability value.
        was_alert (bool): Whether the score exceeded the active threshold and triggered an alert.
    """
    __slots__ = ['ts', 'prob', 'was_alert']
    def __init__(self, ts: float, prob: float, was_alert: bool):
        """Initialize the ScoreEvent record."""
        self.ts = ts
        self.prob = prob
        self.was_alert = was_alert

class ScoreHistory:
    """Thread-safe sliding buffer maintaining a history of ScoreEvents."""
    def __init__(self):
        """Initialize the queue collection and lock helper."""
        self.events = collections.deque()
        self._lock = threading.Lock()
        
    def add(self, prob: float, was_alert: bool):
        """Record a new anomaly score event into the history.

        Args:
            prob: Anomaly score value.
            was_alert: True if the score triggered a system alert.
        """
        with self._lock:
            self.events.append(ScoreEvent(time.time(), prob, was_alert))
            
    def trailing(self, window_sec: float) -> list[ScoreEvent]:
        """Evict stale logs and return events falling within the trailing duration window.

        Args:
            window_sec: Duration in seconds to look back (e.g. 1800).

        Returns:
            list[ScoreEvent]: A list of qualifying history events.
        """
        now = time.time()
        cutoff = now - window_sec
        with self._lock:
            # Purge old events
            while self.events and self.events[0].ts < cutoff:
                self.events.popleft()
            return list(self.events)


class AutoTuner:
    """Coordinates the passive auto-tuning background worker loop.

    Monitors incoming traffic scores, builds baseline percentiles over trailing windows,
    and increments/decrements model thresholds incrementally.
    """
    def __init__(self):
        """Initialize the AutoTuner trackers and start the background thread."""
        self._lock = threading.Lock()
        self.enabled = config.AUTO_TUNE_ENABLED_DEFAULT
        self.score_history = {
            "xgb": ScoreHistory(),
            "tcn": ScoreHistory()
        }
        self._thread = None
        self._stop_event = threading.Event()
        
        # Start background thread immediately, though it will idle if not enabled
        self._start_thread()

    def set_enabled(self, enabled: bool):
        """Enable or disable the auto-tuning worker.

        Args:
            enabled: If True, auto-tuning is activated.
        """
        with self._lock:
            self.enabled = enabled
            logger.info("Auto-tune enabled state changed to: %s", enabled)

    def is_enabled(self) -> bool:
        """Check if the auto-tuner is active.

        Returns:
            bool: True if auto-tuning is enabled, False otherwise.
        """
        with self._lock:
            return self.enabled

    def add_score(self, xgb_prob: float, xgb_alert: bool, tcn_prob: float, tcn_alert: bool):
        """Register newly generated model scores to the history queues.

        Args:
            xgb_prob: Anomaly score from the XGBoost model.
            xgb_alert: Trigger status of the XGBoost model.
            tcn_prob: Anomaly score from the TCN model.
            tcn_alert: Trigger status of the TCN model.
        """
        # Only bother recording if enabled
        if not self.is_enabled():
            return
        self.score_history["xgb"].add(xgb_prob, xgb_alert)
        self.score_history["tcn"].add(tcn_prob, tcn_alert)

    def _start_thread(self):
        """Spin up the daemon worker thread."""
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def _run_loop(self):
        """Background loop executing the auto-tune cycle periodically."""
        while not self._stop_event.is_set():
            # Wait for AUTO_TUNE_INTERVAL_SEC, interruptible by stop event
            if self._stop_event.wait(config.AUTO_TUNE_INTERVAL_SEC):
                break
                
            if not self.is_enabled():
                continue
                
            try:
                self._auto_tune_cycle()
            except Exception as exc:
                logger.error("Error in auto-tune cycle: %s", exc)

    def _auto_tune_cycle(self):
        """Execute one evaluation check and apply bounded threshold increments."""
        threshold_mgr = get_manager()
        current_thresholds = threshold_mgr.get()
        
        floor = {"xgb": config.XGB_THRESHOLD_FLOOR, "tcn": config.TCN_THRESHOLD_FLOOR}
        ceiling = {"xgb": config.XGB_THRESHOLD_CEILING, "tcn": config.TCN_THRESHOLD_CEILING}

        for model in ("xgb", "tcn"):
            window = self.score_history[model].trailing(config.AUTO_TUNE_WINDOW_SEC)
            
            # Critical safeguard: exclude anything that was itself flagged as an alert
            # at the threshold in effect when it was scored.
            qualifying = [s.prob for s in window if not s.was_alert]
            n_samples = len(qualifying)
            
            if n_samples < config.AUTO_TUNE_MIN_SAMPLES:
                continue

            candidate_raw = np.percentile(qualifying, config.AUTO_TUNE_PERCENTILE)
            current = current_thresholds[model]
            
            # Clamp the step size
            max_step = current * config.AUTO_TUNE_MAX_STEP_FRACTION
            step = clip(candidate_raw - current, -max_step, max_step)
            
            # Apply step and clamp to global floor/ceiling
            new_value = current + step
            new_value = clip(new_value, floor[model], ceiling[model])

            if abs(new_value - current) > 1e-6:
                logger.info("Auto-tuning %s threshold: %.4f -> %.4f (candidate %.4f, %d samples)", 
                            model, current, new_value, candidate_raw, n_samples)
                
                kwargs = {
                    model: float(new_value),
                    "reason": "auto_tune",
                    f"candidate_raw_{model}": float(candidate_raw),
                    "n_samples": n_samples
                }
                threshold_mgr.set(**kwargs)


# ── Singleton instance ────────────────────────────────────────────────
_auto_tuner = AutoTuner()

def get_auto_tuner() -> AutoTuner:
    """Retrieve the singleton AutoTuner instance.

    Returns:
        AutoTuner: The global auto-tuner orchestrator.
    """
    return _auto_tuner
