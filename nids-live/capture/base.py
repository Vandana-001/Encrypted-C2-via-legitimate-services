"""
capture/base.py — Abstract CaptureEngine interface.

Both nfstream and scapy capture engines must implement this interface.
Every finished flow is emitted as a dict matching the common output
schema defined in §9.1.
"""

import abc
import queue


class CaptureEngine(abc.ABC):
    """Abstract base class for packet capture engines.

    Defines the contract for capture loops executing on a network interface.
    Emitted flows must match the common NIDS flow dictionary schema.
    """

    @abc.abstractmethod
    def start(self, interface: str) -> None:
        """Start capturing packets on the specified network interface.

        Args:
            interface: Name of the network interface card (NIC) to capture from.

        Raises:
            PermissionError: If administrative privileges are missing.
            ValueError: If the interface is invalid or unavailable.
        """
        ...

    @abc.abstractmethod
    def stop(self) -> None:
        """Stop packet capture and clean up active threads or sniffers.

        Ensures resources like raw sockets are closed cleanly.
        """
        ...

    @abc.abstractmethod
    def get_flow_queue(self) -> queue.Queue:
        """Get the queue containing completed flow dictionaries.

        Returns:
            queue.Queue: Queue where flow records matching the common schema are pushed.
        """
        ...

    @abc.abstractmethod
    def is_running(self) -> bool:
        """Check if the capture engine is currently active.

        Returns:
            bool: True if the engine is running and capture is active, False otherwise.
        """
        ...

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Get the name of the capture engine.

        Returns:
            str: Human-readable identifier of the engine (e.g. 'nfstream' or 'scapy').
        """
        ...
