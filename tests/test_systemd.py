import os
import socket
from pathlib import Path

import pytest

from mi_homekit_bridge.systemd import clock_synchronized, notify, watchdog_interval


def test_notify_sends_datagram(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)  # relative path: AF_UNIX paths are limited to ~100 bytes
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as server:
        server.bind("notify")
        assert notify("READY=1", "STATUS=ok", environ={"NOTIFY_SOCKET": "notify"})
        assert server.recv(100) == b"READY=1\nSTATUS=ok"


def test_notify_without_systemd_is_a_no_op() -> None:
    assert not notify("READY=1", environ={})


def test_notify_survives_a_missing_socket(tmp_path: Path) -> None:
    assert not notify("READY=1", environ={"NOTIFY_SOCKET": str(tmp_path / "gone")})


def test_watchdog_interval() -> None:
    pid = str(os.getpid())
    assert watchdog_interval({"WATCHDOG_USEC": "180000000", "WATCHDOG_PID": pid}) == 90.0
    assert watchdog_interval({"WATCHDOG_USEC": "180000000"}) == 90.0
    assert watchdog_interval({"WATCHDOG_USEC": "180000000", "WATCHDOG_PID": "1"}) is None
    assert watchdog_interval({"WATCHDOG_USEC": "0"}) is None
    assert watchdog_interval({}) is None


def test_clock_synchronized(tmp_path: Path) -> None:
    assert clock_synchronized(tmp_path / "no-timesyncd")
    timesync = tmp_path / "timesync"
    timesync.mkdir()
    assert not clock_synchronized(timesync)
    (timesync / "synchronized").touch()
    assert clock_synchronized(timesync)
