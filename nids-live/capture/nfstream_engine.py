"""
capture/nfstream_engine.py

Primary capture engine for Linux/macOS.
Runs nfstream in a daemon thread (not a process) so it can be
spawned from inside Flask's threaded server without hitting the
'daemonic processes are not allowed to have children' restriction.
"""

import logging
import queue
import threading

import pandas as pd

from capture.base import CaptureEngine
from config import IDLE_TIMEOUT_SEC, ACTIVE_TIMEOUT_SEC

logger = logging.getLogger(__name__)


class NFStreamEngine(CaptureEngine):
    """
    Primary capture engine for Linux/macOS.
    Runs nfstream in a daemon *thread* (not a process) so it can be
    spawned from inside Flask's threaded server without hitting the
    'daemonic processes are not allowed to have children' restriction.
    The public API is identical to the old version so orchestrator.py is unchanged.
    """

    def __init__(self):
        self._thread      = None
        self._queue       = queue.Queue(maxsize=10_000)
        self._stop_event  = threading.Event()
        self._running     = False

    @property
    def name(self) -> str:
        return "nfstream"

    def get_flow_queue(self) -> queue.Queue:
        return self._queue

    def is_running(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    # ── Public interface ──────────────────────────────────────────────

    def start(self, interface: str):
        """Start capturing on *interface* in a background daemon thread."""
        self._stop_event.clear()
        # Drain any leftover items from a previous run
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

        self._running = True
        self._thread = threading.Thread(
            target=self._capture_loop,
            args=(interface,),
            daemon=True,          # daemon THREAD is fine — only daemon
            name="nfstream-capture",  # *processes* cannot have children
        )
        self._thread.start()
        logger.info("NFStreamEngine started on interface: %s", interface)

    def stop(self):
        """Signal the capture loop to stop and wait for the thread to exit."""
        self._running = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._thread = None
        logger.info("NFStreamEngine stopped.")

    # ── Internal capture loop (runs in background thread) ─────────────

    def _capture_loop(self, interface: str):
        try:
            from nfstream import NFStreamer

            streamer = NFStreamer(
                source=interface,
                statistical_analysis=True,
                idle_timeout=IDLE_TIMEOUT_SEC,
                active_timeout=ACTIVE_TIMEOUT_SEC,
            )

            for flow in streamer:
                if self._stop_event.is_set():
                    break

                flow_dict = {
                    "StartTime": pd.Timestamp(
                        flow.bidirectional_first_seen_ms, unit="ms", tz="UTC"
                    ),
                    "Dur":     flow.bidirectional_duration_ms / 1000.0,
                    "Proto":   (
                        flow.protocol_name.lower()
                        if hasattr(flow, "protocol_name")
                        else str(flow.protocol)
                    ),
                    "SrcAddr": flow.src_ip,
                    "Sport":   str(flow.src_port),
                    "Dir":     "->",
                    "DstAddr": flow.dst_ip,
                    "Dport":   str(flow.dst_port),
                    "TotPkts": flow.bidirectional_packets,
                    "TotBytes": flow.bidirectional_bytes,
                    "SrcBytes": flow.src2dst_bytes,
                    "Label":   "Unknown",
                }

                try:
                    self._queue.put_nowait(flow_dict)
                except queue.Full:
                    # Queue is full — drop the oldest item and insert the new one
                    # so we always have the most recent flows rather than stalling
                    try:
                        self._queue.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        self._queue.put_nowait(flow_dict)
                    except queue.Full:
                        pass

        except PermissionError:
            msg = (
                "Permission denied opening interface — run with sudo, or grant "
                "capabilities once: sudo setcap cap_net_raw,cap_net_admin=eip "
                "$(readlink -f $(which python3))"
            )
            logger.error(msg)
            try:
                self._queue.put_nowait({"__error__": msg})
            except queue.Full:
                pass

        except Exception as exc:
            msg = f"NFStream capture error: {exc}"
            logger.error(msg)
            try:
                self._queue.put_nowait({"__error__": msg})
            except queue.Full:
                pass
        finally:
            self._running = False
