import sqlite3
import time
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from mi_homekit_bridge.history import DAY, Event, HistoryStore, Sample, SensorInfo

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
        ("Living Room", 100, 21.0, 50.0, 90, None, None, None),
        ("Outdoor", 200, 5.0, 80.0, None, None, None, None),
    ]


def test_version_1_database_is_migrated(tmp_path: Path) -> None:
    path = tmp_path / "v1.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE sensors (id TEXT PRIMARY KEY, name TEXT NOT NULL,
                kind TEXT NOT NULL CHECK (kind IN ('ble', 'weather'))) STRICT;
            CREATE TABLE readings (sensor_id TEXT NOT NULL REFERENCES sensors (id),
                ts INTEGER NOT NULL, temperature REAL, humidity REAL, battery INTEGER,
                PRIMARY KEY (sensor_id, ts)) STRICT, WITHOUT ROWID;
            INSERT INTO sensors VALUES ('A', 'Living Room', 'ble');
            INSERT INTO readings VALUES ('A', 100, 21.0, 50.0, NULL);
            PRAGMA user_version = 1;
            """
        )
    store = HistoryStore(path)
    assert store.sensors() == [SensorInfo("A", "Living Room", "ble", None)]
    assert store.latest("A") == Sample("A", 100, 21.0, 50.0, None)
    store.upsert_sensors([SensorInfo("A", "Living Room", "ble", 20.5)])
    assert store.sensors()[0].target_temperature == 20.5
    store.add_event(Event(200, "started", data={"version": "x"}))
    assert store.events() == [Event(200, "started", None, {"version": "x"})]
    store.close()
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone() == (3,)


def test_events_newest_first_and_pruned(store: HistoryStore) -> None:
    year = 365 * 86400
    store.add_event(Event(1000, "sensor_lost", "A", {"minutes": 60}))
    store.add_event(Event(2000, "sensor_back", "A", {"minutes": 70}))
    assert [e.kind for e in store.events()] == ["sensor_back", "sensor_lost"]
    assert [e.kind for e in store.events(limit=1)] == ["sensor_back"]
    store.add_event(Event(1000 + 2 * year + 1, "started"))  # the first one expires
    assert [e.kind for e in store.events()] == ["started", "sensor_back"]


def test_raw_rows_battery_and_weather_columns(store: HistoryStore) -> None:
    store.add_samples(
        [
            Sample("A", 100, 21.0, 50.0, 90),
            Sample("A", 400, 21.5, 51.0),
            Sample("W", 300, 5.0, 80.0, radiation=120.0, wind=14.0, precipitation=0.4),
        ]
    )
    assert store.rows("A", 0, 1000) == [
        (100, 21.0, 50.0, None, None, None),
        (400, 21.5, 51.0, None, None, None),
    ]
    assert store.last_battery("A") == (100, 90)
    assert store.last_battery("W") is None
    assert store.latest_full("W") == Sample("W", 300, 5.0, 80.0, None, 120.0, 14.0, 0.4)
    assert store.recorded_timestamps("ble", 0, 1000) == [100, 400]
    [bucket] = store.series("W", 0, 1000, 3600)
    assert (bucket.radiation_avg, bucket.wind_avg, bucket.precipitation_avg) == (120.0, 14.0, 0.4)
    [indoor] = store.series("A", 0, 1000, 3600)
    assert indoor.absolute_avg == pytest.approx((9.15 + 9.56) / 2, abs=0.05)
    assert store.hourly_profile("A", 0, 1000)[0].absolute_avg == indoor.absolute_avg


def test_events_between(store: HistoryStore) -> None:
    for ts in (100, 200, 300):
        store.add_event(Event(ts, "started"))
    assert [e.ts for e in store.events_between(150, 300)] == [200]


def test_version_2_database_gets_weather_columns(tmp_path: Path) -> None:
    path = tmp_path / "v2.db"
    HistoryStore(path).close()
    with sqlite3.connect(path) as conn:  # turn it back into a version 2 file
        conn.executescript(
            """
            ALTER TABLE sensors DROP COLUMN surface_factor;
            ALTER TABLE readings DROP COLUMN radiation;
            ALTER TABLE readings DROP COLUMN wind;
            ALTER TABLE readings DROP COLUMN precipitation;
            PRAGMA user_version = 2;
            """
        )
    store = HistoryStore(path)
    store.upsert_sensors([SensorInfo("A", "Living Room", "ble", 20.0, 0.8)])
    assert store.sensors()[0].surface_factor == 0.8
    store.close()
