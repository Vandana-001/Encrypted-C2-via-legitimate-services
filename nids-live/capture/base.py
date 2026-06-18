"""
capture/base.py — Abstract CaptureEngine interface.

Both nfstream and scapy capture engines must implement this interface.
Every finished flow is emitted as a dict matching the common output
schema defined in §9.1.
"""

import abc
import queue


class CaptureEngine(abc.ABC):
    """Abstract base class for packet capture engines."""

    @abc.abstractmethod
    def start(self, interface: str) -> None:
        """Start capturing packets on the given interface."""
        ...

    @abc.abstractmethod
    def stop(self) -> None:
        """Stop the capture cleanly."""
        ...

    @abc.abstractmethod
    def get_flow_queue(self) -> queue.Queue:
        """
        Return the queue from which finished flow dicts can be consumed.

        Each item is a dict with exactly these keys:
            StartTime, Dur, Proto, SrcAddr, Sport, Dir,
            DstAddr, Dport, TotPkts, TotBytes, SrcBytes, Label
        """
        ...

    @abc.abstractmethod
    def is_running(self) -> bool:
        """Return True if the engine is actively capturing."""
        ...

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Human-readable name of the engine (e.g. 'nfstream', 'scapy')."""
        ...
