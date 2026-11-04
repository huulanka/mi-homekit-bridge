"""Minimal systemd integration: readiness, status text and the service watchdog.

Implements the ``sd_notify`` datagram protocol directly (a few lines, no extra
dependency). Outside systemd, ``NOTIFY_SOCKET`` is not set and every call is a no-op.
"""

from __future__ import annotations

import logging
import os
import socket
from collections.abc import Mapping
from pathlib import Path

_LOGGER = logging.getLogger(__name__)

TIMESYNC_DIR = Path("/run/systemd/timesync")


def notify(*states: str, environ: Mapping[str, str] | None = None) -> bool:
    """Send ``READY=1``, ``STATUS=...``, ``WATCHDOG=1`` etc. Returns ``True`` if sent."""
    env = os.environ if environ is None else environ
    address = env.get("NOTIFY_SOCKET")
    if not address or not states:
        return False
    if address.startswith("@"):  # abstract namespace
        address = "\0" + address[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.connect(address)
            sock.sendall("\n".join(states).encode())
    except OSError as err:
        _LOGGER.debug("sd_notify failed: %s", err)
        return False
    return True


def watchdog_interval(environ: Mapping[str, str] | None = None) -> float | None:
    """How often to send ``WATCHDOG=1`` (half the configured timeout), or ``None``."""
    env = os.environ if environ is None else environ
    usec = env.get("WATCHDOG_USEC", "")
    pid = env.get("WATCHDOG_PID")
    if not usec.isdigit() or int(usec) == 0:
        return None
    if pid is not None and pid != str(os.getpid()):
        return None
    return int(usec) / 1_000_000 / 2


def clock_synchronized(timesync_dir: Path = TIMESYNC_DIR) -> bool:
    """``False`` while systemd-timesyncd has not synchronized the clock yet.

    A Raspberry Pi has no real-time clock, so right after boot the time can be off
    until NTP catches up. Without systemd-timesyncd the clock is trusted.
    """
    if not timesync_dir.is_dir():
        return True
    return (timesync_dir / "synchronized").exists()
