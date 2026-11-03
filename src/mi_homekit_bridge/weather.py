"""Outdoor temperature and humidity from a weather service.

Providers implement :class:`WeatherProvider`. The only provider so far is
`Open-Meteo <https://open-meteo.com>`_: free for non-commercial use, no API key,
worldwide coverage (for Germany it is based on the DWD ICON models).
Weather data by Open-Meteo.com, licensed under CC BY 4.0.

Postal codes are resolved to coordinates with OpenStreetMap's Nominatim, once per
start (its usage policy allows occasional lookups by identified applications).
Open-Meteo's own geocoder only knows a few postal codes per town.
Geocoding data (c) OpenStreetMap contributors, ODbL.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import aiohttp

from . import __version__
from .config import WeatherConfig

_LOGGER = logging.getLogger(__name__)

USER_AGENT = f"mi-homekit-bridge/{__version__} (+https://github.com/huulanka/mi-homekit-bridge)"
_TIMEOUT = aiohttp.ClientTimeout(total=20)


class WeatherError(RuntimeError):
    """The weather service could not be reached or returned unusable data."""


@dataclass(frozen=True, slots=True)
class Location:
    latitude: float
    longitude: float
    label: str


@dataclass(frozen=True, slots=True)
class Observation:
    ts: int
    """Observation time, UTC epoch seconds."""
    temperature: float | None
    humidity: float | None


class WeatherProvider(Protocol):
    async def current(self) -> Observation: ...


def parse_nominatim(data: Any, postal_code: str, country: str) -> Location:
    """Location from a Nominatim structured search response (``format=jsonv2``)."""
    if not isinstance(data, list) or not data:
        raise WeatherError(f"postal code {postal_code} not found in {country}")
    best = data[0]
    try:
        latitude, longitude = float(best["lat"]), float(best["lon"])
    except (KeyError, TypeError, ValueError) as err:
        raise WeatherError("unexpected geocoding response") from err
    place = ", ".join(str(best.get("display_name", "")).split(", ")[1:2])
    return Location(latitude, longitude, f"{postal_code} {place}".strip())


def parse_current(data: dict[str, Any]) -> Observation:
    """Parse the ``current`` block of an Open-Meteo forecast response (timezone=GMT)."""
    current = data.get("current")
    if not isinstance(current, dict) or "time" not in current:
        raise WeatherError("response has no current weather")
    observed = datetime.fromisoformat(str(current["time"])).replace(tzinfo=UTC)
    temperature = current.get("temperature_2m")
    humidity = current.get("relative_humidity_2m")
    return Observation(
        ts=int(observed.timestamp()),
        temperature=float(temperature) if temperature is not None else None,
        humidity=float(humidity) if humidity is not None else None,
    )


class OpenMeteo:
    """Current conditions from Open-Meteo."""

    GEOCODING_URL = "https://nominatim.openstreetmap.org/search"
    FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

    def __init__(self, session: aiohttp.ClientSession, config: WeatherConfig) -> None:
        self._session = session
        self._config = config
        self._location: Location | None = None
        if config.latitude is not None and config.longitude is not None:
            self._location = Location(
                config.latitude, config.longitude, f"{config.latitude}, {config.longitude}"
            )

    async def _get_json(self, url: str, params: dict[str, str]) -> Any:
        try:
            async with self._session.get(
                url, params=params, timeout=_TIMEOUT, headers={"User-Agent": USER_AGENT}
            ) as response:
                response.raise_for_status()
                data = await response.json()
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise WeatherError(f"{url}: {err}") from err
        return data

    async def location(self) -> Location:
        """Resolve the configured location once (postal code lookups are cached)."""
        if self._location is None:
            postal_code, country = self._config.postal_code, self._config.country
            if postal_code is None or country is None:  # prevented by config validation
                raise WeatherError("no weather location configured")
            data = await self._get_json(
                self.GEOCODING_URL,
                {
                    "postalcode": postal_code,
                    "countrycodes": country.lower(),
                    "format": "jsonv2",
                    "limit": "1",
                },
            )
            self._location = parse_nominatim(data, postal_code, country)
            _LOGGER.info(
                "Weather location: %s (%.3f, %.3f)",
                self._location.label,
                self._location.latitude,
                self._location.longitude,
            )
        return self._location

    async def current(self) -> Observation:
        location = await self.location()
        data = await self._get_json(
            self.FORECAST_URL,
            {
                "latitude": f"{location.latitude:.4f}",
                "longitude": f"{location.longitude:.4f}",
                "current": "temperature_2m,relative_humidity_2m",
                "timezone": "GMT",
            },
        )
        if not isinstance(data, dict):
            raise WeatherError(f"{self.FORECAST_URL}: unexpected response")
        return parse_current(data)


def create_provider(session: aiohttp.ClientSession, config: WeatherConfig) -> WeatherProvider:
    if config.provider == "open-meteo":
        return OpenMeteo(session, config)
    raise ValueError(f"unknown weather provider: {config.provider}")  # pragma: no cover
