"""Local measurement history in SQLite.

One process (the bridge) owns the database file in its state directory. Readings
are stored as samples, typically every five minutes, and aggregated on the fly:
a year of data for a handful of sensors is only a few hundred thousand rows.

Time handling: timestamps are stored as UTC epoch seconds. Daily buckets, hour of
day and calendar dates are computed in the *server's local time zone* (SQLite's
``localtime`` modifier), so a day in the dashboard is a day on your wall clock,
including daylight saving time changes.

All methods are blocking; call them via ``asyncio.to_thread`` from async code.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

SCHEMA_VERSION = 2

_EVENTS_SCHEMA = """
CREATE TABLE events (
    id        INTEGER PRIMARY KEY,
    ts        INTEGER NOT NULL,
    kind      TEXT    NOT NULL,
    sensor_id TEXT,
    data      TEXT    NOT NULL DEFAULT '{}'
) STRICT;

CREATE INDEX events_ts ON events (ts);
"""

_SCHEMA = (
    """
CREATE TABLE sensors (
    id   TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('ble', 'weather')),
    target_temperature REAL
) STRICT;

CREATE TABLE readings (
    sensor_id   TEXT    NOT NULL REFERENCES sensors (id),
    ts          INTEGER NOT NULL,
    temperature REAL,
    humidity    REAL,
    battery     INTEGER,
    PRIMARY KEY (sensor_id, ts)
) STRICT, WITHOUT ROWID;
"""
    + _EVENTS_SCHEMA
)

# Each entry upgrades the schema from version ``index + 1`` to ``index + 2``.
_MIGRATIONS = ("ALTER TABLE sensors ADD COLUMN target_temperature REAL;" + _EVENTS_SCHEMA,)

SensorKind = Literal["ble", "weather"]


@dataclass(frozen=True, slots=True)
class SensorInfo:
    id: str
    name: str
    kind: SensorKind
    target_temperature: float | None = None


@dataclass(frozen=True, slots=True)
class Sample:
    sensor_id: str
    ts: int
    temperature: float | None = None
    humidity: float | None = None
    battery: int | None = None


@dataclass(frozen=True, slots=True)
class Bucket:
    """Aggregated values of one time bucket."""

    ts: int
    """Start of the bucket (UTC epoch seconds)."""
    temperature_min: float | None
    temperature_avg: float | None
    temperature_max: float | None
    humidity_min: float | None
    humidity_avg: float | None
    humidity_max: float | None


@dataclass(frozen=True, slots=True)
class HourlyProfilePoint:
    hour: int
    """Hour of day in local time, 0-23."""
    temperature_avg: float | None
    humidity_avg: float | None
    samples: int


@dataclass(frozen=True, slots=True)
class HeatmapCell:
    day: str
    """Local calendar date, ``YYYY-MM-DD``."""
    hour: int
    temperature_avg: float | None
    humidity_avg: float | None


@dataclass(frozen=True, slots=True)
class Event:
    """Something worth remembering, e.g. a sensor that stopped reporting.

    ``kind`` is a stable identifier (``sensor_lost``, ``bluetooth_reset``, ...) and
    ``data`` holds its parameters, so the dashboard can phrase it in any language.
    """

    ts: int
    kind: str
    sensor_id: str | None = None
    data: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class HumidityShare:
    """How often the humidity was above a threshold."""

    share: float | None
    """Fraction of samples above the threshold, 0-1; ``None`` without samples."""
    hours: int
    """Number of distinct hours with samples."""


DAY: Literal["day"] = "day"
EVENT_RETENTION_SECONDS = 2 * 365 * 86400


class HistoryStore:
    """Thread-safe access to the history database."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA busy_timeout = 5000")
        self._migrate()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _migrate(self) -> None:
        with self._lock:
            (version,) = self._conn.execute("PRAGMA user_version").fetchone()
            if version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"{self.path} has schema version {version}, this version of "
                    f"mi-homekit-bridge only knows {SCHEMA_VERSION}. Please upgrade."
                )
            if version == 0:
                self._conn.executescript(
                    "BEGIN;" + _SCHEMA + f"PRAGMA user_version = {SCHEMA_VERSION}; COMMIT;"
                )
                return
            for target, script in enumerate(_MIGRATIONS[version - 1 :], start=version + 1):
                self._conn.executescript(
                    "BEGIN;" + script + f"PRAGMA user_version = {target}; COMMIT;"
                )

    # -- writing ---------------------------------------------------------------

    def upsert_sensors(self, sensors: Iterable[SensorInfo]) -> None:
        """Register sensors; names and targets follow the current configuration."""
        with self._lock:
            self._conn.executemany(
                "INSERT INTO sensors (id, name, kind, target_temperature) VALUES (?, ?, ?, ?) "
                "ON CONFLICT (id) DO UPDATE SET name = excluded.name, kind = excluded.kind, "
                "target_temperature = excluded.target_temperature",
                [(s.id, s.name, s.kind, s.target_temperature) for s in sensors],
            )

    def add_samples(self, samples: Iterable[Sample]) -> int:
        """Store samples. A second sample for the same sensor and second is ignored."""
        rows = [(s.sensor_id, s.ts, s.temperature, s.humidity, s.battery) for s in samples]
        with self._lock:
            before = self._conn.total_changes
            self._conn.execute("BEGIN")
            self._conn.executemany(
                "INSERT INTO readings (sensor_id, ts, temperature, humidity, battery) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT (sensor_id, ts) DO NOTHING",
                rows,
            )
            self._conn.execute("COMMIT")
            return self._conn.total_changes - before

    def add_event(self, event: Event) -> None:
        """Store an event and forget events older than two years."""
        with self._lock:
            self._conn.execute("BEGIN")
            self._conn.execute(
                "INSERT INTO events (ts, kind, sensor_id, data) VALUES (?, ?, ?, ?)",
                (event.ts, event.kind, event.sensor_id, json.dumps(dict(event.data))),
            )
            self._conn.execute(
                "DELETE FROM events WHERE ts < ?", (event.ts - EVENT_RETENTION_SECONDS,)
            )
            self._conn.execute("COMMIT")

    # -- reading ---------------------------------------------------------------

    def events(self, limit: int = 50) -> list[Event]:
        """The most recent events, newest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT ts, kind, sensor_id, data FROM events ORDER BY ts DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [Event(r[0], r[1], r[2], json.loads(r[3])) for r in rows]

    def humidity_share(
        self, sensor_id: str, start: int, end: int, threshold: float
    ) -> HumidityShare:
        """Share of samples in ``[start, end)`` with a humidity above ``threshold``."""
        with self._lock:
            share, hours = self._conn.execute(
                "SELECT avg(humidity > ?), count(DISTINCT ts / 3600) FROM readings "
                "WHERE sensor_id = ? AND ts >= ? AND ts < ? AND humidity IS NOT NULL",
                (threshold, sensor_id, start, end),
            ).fetchone()
        return HumidityShare(share=share, hours=hours)

    def sensors(self) -> list[SensorInfo]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, name, kind, target_temperature FROM sensors ORDER BY kind, name"
            ).fetchall()
        return [SensorInfo(*row) for row in rows]

    def latest(self, sensor_id: str) -> Sample | None:
        """The most recent sample, with the last known battery level filled in."""
        with self._lock:
            row = self._conn.execute(
                "SELECT ts, temperature, humidity, "
                "  (SELECT battery FROM readings b WHERE b.sensor_id = r.sensor_id "
                "   AND b.battery IS NOT NULL ORDER BY b.ts DESC LIMIT 1) "
                "FROM readings r WHERE sensor_id = ? ORDER BY ts DESC LIMIT 1",
                (sensor_id,),
            ).fetchone()
        if row is None:
            return None
        return Sample(sensor_id, row[0], row[1], row[2], row[3])

    def first_timestamp(self) -> int | None:
        with self._lock:
            (ts,) = self._conn.execute("SELECT min(ts) FROM readings").fetchone()
        return int(ts) if ts is not None else None

    def series(
        self, sensor_id: str, start: int, end: int, bucket: int | Literal["day"]
    ) -> list[Bucket]:
        """Min/avg/max per bucket. ``bucket`` is a size in seconds or ``"day"`` (local)."""
        if isinstance(bucket, str):
            key = "strftime('%Y-%m-%d', ts, 'unixepoch', 'localtime')"
            start_of = f"CAST(strftime('%s', {key}, 'utc') AS INTEGER)"
        else:
            if bucket <= 0:
                raise ValueError("bucket size must be positive")
            key = f"(ts / {int(bucket)})"
            start_of = f"{key} * {int(bucket)}"
        query = f"""
            SELECT {start_of} AS bucket_start,
                   min(temperature), avg(temperature), max(temperature),
                   min(humidity), avg(humidity), max(humidity)
            FROM readings
            WHERE sensor_id = ? AND ts >= ? AND ts < ?
            GROUP BY {key}
            ORDER BY bucket_start
        """  # noqa: S608 - only integers and fixed SQL fragments are interpolated
        with self._lock:
            rows = self._conn.execute(query, (sensor_id, start, end)).fetchall()
        return [Bucket(*row) for row in rows]

    def hourly_profile(self, sensor_id: str, start: int, end: int) -> list[HourlyProfilePoint]:
        """Average per hour of day (local time) over ``[start, end)``."""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT CAST(strftime('%H', ts, 'unixepoch', 'localtime') AS INTEGER) AS hour,
                       avg(temperature), avg(humidity), count(*)
                FROM readings
                WHERE sensor_id = ? AND ts >= ? AND ts < ?
                GROUP BY hour ORDER BY hour
                """,
                (sensor_id, start, end),
            ).fetchall()
        return [HourlyProfilePoint(*row) for row in rows]

    def heatmap(self, sensor_id: str, start: int, end: int) -> list[HeatmapCell]:
        """Average per local date and hour over ``[start, end)``."""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT strftime('%Y-%m-%d', ts, 'unixepoch', 'localtime') AS day,
                       CAST(strftime('%H', ts, 'unixepoch', 'localtime') AS INTEGER) AS hour,
                       avg(temperature), avg(humidity)
                FROM readings
                WHERE sensor_id = ? AND ts >= ? AND ts < ?
                GROUP BY day, hour ORDER BY day, hour
                """,
                (sensor_id, start, end),
            ).fetchall()
        return [HeatmapCell(*row) for row in rows]

    def export_rows(self) -> Iterator[tuple[str, int, float | None, float | None, int | None]]:
        """All samples as ``(sensor name, ts, temperature, humidity, battery)``, oldest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT s.name, r.ts, r.temperature, r.humidity, r.battery "
                "FROM readings r JOIN sensors s ON s.id = r.sensor_id "
                "ORDER BY r.ts, s.name"
            ).fetchall()
        yield from rows
