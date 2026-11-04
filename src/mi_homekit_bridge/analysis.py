"""Analyses over recorded readings: airing, outages and daily statistics.

Everything here is pure and works on rows from :meth:`HistoryStore.rows`
(``(ts, temperature, humidity, radiation, wind, precipitation)``, oldest first).
"""

from __future__ import annotations

import itertools
import statistics
from bisect import bisect_right
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Literal

from .climate import (
    DEFAULT_SURFACE_FACTOR,
    MOULD_LIMIT,
    ROOM_MOULD_LIMIT,
    WATER_VAPOUR,
    heating_degrees,
    saturation_pressure,
    surface_humidity,
    surface_temperature,
    water_content,
)
from .history import Event, Row

# -- airing -------------------------------------------------------------------

AIRING_WINDOW = 15 * 60
"""The drop has to happen within this time …"""
AIRING_MIN_DROP = 1.0
"""… by at least this many kelvin …"""
AIRING_MIN_DRYING = 0.8
"""… and the air must lose at least this much water (g/m³). A heating that turns
off cannot cool a room this fast, and a sensor carried into another room keeps
the water content."""
AIRING_MAX_STEP = 20 * 60
"""Samples further apart than this are not compared (outage in between)."""
AIRING_LOWEST_WITHIN = 60 * 60
RECOVERY_WITHIN = 6 * 3600
RECOVERY_TOLERANCE = 0.5
RECOVERY_SHARE = 0.2
"""Recovered once the room is back within 0.5 K or 20 % of the drop, whichever is
larger: after turning a thermostat down it never gets back to the old value."""


@dataclass(frozen=True, slots=True)
class Airing:
    """A window was opened: the temperature and the water content dropped fast."""

    sensor_id: str
    start: int
    lowest: int
    temperature_before: float
    temperature_lowest: float
    drying: float
    """Water taken out of the air, g/m³."""
    recovered: int | None
    """When the room was warm again, ``None`` if not (yet)."""

    @property
    def drop(self) -> float:
        return self.temperature_before - self.temperature_lowest

    @property
    def recovery_minutes(self) -> int | None:
        return None if self.recovered is None else round((self.recovered - self.start) / 60)


def detect_airings(sensor_id: str, rows: Sequence[Row]) -> list[Airing]:
    """Find airings in the readings of one indoor sensor.

    Only works in the heating season: airing on a warm day does not cool a room.
    """
    points = [
        (ts, t, water_content(t, h)) for ts, t, h, *_ in rows if t is not None and h is not None
    ]
    return _airings(sensor_id, points)


def _airings(sensor_id: str, points: Sequence[tuple[int, float, float]]) -> list[Airing]:
    """:func:`detect_airings` on ``(ts, temperature, water content)`` points."""
    result: list[Airing] = []
    count = len(points)
    i = 0
    while i < count - 1:
        ts_i, t_i, ah_i = points[i]
        found = None
        for j in range(i + 1, count):
            ts_j, t_j, ah_j = points[j]
            if ts_j - ts_i > AIRING_WINDOW or ts_j - points[j - 1][0] > AIRING_MAX_STEP:
                break
            if t_i - t_j >= AIRING_MIN_DROP and ah_i - ah_j >= AIRING_MIN_DRYING:
                found = j
                break
        if found is None:
            i += 1
            continue

        # The start is the last sample that was still about as warm as before.
        warmest = max(points[k][1] for k in range(i, found))
        start = max(k for k in range(i, found) if points[k][1] >= warmest - 0.2)
        low = found
        for k in range(found + 1, count):
            if points[k][0] - points[start][0] > AIRING_LOWEST_WITHIN:
                break
            if points[k][0] - points[k - 1][0] > AIRING_MAX_STEP:
                break
            if points[k][1] < points[low][1]:
                low = k
            elif points[k][1] > points[low][1] + 0.3:
                break

        before, lowest = points[start][1], points[low][1]
        threshold = before - max(RECOVERY_TOLERANCE, RECOVERY_SHARE * (before - lowest))
        recovered = None
        for ts, t, _ in itertools.islice(points, low + 1, None):
            if ts - points[low][0] > RECOVERY_WITHIN:
                break
            if t >= threshold:
                recovered = ts
                break
        result.append(
            Airing(
                sensor_id=sensor_id,
                start=points[start][0],
                lowest=points[low][0],
                temperature_before=before,
                temperature_lowest=lowest,
                drying=round(points[start][2] - points[low][2], 2),
                recovered=recovered,
            )
        )
        i = low + 1
    return result


# -- outages ------------------------------------------------------------------

GapCause = Literal["bluetooth", "restart", "unknown"]

_BLUETOOTH_EVENTS = {"scan_silent", "scan_failed", "bluetooth_reset", "bluetooth_failed"}
_RESTART_EVENTS = {"started", "stopped"}


@dataclass(frozen=True, slots=True)
class Gap:
    """No indoor sensor was recorded between ``start`` and ``end``."""

    start: int
    end: int
    cause: GapCause


def find_gaps(
    timestamps: Sequence[int], *, min_gap: int, end: int, events: Iterable[Event] = ()
) -> list[Gap]:
    """Periods without any recorded indoor reading, longer than ``min_gap``.

    ``timestamps`` are sorted; a silence since the last one until ``end`` counts
    too. The cause is taken from the events in the gap: Bluetooth trouble wins
    over a restart.
    """
    spans = [
        (a, b) for a, b in zip(timestamps, [*timestamps[1:], end], strict=True) if b - a > min_gap
    ]
    if not spans:
        return []
    ordered = sorted(events, key=lambda e: e.ts)
    stamps = [e.ts for e in ordered]
    gaps = []
    for a, b in spans:
        kinds = {e.kind for e in ordered[bisect_right(stamps, a) : bisect_right(stamps, b)]}
        cause: GapCause = (
            "bluetooth"
            if kinds & _BLUETOOTH_EVENTS
            else "restart"
            if kinds & _RESTART_EVENTS
            else "unknown"
        )
        gaps.append(Gap(a, b, cause))
    return gaps


# -- daily statistics ---------------------------------------------------------

TARGET_TOLERANCE = 0.5
"""Within this many kelvin of the target counts as "on target" (as in the dashboard)."""
OUTDOOR_MAX_AGE = 75 * 60
"""Outdoor values are fetched every 15 minutes; older ones are not used."""


@dataclass(slots=True)
class _Acc:
    """Running sums for one day."""

    temperatures: list[float] = field(default_factory=list)
    humidities: list[float] = field(default_factory=list)
    absolutes: list[float] = field(default_factory=list)
    cold: int = 0
    warm: int = 0
    mould: int = 0
    mould_basis_surface: int = 0
    radiation: list[float] = field(default_factory=list)
    wind: list[float] = field(default_factory=list)
    precipitation: list[float] = field(default_factory=list)


class OutdoorLookup:
    """The outdoor temperature at a given time, for the mould estimate."""

    def __init__(self, outdoor: Sequence[Row], surface_factor: float | None) -> None:
        self._ts = [r[0] for r in outdoor if r[1] is not None]
        self._t = [r[1] for r in outdoor if r[1] is not None]
        self.factor = surface_factor if surface_factor is not None else DEFAULT_SURFACE_FACTOR

    def temperature(self, ts: int) -> float | None:
        """The last outdoor temperature before ``ts``, if recent enough."""
        index = bisect_right(self._ts, ts) - 1
        if index < 0 or ts - self._ts[index] > OUTDOOR_MAX_AGE:
            return None
        return self._t[index]

    def mould(self, ts: int, temperature: float, humidity: float) -> tuple[bool, bool]:
        """``(mould risk, judged by the wall surface)`` for one indoor reading."""
        surface = surface_humidity(temperature, humidity, self.temperature(ts), self.factor)
        if surface is None:
            return humidity >= ROOM_MOULD_LIMIT, False
        return surface >= MOULD_LIMIT, True


@dataclass(frozen=True, slots=True)
class MouldShare:
    share: float | None
    hours: int
    """Distinct hours with readings."""
    basis: Literal["surface", "room"]


def mould_share(rows: Sequence[Row], outside: OutdoorLookup) -> MouldShare:
    """Share of readings with mould risk at the coldest wall."""
    flags = [outside.mould(ts, t, h) for ts, t, h, *_ in rows if t is not None and h is not None]
    hours = len({ts // 3600 for ts, t, h, *_ in rows if t is not None and h is not None})
    if not flags:
        return MouldShare(None, 0, "surface")
    by_surface = sum(s for _, s in flags)
    return MouldShare(
        share=sum(r for r, _ in flags) / len(flags),
        hours=hours,
        basis="surface" if by_surface * 2 >= len(flags) else "room",
    )


@dataclass(frozen=True, slots=True)
class RoomDay:
    day: str
    """Local calendar date, ``YYYY-MM-DD``."""
    samples: int
    temperature_avg: float | None
    temperature_min: float | None
    temperature_max: float | None
    humidity_avg: float | None
    absolute_avg: float | None
    cold: float | None
    """Share of samples more than the tolerance below the target (None without target)."""
    on_target: float | None
    warm: float | None
    mould: float | None
    """Share of samples with mould risk at the coldest wall (or, without outdoor
    data, a room humidity above 70 %)."""
    mould_basis: Literal["surface", "room"]
    airings: int
    recovery_minutes: float | None
    """Median time to warm up again after airing."""


@dataclass(frozen=True, slots=True)
class OutdoorDay:
    day: str
    samples: int
    temperature_avg: float | None
    temperature_min: float | None
    temperature_max: float | None
    humidity_avg: float | None
    absolute_avg: float | None
    heating_degrees: float | None
    radiation_avg: float | None
    """Mean global radiation over the recorded part of the day, W/m²."""
    precipitation: float | None
    """Precipitation amount in mm, from the mean rate."""
    wind_avg: float | None


def local_midnights(first: date, last: date) -> list[tuple[str, int]]:
    """``(YYYY-MM-DD, epoch of local midnight)`` for each day from first to last."""
    days = []
    day = first
    while day <= last:
        midnight = datetime(day.year, day.month, day.day)  # local time on purpose
        days.append((day.isoformat(), int(midnight.timestamp())))
        day += timedelta(days=1)
    return days


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _by_day(rows: Sequence[Row], midnights: Sequence[int]) -> list[list[Row]]:
    """Split sorted rows into the days that start at ``midnights``."""
    days: list[list[Row]] = [[] for _ in midnights]
    for row in rows:
        index = bisect_right(midnights, row[0]) - 1
        if index >= 0:
            days[index].append(row)
    return days


def outdoor_days(
    rows: Sequence[Row], days: Sequence[tuple[str, int]], *, now: int
) -> list[OutdoorDay]:
    midnights = [m for _, m in days]
    result = []
    for (day, midnight), day_rows, next_midnight in zip(
        days, _by_day(rows, midnights), [*midnights[1:], midnights[-1] + 86400], strict=True
    ):
        acc = _Acc()
        for _, t, h, radiation, wind, precipitation in day_rows:
            if t is not None:
                acc.temperatures.append(t)
            if h is not None:
                acc.humidities.append(h)
            if t is not None and h is not None:
                acc.absolutes.append(water_content(t, h))
            if radiation is not None:
                acc.radiation.append(radiation)
            if wind is not None:
                acc.wind.append(wind)
            if precipitation is not None:
                acc.precipitation.append(precipitation)
        mean = _mean(acc.temperatures)
        hours = max(0, min(now, next_midnight) - midnight) / 3600
        rate = _mean(acc.precipitation)
        result.append(
            OutdoorDay(
                day=day,
                samples=len(day_rows),
                temperature_avg=mean,
                temperature_min=min(acc.temperatures, default=None),
                temperature_max=max(acc.temperatures, default=None),
                humidity_avg=_mean(acc.humidities),
                absolute_avg=_mean(acc.absolutes),
                heating_degrees=None if mean is None else heating_degrees(mean),
                radiation_avg=_mean(acc.radiation),
                precipitation=None if rate is None else rate * hours,
                wind_avg=_mean(acc.wind),
            )
        )
    return result


def room_days(
    sensor_id: str,
    rows: Sequence[Row],
    outdoor: Sequence[Row],
    days: Sequence[tuple[str, int]],
    *,
    target: float | None,
    surface_factor: float | None,
) -> list[RoomDay]:
    """Daily statistics of one indoor sensor.

    A year of 5-minute samples is a hundred thousand rows: this is one tight loop
    (seconds on a Raspberry Pi 3), with the humidity formulas of
    :mod:`.climate` evaluated once per sample.
    """
    factor = surface_factor if surface_factor is not None else DEFAULT_SURFACE_FACTOR
    out_ts = [r[0] for r in outdoor if r[1] is not None]
    out_t = [r[1] for r in outdoor if r[1] is not None]
    midnights = [m for _, m in days]
    accs = [_Acc() for _ in days]
    counts = [0] * len(days)
    points: list[tuple[int, float, float]] = []
    saturation = saturation_pressure
    low_target = None if target is None else target - TARGET_TOLERANCE
    high_target = None if target is None else target + TARGET_TOLERANCE
    day, next_midnight = -1, midnights[0] if midnights else 0
    j = -1
    for ts, t, h, *_ in rows:
        while ts >= next_midnight:
            day += 1
            next_midnight = midnights[day + 1] if day + 1 < len(midnights) else 2**62
        if day < 0:
            continue
        acc = accs[day]
        counts[day] += 1
        if t is not None:
            acc.temperatures.append(t)
            if low_target is not None and high_target is not None:
                acc.cold += t < low_target
                acc.warm += t > high_target
        if h is None:
            continue
        acc.humidities.append(h)
        if t is None:
            continue
        pressure = h / 100 * saturation(t)
        water = WATER_VAPOUR * pressure / (273.15 + t)
        acc.absolutes.append(water)
        points.append((ts, t, water))
        while j + 1 < len(out_ts) and out_ts[j + 1] <= ts:
            j += 1
        if j >= 0 and ts - out_ts[j] <= OUTDOOR_MAX_AGE:
            surface = surface_temperature(t, out_t[j], factor)
            acc.mould += pressure / saturation(surface) * 100 >= MOULD_LIMIT
            acc.mould_basis_surface += 1
        else:
            acc.mould += h >= ROOM_MOULD_LIMIT

    airings_by_day: list[list[Airing]] = [[] for _ in days]
    for airing in _airings(sensor_id, points):
        index = bisect_right(midnights, airing.start) - 1
        if index >= 0:
            airings_by_day[index].append(airing)

    result = []
    for (name, _), acc, samples, day_airings in zip(
        days, accs, counts, airings_by_day, strict=True
    ):
        measured = len(acc.temperatures)
        with_humidity = len(acc.humidities)
        shares = target is not None and measured > 0
        recoveries = [a.recovery_minutes for a in day_airings if a.recovery_minutes is not None]
        result.append(
            RoomDay(
                day=name,
                samples=samples,
                temperature_avg=_mean(acc.temperatures),
                temperature_min=min(acc.temperatures, default=None),
                temperature_max=max(acc.temperatures, default=None),
                humidity_avg=_mean(acc.humidities),
                absolute_avg=_mean(acc.absolutes),
                cold=acc.cold / measured if shares else None,
                on_target=(measured - acc.cold - acc.warm) / measured if shares else None,
                warm=acc.warm / measured if shares else None,
                mould=acc.mould / with_humidity if with_humidity else None,
                mould_basis="surface" if acc.mould_basis_surface * 2 >= with_humidity else "room",
                airings=len(day_airings),
                recovery_minutes=statistics.median(recoveries) if recoveries else None,
            )
        )
    return result
