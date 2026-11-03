"""Synthetic but plausible climate data for the ``demo`` command and screenshots.

Nothing here is real data: an outdoor climate with seasons, a daily cycle and
weather fronts, a heated living room and a bedroom that is aired every morning.
The generator is deterministic for a given seed.
"""

from __future__ import annotations

import math
import random
import time
from datetime import datetime
from pathlib import Path

from .history import HistoryStore, Sample, SensorInfo

LIVING_ROOM = SensorInfo("A4:C1:38:00:00:01", "Living Room", "ble")
BEDROOM = SensorInfo("A4:C1:38:00:00:02", "Bedroom", "ble")
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
    cooking = 7 * math.exp(-(((hour - 18.8) / 0.6) ** 2))
    humidity = 0.35 * out_humidity + 22 - 10 * heating + cooking + rng.gauss(0, 0.6)
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
    for ts in range(start, end + 1, _STEP):
        if ts % (3 * 86400) == 0:
            front_target = rng.gauss(0, 3.5)  # a new weather situation every few days
        front += (front_target - front) * 0.004
        out_t, out_h = _outdoor(ts, front)
        age = (ts - start) / _YEAR
        battery = round(_clamp(100 - 28 * age, 5, 100))
        living_t, living_h = _living_room(ts, out_t, out_h, rng)
        bed_t, bed_h = _bedroom(ts, out_t, out_h, rng)
        samples.append(Sample(LIVING_ROOM.id, ts, round(living_t, 1), round(living_h), battery))
        samples.append(Sample(BEDROOM.id, ts, round(bed_t, 1), round(bed_h), battery - 4))
        if ts % 900 == 0:
            samples.append(Sample(OUTDOOR.id, ts, round(out_t, 1), round(out_h)))
    store.add_samples(samples)
    return len(samples)


def create_demo_store(path: Path, days: int = 400) -> HistoryStore:
    store = HistoryStore(path)
    generate(store, days=days)
    return store
