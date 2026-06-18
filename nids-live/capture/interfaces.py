"""
capture/interfaces.py — Cross-platform NIC enumeration and engine selection.
"""

import platform
import logging

logger = logging.getLogger(__name__)


def list_interfaces() -> list[str]:
    """
    List available network interfaces.
    Uses scapy's get_if_list() which works cross-platform via libpcap/Npcap.
    """
    try:
        from scapy.all import get_if_list
        return get_if_list()
    except Exception as exc:
        logger.error("Failed to enumerate interfaces: %s", exc)
        return []


def select_capture_engine():
    """
    Choose the best capture engine for the current platform.

    Returns the engine CLASS (not an instance).
    - Linux/macOS with nfstream available → NFStreamEngine
    - Otherwise (Windows, or nfstream unavailable) → ScapyEngine
    """
    if platform.system() in ("Linux", "Darwin"):
        try:
            import nfstream  # noqa: F401
            from capture.nfstream_engine import NFStreamEngine
            logger.info("Engine selection: nfstream available → NFStreamEngine")
            return NFStreamEngine
        except ImportError:
            logger.info("Engine selection: nfstream not available, falling back to ScapyEngine")

    from capture.scapy_engine import ScapyEngine
    logger.info("Engine selection: ScapyEngine (universal fallback)")
    return ScapyEngine


def get_engine_by_name(name: str):
    """
    Get a capture engine class by name.
    Supports: 'auto', 'nfstream', 'scapy'.
    """
    if name == "auto":
        return select_capture_engine()
    elif name == "nfstream":
        from capture.nfstream_engine import NFStreamEngine
        return NFStreamEngine
    elif name == "scapy":
        from capture.scapy_engine import ScapyEngine
        return ScapyEngine
    else:
        raise ValueError(f"Unknown engine name: {name}")
