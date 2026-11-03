from __future__ import annotations

from types import TracebackType
from typing import Any

import aiohttp
import pytest

from mi_homekit_bridge.config import WeatherConfig
from mi_homekit_bridge.weather import (
    OpenMeteo,
    WeatherError,
    parse_current,
    parse_geocoding,
)

GEOCODING = {
    "results": [
        {
            "name": "Lehel",
            "postcodes": ["80331", "80538"],
            "latitude": 48.14,
            "longitude": 11.59,
            "country_code": "DE",
        },
        {
            "name": "München",
            "postcodes": ["80331"],
            "latitude": 48.137,
            "longitude": 11.575,
            "country_code": "DE",
        },
        {
            "name": "Somewhere",
            "postcodes": ["80331"],
            "latitude": 1.0,
            "longitude": 2.0,
            "country_code": "XX",
        },
    ]
}
CURRENT = {
    "current": {"time": "2026-11-03T21:15", "temperature_2m": 3.9, "relative_humidity_2m": 81}
}


def test_parse_geocoding_prefers_exact_postcode_in_country() -> None:
    location = parse_geocoding(GEOCODING, "80331", "DE")
    assert (location.latitude, location.longitude) == (48.14, 11.59)
    assert location.label == "80331 Lehel"


def test_parse_geocoding_falls_back_to_first_result() -> None:
    location = parse_geocoding(GEOCODING, "99999", "DE")
    assert location.label == "99999 Lehel"


def test_parse_geocoding_not_found() -> None:
    with pytest.raises(WeatherError, match="not found"):
        parse_geocoding({"results": []}, "80331", "DE")
    with pytest.raises(WeatherError):
        parse_geocoding({}, "80331", "AT")


def test_parse_current() -> None:
    observation = parse_current(CURRENT)
    assert observation.ts == 1793740500  # 2026-11-03 21:15 UTC
    assert (observation.temperature, observation.humidity) == (3.9, 81.0)


def test_parse_current_rejects_garbage() -> None:
    with pytest.raises(WeatherError):
        parse_current({"error": True})


class FakeResponse:
    def __init__(self, data: Any, status: int = 200) -> None:
        self._data = data
        self.status = status

    async def __aenter__(self) -> FakeResponse:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise aiohttp.ClientError(f"HTTP {self.status}")

    async def json(self) -> Any:
        return self._data


class FakeSession:
    def __init__(self, responses: dict[str, FakeResponse]) -> None:
        self._responses = responses
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append((url, kwargs["params"]))
        assert "mi-homekit-bridge" in kwargs["headers"]["User-Agent"]
        return self._responses[url]


async def test_open_meteo_resolves_postal_code_once() -> None:
    session = FakeSession(
        {
            OpenMeteo.GEOCODING_URL: FakeResponse(GEOCODING),
            OpenMeteo.FORECAST_URL: FakeResponse(CURRENT),
        }
    )
    config = WeatherConfig(enabled=True, postal_code="80331", country="DE")
    provider = OpenMeteo(session, config)  # type: ignore[arg-type]

    first = await provider.current()
    await provider.current()

    assert first.temperature == 3.9
    urls = [url for url, _ in session.calls]
    assert urls.count(OpenMeteo.GEOCODING_URL) == 1
    assert urls.count(OpenMeteo.FORECAST_URL) == 2
    forecast_params = session.calls[1][1]
    assert forecast_params["latitude"] == "48.1400"
    assert forecast_params["timezone"] == "GMT"


async def test_open_meteo_with_coordinates_skips_geocoding() -> None:
    session = FakeSession({OpenMeteo.FORECAST_URL: FakeResponse(CURRENT)})
    config = WeatherConfig(enabled=True, latitude=52.52, longitude=13.405)
    await OpenMeteo(session, config).current()  # type: ignore[arg-type]
    assert [url for url, _ in session.calls] == [OpenMeteo.FORECAST_URL]


async def test_open_meteo_http_errors_become_weather_errors() -> None:
    session = FakeSession({OpenMeteo.FORECAST_URL: FakeResponse({}, status=503)})
    config = WeatherConfig(enabled=True, latitude=52.52, longitude=13.405)
    with pytest.raises(WeatherError, match="HTTP 503"):
        await OpenMeteo(session, config).current()  # type: ignore[arg-type]
