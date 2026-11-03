import sqlite3
import time
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from mi_homekit_bridge.history import DAY, HistoryStore, Sample, SensorInfo

BERLIN = ZoneInfo("Europe/Berlin")


@pytest.fixture
def berlin_time(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """SQLite's 'localtime' follows the process time zone."""
    monkeypatch.setenv("TZ", "Europe/Berlin")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


@pytest.fixture
def store(tmp_path: Path) -> Iterator[HistoryStore]:
    db = HistoryStore(tmp_path / "history.db")
    db.upsert_sensors(
        [SensorInfo("A", "Living Room", "ble"), SensorInfo("W", "Outdoor", "weather")]
    )
    yield db
    db.close()


def _ts(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> int:
    return int(datetime(year, month, day, hour, minute, tzinfo=BERLIN).timestamp())


def test_schema_is_created_once(tmp_path: Path) -> None:
    HistoryStore(tmp_path / "h.db").close()
    store = HistoryStore(tmp_path / "h.db")  # reopening must not fail
    assert store.sensors() == []
    store.close()


def test_newer_schema_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "h.db"
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA user_version = 99")
    with pytest.raises(RuntimeError, match="schema version 99"):
        HistoryStore(path)


def test_sensor_names_follow_config(store: HistoryStore) -> None:
    store.upsert_sensors([SensorInfo("A", "Wohnzimmer", "ble")])
    assert [s.name for s in store.sensors()] == ["Wohnzimmer", "Outdoor"]


def test_duplicate_samples_are_ignored(store: HistoryStore) -> None:
    assert store.add_samples([Sample("A", 100, 21.0, 50.0, 90)]) == 1
    assert store.add_samples([Sample("A", 100, 22.0, 51.0, 90), Sample("A", 400, 22.0)]) == 1


def test_unknown_sensor_is_rejected(store: HistoryStore) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        store.add_samples([Sample("nope", 1, 20.0)])


def test_latest_fills_in_last_known_battery(store: HistoryStore) -> None:
    assert store.latest("A") is None
    store.add_samples([Sample("A", 100, 21.0, 50.0, 87), Sample("A", 400, 21.5, 49.0, None)])
    assert store.latest("A") == Sample("A", 400, 21.5, 49.0, 87)


def test_series_with_fixed_buckets(store: HistoryStore) -> None:
    store.add_samples(
        [Sample("A", 3600 + i * 300, 20.0 + i, 40.0 + i) for i in range(24)]  # 2 hours
    )
    buckets = store.series("A", 0, 10_000_000, 3600)
    assert [b.ts for b in buckets] == [3600, 7200]
    first = buckets[0]
    assert (first.temperature_min, first.temperature_max) == (20.0, 31.0)
    assert first.temperature_avg == pytest.approx(25.5)
    assert first.humidity_avg == pytest.approx(45.5)


def test_series_respects_range_and_sensor(store: HistoryStore) -> None:
    store.add_samples([Sample("A", 100, 1.0), Sample("A", 200, 2.0), Sample("W", 150, 9.0)])
    buckets = store.series("A", 150, 250, 300)
    assert [b.temperature_avg for b in buckets] == [2.0]


def test_series_daily_buckets_use_local_days(store: HistoryStore, berlin_time: None) -> None:
    # 23:30 and 00:30 local time belong to different days, even across the DST change.
    store.add_samples(
        [
            Sample("A", _ts(2026, 10, 24, 23, 30), 10.0),
            Sample("A", _ts(2026, 10, 25, 0, 30), 20.0),  # day of the switch to CET
            Sample("A", _ts(2026, 10, 25, 23, 30), 30.0),
        ]
    )
    buckets = store.series("A", 0, _ts(2027, 1, 1), DAY)
    assert [b.ts for b in buckets] == [_ts(2026, 10, 24), _ts(2026, 10, 25)]
    assert [b.temperature_avg for b in buckets] == [10.0, 25.0]


def test_hourly_profile(store: HistoryStore, berlin_time: None) -> None:
    store.add_samples(
        [
            Sample("A", _ts(2026, 11, 1, 7, 0), 18.0, 60.0),
            Sample("A", _ts(2026, 11, 2, 7, 30), 20.0, 50.0),
            Sample("A", _ts(2026, 11, 2, 15, 0), 23.0, 45.0),
        ]
    )
    profile = store.hourly_profile("A", 0, _ts(2027, 1, 1))
    assert [(p.hour, p.temperature_avg, p.samples) for p in profile] == [
        (7, 19.0, 2),
        (15, 23.0, 1),
    ]


def test_heatmap(store: HistoryStore, berlin_time: None) -> None:
    store.add_samples(
        [
            Sample("A", _ts(2026, 11, 1, 7, 0), 18.0),
            Sample("A", _ts(2026, 11, 1, 7, 30), 20.0),
            Sample("A", _ts(2026, 11, 2, 8, 0), 21.0),
        ]
    )
    cells = store.heatmap("A", 0, _ts(2027, 1, 1))
    assert [(c.day, c.hour, c.temperature_avg) for c in cells] == [
        ("2026-11-01", 7, 19.0),
        ("2026-11-02", 8, 21.0),
    ]


def test_export_rows_and_first_timestamp(store: HistoryStore) -> None:
    assert store.first_timestamp() is None
    store.add_samples([Sample("W", 200, 5.0, 80.0), Sample("A", 100, 21.0, 50.0, 90)])
    assert store.first_timestamp() == 100
    assert list(store.export_rows()) == [
        ("Living Room", 100, 21.0, 50.0, 90),
        ("Outdoor", 200, 5.0, 80.0, None),
    ]
