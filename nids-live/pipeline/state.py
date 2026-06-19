"""
pipeline/state.py — Thread-safe PipelineState holding all live inference results.

Guarded by a single threading.Lock so the capture thread and Flask
request threads can safely access the state concurrently.
"""

import collections
import threading
import time
from datetime import datetime, timezone


class PipelineState:
    """Thread-safe container for all live pipeline metrics and alerts.

    Synchronizes concurrently written stats from the sniffer thread and read
    queries from Flask dashboard threads.
    """

    def __init__(self):
        """Initialize pipeline counters, deques, summaries, and lock."""
        self._lock = threading.Lock()

        # Recent flow inference results for the live table
        self.recent_flows: collections.deque = collections.deque(maxlen=300)

        # Flows/sequences where xgb_alert==1 or tcn_alert==1
        self.alerts: collections.deque = collections.deque(maxlen=500)

        # Running max prob + alert counts per SrcAddr
        self.per_ip_summary: dict[str, dict] = {}

        # Counters
        self.total_flows_processed: int = 0
        self.total_packets_seen: int = 0
        self.xgb_alert_count: int = 0
        self.tcn_alert_count: int = 0
        self.start_time: float | None = None
        self.status: str = "stopped"   # stopped / running / error
        self.last_error: str = ""
        self.active_engine: str = ""
        self.clip_boundary_stats: dict = {}

    def reset(self):
        """Reset all metric counters, flow lists, and timers to startup states."""
        with self._lock:
            self.recent_flows.clear()
            self.alerts.clear()
            self.per_ip_summary.clear()
            self.total_flows_processed = 0
            self.total_packets_seen = 0
            self.xgb_alert_count = 0
            self.tcn_alert_count = 0
            self.start_time = time.time()
            self.status = "running"
            self.last_error = ""
            self.clip_boundary_stats = {}

    def set_status(self, status: str, error: str = ""):
        """Update system runtime status thread-safely.

        Args:
            status: Target state ("running", "stopped", "error").
            error: Descriptive error message if status is "error".
        """
        with self._lock:
            self.status = status
            if error:
                self.last_error = error

    def set_engine(self, engine_name: str):
        """Register the currently running capture engine identifier.

        Args:
            engine_name: The engine name ("nfstream" or "scapy").
        """
        with self._lock:
            self.active_engine = engine_name

    def add_flow_result(self, result: dict):
        """Insert a newly processed flow inference result dictionary.

        Updates cumulative metrics and aggregates IP summary records.

        Args:
            result: Completed flow dictionary with scores and alert flags.
        """
        with self._lock:
            self.recent_flows.append(result)
            self.total_flows_processed += 1

            is_alert = False

            # XGBoost alert tracking
            if result.get("xgb_alert", 0) == 1:
                self.xgb_alert_count += 1
                is_alert = True

            # TCN alert tracking
            if result.get("tcn_alert", 0) == 1:
                self.tcn_alert_count += 1
                is_alert = True

            if is_alert:
                self.alerts.append(result)

            # Update per-IP summary
            src = result.get("SrcAddr", "")
            if src:
                if src not in self.per_ip_summary:
                    self.per_ip_summary[src] = {
                        "SrcAddr": src,
                        "xgb_max_prob": 0.0,
                        "tcn_max_prob": 0.0,
                        "xgb_alert_count": 0,
                        "tcn_alert_count": 0,
                        "total_flows": 0,
                    }

                summary = self.per_ip_summary[src]
                summary["total_flows"] += 1

                xgb_prob = result.get("xgb_prob", 0.0)
                tcn_prob = result.get("tcn_prob", 0.0)

                if xgb_prob > summary["xgb_max_prob"]:
                    summary["xgb_max_prob"] = xgb_prob
                if tcn_prob > summary["tcn_max_prob"]:
                    summary["tcn_max_prob"] = tcn_prob
                if result.get("xgb_alert", 0) == 1:
                    summary["xgb_alert_count"] += 1
                if result.get("tcn_alert", 0) == 1:
                    summary["tcn_alert_count"] += 1

    def get_status(self) -> dict:
        """Fetch general pipeline status metrics.

        Returns:
            dict: Pipeline status summary including status, engine, and metrics.
        """
        with self._lock:
            uptime = 0.0
            if self.start_time is not None:
                uptime = time.time() - self.start_time

            return {
                "status": self.status,
                "engine": self.active_engine,
                "uptime_sec": round(uptime, 1),
                "total_flows": self.total_flows_processed,
                "total_packets": self.total_packets_seen,
                "xgb_alerts": self.xgb_alert_count,
                "tcn_alerts": self.tcn_alert_count,
                "last_error": self.last_error,
            }

    def get_recent_flows(self, limit: int = 50) -> list[dict]:
        """Get list of most recently processed flows.

        Args:
            limit: Maximum count to return.

        Returns:
            list[dict]: List of recent flow metrics.
        """
        with self._lock:
            items = list(self.recent_flows)
            return items[-limit:]

    def get_alerts(self, limit: int = 50) -> list[dict]:
        """Get list of recent alert results.

        Args:
            limit: Maximum count to return.

        Returns:
            list[dict]: List of alert dictionaries.
        """
        with self._lock:
            items = list(self.alerts)
            return items[-limit:]

    def get_top_ips(self, limit: int = 10) -> list[dict]:
        """Get list of source IPs sorted by highest anomaly probability.

        Args:
            limit: Maximum count to return.

        Returns:
            list[dict]: Sorted top anomaly source IPs.
        """
        with self._lock:
            if not self.per_ip_summary:
                return []

            sorted_ips = sorted(
                self.per_ip_summary.values(),
                key=lambda x: max(x["xgb_max_prob"], x["tcn_max_prob"]),
                reverse=True,
            )
            return sorted_ips[:limit]
