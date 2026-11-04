import json
from pathlib import Path

import pytest
from bleak.exc import BleakDBusError

from mi_homekit_bridge.bluetooth import (
    RESET_MARKER,
    ControllerResetRequired,
    ResetError,
    ScanState,
    ScanSupervisor,
    Timings,
    reset_controller,
)

TIMINGS = Timings(
    start_timeout=1.0,
    silence=300.0,
    confirm=60.0,
    retry_delays=(10.0, 30.0, 60.0),
    escalate_after=3,
    reset_cooldown=1800.0,
)

IN_PROGRESS = BleakDBusError("org.bluez.Error.InProgress", ["Operation already in progress"])


class FakeScanner:
    def __init__(self, plan: "Plan") -> None:
        self._plan = plan

    async def start(self) -> None:
        self._plan.starts += 1
        if self._plan.fail:
            raise IN_PROGRESS
        self._plan.running = True

    async def stop(self) -> None:
        self._plan.running = False


class Plan:
    """Shared state of all scanners created by the factory."""

    def __init__(self) -> None:
        self.fail = False
        self.running = False
        self.starts = 0

    def factory(self) -> FakeScanner:
        return FakeScanner(self)


class Events(list[tuple[str, dict[str, object]]]):
    """Events passed to the supervisor's listener."""


def state(sup: ScanSupervisor) -> ScanState:
    """Read the state without mypy narrowing it across awaits."""
    return sup.state


class Clock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def make(tmp_path: Path, plan: Plan, events: Events, wall: Clock) -> ScanSupervisor:
    return ScanSupervisor(
        plan.factory,
        state_dir=tmp_path,
        timings=TIMINGS,
        listener=lambda kind, data: events.append((kind, data)),
        wall_clock=wall,
    )


async def test_starts_and_stays_running_while_advertisements_arrive(tmp_path: Path) -> None:
    plan, events = Plan(), Events()
    sup = make(tmp_path, plan, events, Clock())
    await sup.start(0.0)
    assert state(sup) is ScanState.RUNNING
    for t in range(0, 3600, 60):
        sup.advertisement_seen(float(t))
        await sup.check(float(t) + 30)
    assert state(sup) is ScanState.RUNNING
    assert plan.starts == 1
    assert events == []


async def test_silence_restarts_scan_and_recovers_on_next_advertisement(tmp_path: Path) -> None:
    plan, events = Plan(), Events()
    sup = make(tmp_path, plan, events, Clock())
    await sup.start(0.0)
    sup.advertisement_seen(10.0)

    await sup.check(320.0)  # 310 s without anything
    assert plan.starts == 2
    assert state(sup) is ScanState.RECOVERING
    assert events[0][0] == "scan_silent"

    sup.advertisement_seen(330.0)
    assert state(sup) is ScanState.RUNNING
    assert events[-1] == ("scan_recovered", {"seconds": 10})


async def test_stuck_controller_requests_reset(tmp_path: Path) -> None:
    """What happened on 2026-11-04: the controller hangs, every scan start fails."""
    plan, events, wall = Plan(), Events(), Clock()
    sup = make(tmp_path, plan, events, wall)
    await sup.start(0.0)
    sup.advertisement_seen(5.0)

    plan.fail = True
    await sup.check(310.0)  # silence (failure 1) -> immediate restart fails (failure 2)
    assert state(sup) is ScanState.RECOVERING
    await sup.check(315.0)  # before the retry delay: nothing happens
    assert plan.starts == 2
    with pytest.raises(ControllerResetRequired):
        await sup.check(340.0)  # failure 3 -> reset, about 5.5 minutes after the hang

    assert [kind for kind, _ in events] == ["scan_silent", "bluetooth_reset"]
    assert "InProgress" in str(events[-1][1]["error"])
    marker = json.loads((tmp_path / RESET_MARKER).read_text())
    assert marker["requested_at"] == wall.now
    assert sup.last_reset() == wall.now


async def test_failing_start_is_retried_with_backoff(tmp_path: Path) -> None:
    plan, events = Plan(), Events()
    plan.fail = True
    sup = make(tmp_path, plan, events, Clock())
    await sup.start(0.0)  # does not raise
    assert state(sup) is ScanState.RECOVERING
    assert events[0][0] == "scan_failed"

    await sup.check(5.0)
    assert plan.starts == 1  # waits 10 s
    plan.fail = False
    await sup.check(10.0)
    assert plan.starts == 2
    assert state(sup) is ScanState.RECOVERING  # started, but not confirmed yet
    sup.advertisement_seen(12.0)
    assert state(sup) is ScanState.RUNNING


async def test_started_but_silent_counts_as_failure(tmp_path: Path) -> None:
    plan, events = Plan(), Events()
    plan.fail = True
    sup = make(tmp_path, plan, events, Clock())
    await sup.start(0.0)
    plan.fail = False
    await sup.check(10.0)  # starts, but nothing arrives
    await sup.check(40.0)
    assert state(sup) is ScanState.RECOVERING
    await sup.check(71.0)  # confirm window over -> second failure, scanner stopped
    assert not plan.running
    assert sup.last_error == "scan started but nothing was received"
    await sup.check(101.0)  # retry after 30 s
    with pytest.raises(ControllerResetRequired):
        await sup.check(162.0)  # silent again -> third failure


async def test_reset_cooldown_keeps_bridge_running(tmp_path: Path) -> None:
    plan, events, wall = Plan(), Events(), Clock()
    (tmp_path / RESET_MARKER).write_text(json.dumps({"requested_at": wall.now - 600}))
    plan.fail = True
    sup = make(tmp_path, plan, events, wall)
    await sup.start(0.0)
    await sup.check(10.0)
    await sup.check(40.0)  # third failure, but a reset happened 10 minutes ago
    assert state(sup) is ScanState.FAILED
    assert [kind for kind, _ in events] == ["scan_failed", "bluetooth_failed"]

    await sup.check(80.0)
    assert plan.starts == 3  # longest delay (60 s) from now on
    await sup.check(100.0)
    assert plan.starts == 4
    assert state(sup) is ScanState.FAILED
    assert [kind for kind, _ in events].count("bluetooth_failed") == 1

    wall.now += 1800  # cooldown over
    with pytest.raises(ControllerResetRequired):
        await sup.check(160.0)


async def test_without_state_dir_never_requests_a_reset(tmp_path: Path) -> None:
    plan, events = Plan(), Events()
    plan.fail = True
    sup = ScanSupervisor(plan.factory, timings=TIMINGS, listener=lambda k, d: events.append((k, d)))
    await sup.start(0.0)
    for t in (10.0, 40.0, 100.0, 160.0):
        await sup.check(t)
    assert state(sup) is ScanState.FAILED


async def test_hanging_start_times_out(tmp_path: Path) -> None:
    class Hanging:
        async def start(self) -> None:
            import asyncio

            await asyncio.sleep(10)

        async def stop(self) -> None:
            return None

    sup = ScanSupervisor(Hanging, timings=Timings(start_timeout=0.01))
    await sup.start(0.0)
    assert state(sup) is ScanState.RECOVERING
    assert sup.last_error == "TimeoutError"


def _fake_sysfs(root: Path) -> tuple[Path, Path]:
    device = root / "devices" / "platform" / "serial0" / "serial0-0"
    driver = root / "bus" / "serial" / "drivers" / "hci_uart_bcm"
    (device / "bluetooth" / "hci0").mkdir(parents=True)
    driver.mkdir(parents=True)
    for name in ("bind", "unbind"):
        (driver / name).write_text("")
    (device / "driver").symlink_to(driver)
    hci = root / "class" / "bluetooth" / "hci0"
    hci.mkdir(parents=True)
    (hci / "device").symlink_to(device)
    return device, driver


def test_reset_controller_rebinds_driver(tmp_path: Path) -> None:
    device, driver = _fake_sysfs(tmp_path)
    sleeps: list[float] = []
    assert reset_controller("hci0", sys_root=tmp_path, sleep=sleeps.append) == device.resolve()
    assert (driver / "unbind").read_text() == "serial0-0"
    assert (driver / "bind").read_text() == "serial0-0"
    assert sleeps == [1.0]


def test_reset_controller_reports_missing_adapter(tmp_path: Path) -> None:
    _fake_sysfs(tmp_path)
    with pytest.raises(ResetError, match="hci1 not found"):
        reset_controller("hci1", sys_root=tmp_path)


def test_reset_controller_waits_for_adapter(tmp_path: Path) -> None:
    device, _ = _fake_sysfs(tmp_path)
    (device / "bluetooth" / "hci0").rmdir()
    with pytest.raises(ResetError, match="did not come back"):
        reset_controller("hci0", sys_root=tmp_path, timeout=0.0, sleep=lambda _s: None)


class SwitchablePlan(Plan):
    """Passive mode is broken in one of the two ways seen on a Raspberry Pi 3."""

    def __init__(self, passive: str) -> None:
        super().__init__()
        self.mode = "passive"
        self.passive = passive  # "error" or "silent"
        self.fallbacks: list[str] = []

    def factory(self) -> FakeScanner:
        plan = self

        class Scanner(FakeScanner):
            async def start(self) -> None:
                plan.starts += 1
                if plan.mode == "passive" and plan.passive == "error":
                    raise BleakDBusError("x", ["passive scanning on Linux requires BlueZ"])
                plan.running = True

        return Scanner(self)

    def fall_back(self, reason: str) -> bool:
        if self.mode != "passive":
            return False
        self.fallbacks.append(reason)
        self.mode = "active"
        return True


async def test_unsupported_passive_mode_falls_back_without_a_reset(tmp_path: Path) -> None:
    plan = SwitchablePlan("error")
    sup = ScanSupervisor(plan.factory, state_dir=tmp_path, timings=TIMINGS, fallback=plan.fall_back)
    await sup.start(0.0)
    assert state(sup) is ScanState.RUNNING
    assert plan.mode == "active"
    assert "passive scanning" in plan.fallbacks[0]
    assert not (tmp_path / RESET_MARKER).exists()


async def test_silent_passive_mode_falls_back_after_the_first_window(tmp_path: Path) -> None:
    plan, events = SwitchablePlan("silent"), Events()
    sup = ScanSupervisor(
        plan.factory,
        state_dir=tmp_path,
        timings=TIMINGS,
        listener=lambda kind, data: events.append((kind, data)),
        fallback=plan.fall_back,
    )
    await sup.start(0.0)
    await sup.check(100.0)  # within the first-advertisement window (120 s)
    assert plan.mode == "passive"
    await sup.check(130.0)
    assert plan.fallbacks == ["nothing was received since the start"]
    assert plan.mode == "active"
    assert state(sup) is ScanState.RUNNING
    sup.advertisement_seen(131.0)
    assert events == []  # no outage events, no reset


async def test_fallback_is_not_used_once_something_was_received(tmp_path: Path) -> None:
    plan = SwitchablePlan("silent")
    sup = ScanSupervisor(plan.factory, state_dir=tmp_path, timings=TIMINGS, fallback=plan.fall_back)
    await sup.start(0.0)
    sup.advertisement_seen(1.0)  # passive worked
    await sup.check(400.0)  # later silence is a normal outage
    assert plan.fallbacks == []
    assert state(sup) is ScanState.RECOVERING
