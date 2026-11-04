"""Synthetic but plausible climate data for the ``demo`` command and screenshots.

Nothing here is real data: an outdoor climate with seasons, a daily cycle,
weather fronts, sun, wind and showers, a heated living room that is aired after
breakfast and a bedroom that is aired every morning, plus one Bluetooth outage.
The generator is deterministic for a given seed.
"""

from __future__ import annotations

import math
import random
import time
from datetime import datetime
from pathlib import Path

from . import __version__
from .history import Event, HistoryStore, Sample, SensorInfo
from .status import BridgeStatus, SensorStatus
from .system import SystemHealth

LIVING_ROOM = SensorInfo("A4:C1:38:00:00:01", "Living Room", "ble", 21.0, 0.8)
BEDROOM = SensorInfo("A4:C1:38:00:00:02", "Bedroom", "ble", 18.0, 0.7)
OUTDOOR = SensorInfo("weather", "Outdoor", "weather")
DEMO_SENSORS = (LIVING_ROOM, BEDROOM, OUTDOOR)

_STEP = 300
_YEAR = 365.25 * 86400


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _outdoor(ts: int, front: float) -> tuple[float, float]:
    local = datetime.fromtimestamp(ts)
    season = -math.cos(2 * math.pi * (local.timetuple().tm_yday - 18) / 365.25)  # -1 Jan, +1 Jul
    hour = local.hour + local.minute / 60
    daily = math.cos(2 * math.pi * (hour - 15) / 24)  # warmest around 15:00
    temperature = 10 + 10 * season + (3 + 2.5 * (season + 1)) * daily + front
    humidity = _clamp(78 - 14 * daily - 6 * season - 2.5 * front, 35, 100)
    return temperature, humidity


def _sky(ts: int, front: float, rng: random.Random) -> tuple[float, float, float]:
    """Solar radiation (W/m²), wind (km/h) and precipitation rate (mm/h)."""
    local = datetime.fromtimestamp(ts)
    season = -math.cos(2 * math.pi * (local.timetuple().tm_yday - 18) / 365.25)
    hour = local.hour + local.minute / 60
    half_day = 4.2 + 3.8 * (season + 1) / 2  # 8.4 h of daylight in winter, 16 h in summer
    sun = math.cos(math.pi * (hour - 12.8) / (2 * half_day))
    clouds = _clamp(0.55 - 0.12 * front, 0.15, 0.95)
    radiation = max(0.0, sun) * (300 + 550 * (season + 1) / 2) * (1 - 0.75 * clouds)
    wind = max(0.0, 9 + 2.2 * abs(front) + rng.gauss(0, 2.5))
    rain = rng.expovariate(1.2) if front < -1.5 and rng.random() < 0.35 else 0.0
    return round(radiation), round(wind, 1), round(rain, 1)


def _heating(ts: int) -> float:
    """1 in winter, 0 in summer."""
    local = datetime.fromtimestamp(ts)
    season = -math.cos(2 * math.pi * (local.timetuple().tm_yday - 18) / 365.25)
    return _clamp(0.5 - season, 0, 1)


def _living_room(
    ts: int, outdoor: float, out_humidity: float, rng: random.Random
) -> tuple[float, float]:
    local = datetime.fromtimestamp(ts)
    hour = local.hour + local.minute / 60
    heating = _heating(ts)
    setback = 1.6 if hour >= 23 or hour < 6 else 0.0
    sun = 0.9 * math.exp(-(((hour - 16) / 2.5) ** 2))
    heated = 21.6 - setback + sun
    free_running = 22.5 + 0.35 * (outdoor - 18) + sun
    temperature = heating * heated + (1 - heating) * free_running + rng.gauss(0, 0.08)
    airing = math.exp(-(((hour - 8.4) / 0.18) ** 2)) * heating  # short, after breakfast
    temperature -= 3.2 * airing
    cooking = 7 * math.exp(-(((hour - 18.8) / 0.6) ** 2))
    humidity = 0.35 * out_humidity + 22 - 10 * heating + cooking - 9 * airing + rng.gauss(0, 0.6)
    return temperature, _clamp(humidity, 25, 80)


def _bedroom(
    ts: int, outdoor: float, out_humidity: float, rng: random.Random
) -> tuple[float, float]:
    local = datetime.fromtimestamp(ts)
    hour = local.hour + local.minute / 60
    heating = _heating(ts)
    airing = 2.6 * math.exp(-(((hour - 7.3) / 0.35) ** 2))  # window open in the morning
    sleeping = 1.0 if hour >= 23 or hour < 7 else 0.0
    heated = 19.0 + 0.4 * sleeping - airing * (0.6 + heating)
    free_running = 21.5 + 0.3 * (outdoor - 18) - 0.5 * airing
    temperature = heating * heated + (1 - heating) * free_running + rng.gauss(0, 0.08)
    humidity = 0.3 * out_humidity + 30 - 9 * heating + 6 * sleeping - 2 * airing + rng.gauss(0, 0.6)
    return temperature, _clamp(humidity, 25, 85)


def generate(store: HistoryStore, *, days: int = 400, end: int | None = None, seed: int = 7) -> int:
    """Fill ``store`` with ``days`` of demo data ending at ``end``. Returns the sample count."""
    end = end if end is not None else int(time.time())
    end -= end % _STEP
    start = end - days * 86400
    rng = random.Random(seed)  # noqa: S311 - demo data, not security relevant
    store.upsert_sensors(DEMO_SENSORS)

    samples: list[Sample] = []
    front, front_target = 0.0, 0.0
    outage = range(end - _OUTAGE_START, end - _OUTAGE_END)
    for ts in range(start, end + 1, _STEP):
        if ts % (3 * 86400) == 0:
            front_target = rng.gauss(0, 3.5)  # a new weather situation every few days
        front += (front_target - front) * 0.004
        out_t, out_h = _outdoor(ts, front)
        age = (ts - start) / _YEAR
        battery = round(_clamp(100 - 28 * age, 5, 100))
        living_t, living_h = _living_room(ts, out_t, out_h, rng)
        bed_t, bed_h = _bedroom(ts, out_t, out_h, rng)
        if ts % 900 == 0:
            radiation, wind, rain = _sky(ts, front, rng)
            samples.append(
                Sample(OUTDOOR.id, ts, round(out_t, 1), round(out_h), None, radiation, wind, rain)
            )
        if ts in outage:
            continue
        # The battery is only broadcast now and then.
        level = battery if ts % 3600 == 0 else None
        samples.append(Sample(LIVING_ROOM.id, ts, round(living_t, 1), round(living_h), level))
        bed_battery = None if level is None else level - 4
        samples.append(Sample(BEDROOM.id, ts, round(bed_t, 1), round(bed_h), bed_battery))
    store.add_samples(samples)
    for event in _demo_events(end):
        store.add_event(event)
    return len(samples)


_OUTAGE_START = 6 * 86400 + 6000
_OUTAGE_END = 6 * 86400 + 1800
"""Bluetooth outage six days ago: 70 minutes without indoor readings."""


def _demo_events(end: int) -> list[Event]:
    day = 86400
    outage = end - _OUTAGE_START
    return [
        Event(end - 9 * day, "started", data={"version": "0.4.1"}),
        Event(outage + 300, "scan_silent", data={"minutes": 5, "error": ""}),
        Event(outage + 360, "bluetooth_reset", data={"error": "InProgress"}),
        Event(outage + 375, "started", data={"version": "0.4.1"}),
        Event(outage + 400, "scan_failed", data={"error": "InProgress"}),
        Event(outage + 2200, "bluetooth_failed", data={"error": "InProgress"}),
        Event(outage + 4150, "scan_recovered", data={"seconds": 3750}),
        Event(end - 4 * day, "undervoltage", data={"count": 1}),
        Event(end - 3 * day, "stopped"),
        Event(end - 3 * day + 9, "started", data={"version": __version__}),
        Event(end - 3 * day + 140, "stopped"),
        Event(end - 3 * day + 148, "started", data={"version": __version__}),
        Event(end - 2 * day, "sensor_lost", BEDROOM.id, {"minutes": 60}),
        Event(end - 2 * day + 1800, "sensor_back", BEDROOM.id, {"minutes": 90}),
    ]


def demo_status(now: float | None = None) -> BridgeStatus:
    """A healthy bridge, for the ``demo`` command."""
    ts = round(now if now is not None else time.time())
    return BridgeStatus(
        version=__version__,
        started_at=ts - 9 * 86400,
        bluetooth_state="running",
        bluetooth_since=ts - 6 * 86400,
        bluetooth_error=None,
        scanning_mode="passive",
        last_advertisement=ts - 2,
        homekit_paired=True,
        homekit_controllers=2,
        sensors=(
            SensorStatus(LIVING_ROOM.id, LIVING_ROOM.name, True, False, ts - 4, -64),
            SensorStatus(BEDROOM.id, BEDROOM.name, True, False, ts - 9, -78),
        ),
        system=SystemHealth(
            cpu_temperature=51.2,
            undervoltage=False,
            undervoltage_count=0,
            last_undervoltage=None,
        ),
    )


def create_demo_store(path: Path, days: int = 400) -> HistoryStore:
    store = HistoryStore(path)
    generate(store, days=days)
    return store
