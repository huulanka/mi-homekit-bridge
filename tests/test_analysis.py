from datetime import date, datetime

import pytest

from mi_homekit_bridge.analysis import (
    OutdoorLookup,
    detect_airings,
    find_gaps,
    local_midnights,
    mould_share,
    outdoor_days,
    room_days,
)
from mi_homekit_bridge.history import Event, Row

# 2026-11-04, living room, 5-minute samples as recorded (07:45 and 08:00 missing).
MORNING = [
    ("07:30", 23.7, 57.0),
    ("07:35", 23.7, 56.0),
    ("07:40", 23.9, 56.0),
    ("07:55", 24.1, 57.0),
    ("08:05", 20.3, 47.0),
    ("08:10", 20.9, 47.0),
    ("08:15", 21.5, 50.0),
    ("08:20", 22.0, 50.0),
    ("08:25", 22.0, 50.0),
    ("08:30", 22.5, 50.0),
    ("08:35", 22.5, 51.0),
    ("08:40", 22.9, 51.0),
    ("08:45", 22.9, 51.0),
    ("08:50", 22.9, 51.0),
    ("09:00", 23.5, 51.0),
    ("09:05", 23.5, 52.0),
]


def _ts(clock: str, day: str = "2026-11-04") -> int:
    return int(datetime.fromisoformat(f"{day}T{clock}").timestamp())


def _rows(points: list[tuple[str, float, float]]) -> list[Row]:
    return [(_ts(clock), t, h, None, None, None) for clock, t, h in points]


def test_detects_the_airing_of_this_morning() -> None:
    [airing] = detect_airings("L", _rows(MORNING))
    assert (airing.start, airing.lowest) == (_ts("07:55"), _ts("08:05"))
    assert airing.drop == pytest.approx(3.8)
    assert airing.drying == pytest.approx(4.2, abs=0.1)
    # Back within 20 % of the drop (23.3 °C) at 09:00.
    assert airing.recovered == _ts("09:00")
    assert airing.recovery_minutes == 65


def test_slow_cooling_or_a_drier_sensor_is_no_airing() -> None:
    cooling = [(f"0{h}:00", 22.0 - h * 0.3, 50.0) for h in range(10)]
    assert detect_airings("L", _rows(cooling)) == []
    # Carried into a colder room: the water content stays about the same.
    carried = [("10:00", 22.0, 50.0), ("10:05", 20.5, 55.0), ("10:10", 20.4, 55.0)]
    assert detect_airings("L", _rows(carried)) == []
    # A drop across an outage is not compared.
    gap = [("10:00", 22.0, 50.0), ("10:30", 19.0, 40.0)]
    assert detect_airings("L", _rows(gap)) == []


def test_airing_without_recovery() -> None:
    points = [("20:00", 22.0, 55.0), ("20:05", 19.0, 45.0), ("20:10", 19.1, 45.0)]
    [airing] = detect_airings("L", _rows(points))
    assert airing.recovered is None
    assert airing.recovery_minutes is None


def test_two_airings_in_one_day() -> None:
    points = [
        *MORNING,
        ("18:00", 23.0, 55.0),
        ("18:05", 21.5, 48.0),
        ("18:10", 21.6, 48.0),
        ("18:40", 22.8, 52.0),
    ]
    starts = [a.start for a in detect_airings("L", _rows(points))]
    assert starts == [_ts("07:55"), _ts("18:00")]


def test_find_gaps_with_causes() -> None:
    stamps = [0, 300, 600, 3600, 3900, 4200]
    events = [Event(1000, "scan_silent"), Event(1100, "bluetooth_reset"), Event(4000, "started")]
    gaps = find_gaps(stamps, min_gap=900, end=8000, events=events)
    assert [(g.start, g.end, g.cause) for g in gaps] == [
        (600, 3600, "bluetooth"),
        (4200, 8000, "unknown"),
    ]
    restart = find_gaps([0, 2000], min_gap=900, end=2100, events=[Event(500, "stopped")])
    assert [g.cause for g in restart] == ["restart"]
    assert find_gaps([0, 300], min_gap=900, end=600) == []


def test_mould_share_prefers_the_wall_estimate() -> None:
    outdoor: list[Row] = [(_ts("07:00"), 5.6, 71.0, None, None, None)]
    rows: list[Row] = [
        (_ts("07:30"), 22.2, 61.0, None, None, None),  # wall ~83 % with fRsi 0.7
        (_ts("07:35"), 22.2, 50.0, None, None, None),
        (_ts("10:00"), 22.2, 61.0, None, None, None),  # outdoor too old: room 61 % < 70 %
    ]
    share = mould_share(rows, OutdoorLookup(outdoor, None))
    assert share.share == pytest.approx(1 / 3)
    assert (share.hours, share.basis) == (2, "surface")
    better_walls = mould_share(rows, OutdoorLookup(outdoor, 0.8))
    assert better_walls.share == 0
    assert mould_share([], OutdoorLookup([], None)).share is None


def test_local_midnights_follow_daylight_saving() -> None:
    days = local_midnights(date(2026, 10, 24), date(2026, 10, 26))
    assert [d for d, _ in days] == ["2026-10-24", "2026-10-25", "2026-10-26"]
    assert days[0][1] == _ts("00:00", "2026-10-24")


def test_room_days() -> None:
    days = local_midnights(date(2026, 11, 3), date(2026, 11, 4))
    rows = [(_ts("23:00", "2026-11-03"), 21.0, 50.0, None, None, None), *_rows(MORNING)]
    outdoor: list[Row] = [(_ts("07:00"), 5.6, 71.0, None, None, None)]
    yesterday, today = room_days("L", rows, outdoor, days, target=21.0, surface_factor=0.8)
    assert (yesterday.samples, yesterday.on_target, yesterday.airings) == (1, 1.0, 0)
    assert yesterday.mould_basis == "room"
    assert today.samples == len(MORNING)
    assert today.airings == 1
    assert today.recovery_minutes == 65
    # Target 21 ± 0.5 °C: 20.3 °C too cold, 20.9 and 21.5 °C on target, the rest too warm.
    assert today.cold == pytest.approx(1 / 16)
    assert today.on_target == pytest.approx(2 / 16)
    assert today.warm == pytest.approx(13 / 16)
    assert today.mould == 0
    assert today.temperature_min == 20.3

    no_target = room_days("L", rows, [], days, target=None, surface_factor=None)
    assert no_target[1].on_target is None


def test_outdoor_days() -> None:
    days = local_midnights(date(2026, 11, 4), date(2026, 11, 4))
    rows: list[Row] = [
        (_ts("06:00"), 4.0, 80.0, 0.0, 10.0, 0.0),
        (_ts("12:00"), 8.0, 60.0, 400.0, 20.0, 1.0),
    ]
    [day] = outdoor_days(rows, days, now=_ts("12:00"))
    assert day.temperature_avg == 6.0
    assert day.heating_degrees == 14.0
    assert (day.radiation_avg, day.wind_avg) == (200.0, 15.0)
    assert day.precipitation == pytest.approx(0.5 * 12)  # mean rate over the 12 hours so far
