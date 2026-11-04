"""Building physics for the dashboard and HomeKit: humidity, mould risk, airing.

All functions are pure. Temperatures are in °C, relative humidity in percent.

Relative humidity alone says little about how much water is in the air: 70 % at
5 °C outdoors is less than half the water of 60 % at 22 °C indoors. *Absolute*
humidity (g/m³) makes indoor and outdoor air comparable and shows whether airing
dries a room.

Mould grows where a wall is cold, not in the middle of the room. The relative
humidity at the coldest spots (corners, window reveals, wall-to-roof junctions) is
estimated with the temperature factor fRsi from DIN 4108-2::

    θsi = θe + fRsi · (θi - θe)

``fRsi`` = 0.7 is the minimum the standard requires at thermal bridges, well
insulated new buildings reach about 0.8 or more, uninsulated old ones less.
DIN 4108-2 regards 80 % relative humidity at the surface as the limit for mould.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

# Magnus formula over water (Sonntag 1990), valid for -45 °C to 60 °C.
_A, _B, _C = 6.112, 17.62, 243.12
WATER_VAPOUR = 216.7
"""g·K/J: 100 / specific gas constant of water vapour (461.5 J/(kg·K)) · 1000."""

DEFAULT_SURFACE_FACTOR = 0.7
MOULD_LIMIT = 80.0
"""Relative humidity at the wall above which mould can grow (DIN 4108-2)."""
CAUTION_LIMIT = 70.0
ROOM_MOULD_LIMIT = 70.0
ROOM_CAUTION_LIMIT = 60.0
"""Without outdoor data only the room humidity is known: stricter limits for it."""

DRYING_MIN = 1.0
"""Airing must take out at least this much water (g/m³) to be worth it."""

HEATING_BASE = 20.0
HEATING_LIMIT = 15.0
"""Heating degree days G20/15 (VDI 3807): days with a mean below 15 °C count
20 °C minus their mean."""

Level = Literal["good", "warning", "critical"]
Ventilation = Literal["recommended", "not_needed", "avoid"]


def saturation_pressure(temperature: float) -> float:
    """Saturation vapour pressure in hPa."""
    return _A * math.exp(_B * temperature / (_C + temperature))


def vapour_pressure(temperature: float, humidity: float) -> float:
    """Partial pressure of water vapour in hPa."""
    return humidity / 100 * saturation_pressure(temperature)


def water_content(temperature: float, humidity: float) -> float:
    """Absolute humidity: water in the air in g/m³."""
    return WATER_VAPOUR * vapour_pressure(temperature, humidity) / (273.15 + temperature)


def absolute_humidity(temperature: float | None, humidity: float | None) -> float | None:
    """:func:`water_content`, or ``None`` if a value is missing (usable in SQL)."""
    if temperature is None or humidity is None:
        return None
    return water_content(temperature, humidity)


def dew_point(temperature: float | None, humidity: float | None) -> float | None:
    """Dew point in °C."""
    if temperature is None or humidity is None or humidity <= 0:
        return None
    gamma = math.log(humidity / 100) + _B * temperature / (_C + temperature)
    return _C * gamma / (_B - gamma)


def surface_temperature(indoor: float, outdoor: float, factor: float) -> float:
    """Estimated temperature of the coldest inner wall surface.

    When it is warmer outside than inside, the walls are not colder than the room.
    """
    return min(indoor, outdoor + factor * (indoor - outdoor))


def surface_humidity(
    temperature: float | None,
    humidity: float | None,
    outdoor: float | None,
    factor: float = DEFAULT_SURFACE_FACTOR,
) -> float | None:
    """Relative humidity (%) at the coldest wall surface, at most 100."""
    if temperature is None or humidity is None or outdoor is None:
        return None
    surface = surface_temperature(temperature, outdoor, factor)
    return min(100.0, vapour_pressure(temperature, humidity) / saturation_pressure(surface) * 100)


def mould_level(surface: float) -> Level:
    """How close the coldest wall is to mould growth."""
    if surface >= MOULD_LIMIT:
        return "critical"
    if surface >= CAUTION_LIMIT:
        return "warning"
    return "good"


def room_level(humidity: float) -> Level:
    """Fallback without outdoor data: judge by the room humidity alone."""
    if humidity >= ROOM_MOULD_LIMIT:
        return "critical"
    if humidity >= ROOM_CAUTION_LIMIT:
        return "warning"
    return "good"


def airing_minutes(outdoor: float) -> int:
    """How long to air with wide open windows (rule of thumb of German consumer
    advice centres): the colder it is, the faster the air is exchanged."""
    if outdoor < 5:
        return 5
    if outdoor < 10:
        return 10
    if outdoor < 15:
        return 15
    if outdoor < 20:
        return 20
    return 25


def heating_degrees(daily_mean: float) -> float:
    """Heating degrees of one day (G20/15)."""
    return HEATING_BASE - daily_mean if daily_mean < HEATING_LIMIT else 0.0


@dataclass(frozen=True, slots=True)
class AirAssessment:
    """Humidity situation of one room right now."""

    absolute_humidity: float | None
    outdoor_absolute_humidity: float | None
    surface_humidity: float | None
    """``None`` without outdoor temperature."""
    level: Level | None
    """Mould risk, from the wall surface or (without outdoor data) the room."""
    basis: Literal["surface", "room"] | None
    ventilation: Ventilation | None
    minutes: int | None
    """Suggested airing time when airing is recommended."""


def assess(
    temperature: float | None,
    humidity: float | None,
    outdoor_temperature: float | None,
    outdoor_humidity: float | None,
    factor: float = DEFAULT_SURFACE_FACTOR,
) -> AirAssessment:
    """Mould risk and whether airing helps.

    Airing is recommended when the room is (getting) too humid and the outdoor
    air holds clearly less water. If it is damp and the outdoor air is not drier
    (a humid summer day), airing would not help: ``avoid``.
    """
    inside = absolute_humidity(temperature, humidity)
    outside = absolute_humidity(outdoor_temperature, outdoor_humidity)
    surface = surface_humidity(temperature, humidity, outdoor_temperature, factor)
    level: Level | None = None
    basis: Literal["surface", "room"] | None = None
    if surface is not None:
        level, basis = mould_level(surface), "surface"
    elif humidity is not None:
        level, basis = room_level(humidity), "room"

    ventilation: Ventilation | None = None
    minutes = None
    if (
        level is not None
        and inside is not None
        and outside is not None
        and outdoor_temperature is not None
    ):
        if level == "good":
            ventilation = "not_needed"
        elif inside - outside >= DRYING_MIN:
            ventilation = "recommended"
            minutes = airing_minutes(outdoor_temperature)
        else:
            ventilation = "avoid"
    return AirAssessment(inside, outside, surface, level, basis, ventilation, minutes)


def air_quality(surface: float | None) -> int:
    """HomeKit ``AirQuality`` (1 excellent … 5 poor, 0 unknown) from the wall humidity."""
    if surface is None:
        return 0
    for limit, value in ((60, 1), (CAUTION_LIMIT, 2), (MOULD_LIMIT, 3), (90, 4)):
        if surface < limit:
            return value
    return 5
