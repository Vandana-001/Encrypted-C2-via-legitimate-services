"""
capture/scapy_engine.py — Fallback capture engine using scapy AsyncSniffer.

Works on all platforms (Windows, Linux, macOS).
Uses scapy.all.AsyncSniffer(prn=callback, store=False) with a manual
flow table keyed by the 5-tuple (src_ip, dst_ip, sport, dport, proto).

A background timer (every 1 second) scans the flow table and expires
entries based on IDLE_TIMEOUT_SEC and ACTIVE_TIMEOUT_SEC.
"""

import queue
import time
import threading
import logging
from datetime import datetime, timezone

import numpy as np

from capture.base import CaptureEngine
from config import EPSILON, IDLE_TIMEOUT_SEC, ACTIVE_TIMEOUT_SEC

logger = logging.getLogger(__name__)


class ScapyEngine(CaptureEngine):
    """Scapy-based capture engine using AsyncSniffer and a manual flow table.

    Tracks individual packets and groups them into flow structures using a
    hash-based flow table. Periodically expires idle or long-running flows.
    """

    def __init__(self):
        """Initialize the Scapy sniffer engine and flow tracking components."""
        self._flow_queue: queue.Queue = queue.Queue()
        self._flow_table: dict = {}
        self._flow_lock = threading.Lock()
        self._sniffer = None
        self._expiry_timer: threading.Timer | None = None
        self._running = False
        self._stop_event = threading.Event()

    @property
    def name(self) -> str:
        """Get the name identifier of this capture engine.

        Returns:
            str: "scapy"
        """
        return "scapy"

    def get_flow_queue(self) -> queue.Queue:
        """Get the queue where completed flows are appended.

        Returns:
            queue.Queue: Queue container for flow records.
        """
        return self._flow_queue

    def is_running(self) -> bool:
        """Check if the Scapy packet sniffer is currently active.

        Returns:
            bool: True if sniff loop is running, False otherwise.
        """
        return self._running

    def start(self, interface: str) -> None:
        """Start capturing packets on the network interface.

        Spins up the Scapy AsyncSniffer and schedules the periodic flow expiry loop.

        Args:
            interface: Name of the interface to sniff on.

        Raises:
            PermissionError: If administrative privileges are missing.
            RuntimeError: If packet sniffer initialization fails.
        """
        from scapy.all import AsyncSniffer

        self._stop_event.clear()
        self._running = True

        self._sniffer = AsyncSniffer(
            iface=interface,
            prn=self._packet_callback,
            store=False,
        )

        try:
            self._sniffer.start()
        except PermissionError as exc:
            self._running = False
            raise PermissionError(
                "Permission denied opening interface — run as Administrator "
                "(Windows) or with sudo/setcap (Linux/macOS)."
            ) from exc
        except Exception as exc:
            self._running = False
            raise RuntimeError(
                f"Failed to start packet capture on '{interface}': {exc}"
            ) from exc

        # Start the expiry timer
        self._schedule_expiry()
        logger.info("ScapyEngine started on interface '%s'", interface)

    def stop(self) -> None:
        """Stop capturing packets, cancel timers, and flush remaining flows."""
        self._stop_event.set()
        self._running = False

        if self._sniffer is not None:
            try:
                self._sniffer.stop()
            except Exception:
                pass
            self._sniffer = None

        # Expire remaining flows
        self._expire_flows(force_all=True)
        logger.info("ScapyEngine stopped.")

    def _packet_callback(self, pkt):
        """Callback function executed for every captured packet.

        Extracts headers, updates the flow table tracking state.

        Args:
            pkt: Scapy packet object.
        """
        from scapy.all import IP, TCP, UDP, ICMP

        if IP not in pkt:
            return

        ip = pkt[IP]
        ts = float(pkt.time)
        plen = len(pkt)

        if TCP in pkt:
            proto = "tcp"
            sport = str(pkt[TCP].sport)
            dport = str(pkt[TCP].dport)
        elif UDP in pkt:
            proto = "udp"
            sport = str(pkt[UDP].sport)
            dport = str(pkt[UDP].dport)
        elif ICMP in pkt:
            proto = "icmp"
            sport = "0"
            dport = "0"
        else:
            proto = str(ip.proto)
            sport = "0"
            dport = "0"

        key = (ip.src, ip.dst, sport, dport, proto)

        with self._flow_lock:
            if key in self._flow_table:
                entry = self._flow_table[key]
                entry["last_ts"] = ts
                entry["tot_pkts"] += 1
                entry["tot_bytes"] += plen
                entry["src_bytes"] += plen
            else:
                self._flow_table[key] = {
                    "first_ts": ts,
                    "last_ts": ts,
                    "tot_pkts": 1,
                    "tot_bytes": plen,
                    "src_bytes": plen,
                    "proto": proto,
                }

    def _schedule_expiry(self):
        """Schedule the next flow expiry check thread."""
        if self._stop_event.is_set():
            return
        self._expiry_timer = threading.Timer(1.0, self._run_expiry)
        self._expiry_timer.daemon = True
        self._expiry_timer.start()

    def _run_expiry(self):
        """Worker thread entry point to run flow checks and reschedule."""
        self._expire_flows(force_all=False)
        self._schedule_expiry()

    def _expire_flows(self, force_all: bool = False):
        """Evaluate flow durations and idle times to move expired flows to emission queue.

        Args:
            force_all: If True, expires all current tracking flows immediately.
        """
        now = time.time()
        to_emit = []

        with self._flow_lock:
            keys_to_remove = []
            for key, entry in self._flow_table.items():
                idle = now - entry["last_ts"]
                active = entry["last_ts"] - entry["first_ts"]

                if force_all or idle > IDLE_TIMEOUT_SEC or active > ACTIVE_TIMEOUT_SEC:
                    keys_to_remove.append(key)
                    to_emit.append((key, entry))

            for key in keys_to_remove:
                del self._flow_table[key]

        # Emit expired flows as dicts matching §9.1 schema
        for key, entry in to_emit:
            src_ip, dst_ip, sport, dport, proto = key
            dur = max(entry["last_ts"] - entry["first_ts"], EPSILON)
            start_time = datetime.fromtimestamp(
                entry["first_ts"], tz=timezone.utc
            )

            flow_dict = {
                "StartTime": start_time,
                "Dur": dur,
                "Proto": entry["proto"],
                "SrcAddr": src_ip,
                "Sport": sport,
                "Dir": "->",
                "DstAddr": dst_ip,
                "Dport": dport,
                "TotPkts": entry["tot_pkts"],
                "TotBytes": entry["tot_bytes"],
                "SrcBytes": entry["src_bytes"],
                "Label": "Unknown",
            }
            self._flow_queue.put(flow_dict)
