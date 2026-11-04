from pathlib import Path

from mi_homekit_bridge.system import SystemMonitor


def _sys(tmp_path: Path, *, alarm: str | None = "0", temp: str | None = "48312") -> Path:
    root = tmp_path / "sys"
    (root / "class" / "hwmon" / "hwmon0").mkdir(parents=True)
    (root / "class" / "hwmon" / "hwmon0" / "name").write_text("cpu_thermal\n")
    if alarm is not None:
        volt = root / "class" / "hwmon" / "hwmon1"
        volt.mkdir()
        (volt / "name").write_text("rpi_volt\n")
        (volt / "in0_lcrit_alarm").write_text(alarm + "\n")
    if temp is not None:
        zone = root / "class" / "thermal" / "thermal_zone0"
        zone.mkdir(parents=True)
        (zone / "temp").write_text(temp + "\n")
    return root


def _alarm(root: Path, value: str) -> None:
    (root / "class" / "hwmon" / "hwmon1" / "in0_lcrit_alarm").write_text(value)


def test_reports_undervoltage_once_per_cooldown(tmp_path: Path) -> None:
    root = _sys(tmp_path)
    events: list[tuple[str, dict[str, object]]] = []
    now = [1000.0]
    monitor = SystemMonitor(
        sys_root=root, events=lambda kind, **data: events.append((kind, data)), clock=lambda: now[0]
    )
    monitor.poll()
    assert monitor.health().undervoltage is False
    for value, step in (("1", 5), ("0", 5), ("1", 5), ("0", 700), ("1", 5)):
        now[0] += step
        _alarm(root, value)
        monitor.poll()
    health = monitor.health()
    assert health.undervoltage is True
    assert health.undervoltage_count == 3
    assert health.last_undervoltage == 1720
    assert health.cpu_temperature == 48.3
    assert events == [("undervoltage", {"count": 1}), ("undervoltage", {"count": 3})]


def test_not_a_raspberry_pi(tmp_path: Path) -> None:
    monitor = SystemMonitor(sys_root=_sys(tmp_path, alarm=None, temp=None))
    monitor.poll()
    assert not monitor.available
    health = monitor.health()
    assert (health.undervoltage, health.cpu_temperature) == (None, None)
    assert health.to_json()["undervoltage_count"] == 0
