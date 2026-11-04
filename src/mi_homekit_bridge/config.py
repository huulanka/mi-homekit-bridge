"""Load and validate the configuration.

Non-secret settings (names, MAC addresses, port, features) live in a TOML file.
Secrets (bindkeys) are only ever read from environment variables, so the config
file can be shared or versioned without leaking anything.
"""

from __future__ import annotations

import os
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

DEFAULT_BRIDGE_NAME = "Mi Thermometers"
DEFAULT_PORT = 51826
DEFAULT_STALE_AFTER_MINUTES = 60

_MAC_RE = re.compile(r"^[0-9A-F]{12}$")
_BINDKEY_RE = re.compile(r"^[0-9a-f]{32}$")

DEFAULT_HISTORY_INTERVAL_MINUTES = 5
DEFAULT_WEATHER_INTERVAL_MINUTES = 15
DEFAULT_WEATHER_NAME = "Outdoor"
WEATHER_PROVIDERS = ("open-meteo",)

DEFAULT_WEB_HOST = "127.0.0.1"
DEFAULT_WEB_PORT = 8080

DEFAULT_ADAPTER = "hci0"
SCANNING_MODES = ("active", "passive")
ScanningMode = Literal["active", "passive"]

_TOP_LEVEL_KEYS = {"bridge", "sensors", "bluetooth", "history", "weather", "web"}
_BRIDGE_KEYS = {"name", "port", "address", "stale_after_minutes"}
_SENSOR_KEYS = {"name", "mac", "target_temperature"}
_BLUETOOTH_KEYS = {"adapter", "scanning_mode"}
_HISTORY_KEYS = {"enabled", "interval_minutes"}
_WEB_KEYS = {"enabled", "host", "port"}
_WEATHER_KEYS = {
    "enabled",
    "provider",
    "name",
    "postal_code",
    "country",
    "latitude",
    "longitude",
    "interval_minutes",
}

BINDKEY_ENV_PREFIX = "MI_HOMEKIT_BRIDGE_BINDKEY_"


class ConfigError(ValueError):
    """Raised when the configuration file is missing or invalid."""


@dataclass(frozen=True, slots=True)
class SensorConfig:
    """One BLE thermometer."""

    name: str
    mac: str
    """Upper-case, colon separated, e.g. ``A4:C1:38:00:00:01``."""
    bindkey: bytes | None = None
    """16-byte key for encrypted advertisements, ``None`` for plaintext ones.

    Read from the environment variable named by :func:`bindkey_env_var`.
    """
    target_temperature: float | None = None
    """Desired room temperature in °C, shown in the dashboard."""


@dataclass(frozen=True, slots=True)
class BluetoothConfig:
    """The local Bluetooth adapter."""

    adapter: str = DEFAULT_ADAPTER
    """BlueZ adapter name, e.g. ``hci0``."""
    scanning_mode: ScanningMode = "active"
    """``passive`` only listens and never sends scan requests. It needs BlueZ
    advertisement monitor support (BlueZ 5.56+, Linux 5.10+)."""


@dataclass(frozen=True, slots=True)
class HistoryConfig:
    """Recording of readings into a local SQLite database."""

    enabled: bool = True
    interval_minutes: int = DEFAULT_HISTORY_INTERVAL_MINUTES


@dataclass(frozen=True, slots=True)
class WeatherConfig:
    """Outdoor temperature and humidity from a weather service.

    The location is given either as ``postal_code`` + ``country`` or as
    ``latitude`` + ``longitude``.
    """

    enabled: bool = False
    provider: str = WEATHER_PROVIDERS[0]
    name: str = DEFAULT_WEATHER_NAME
    postal_code: str | None = None
    country: str | None = None
    """ISO 3166-1 alpha-2 country code, upper-case, e.g. ``DE``."""
    latitude: float | None = None
    longitude: float | None = None
    interval_minutes: int = DEFAULT_WEATHER_INTERVAL_MINUTES


@dataclass(frozen=True, slots=True)
class WebConfig:
    """The built-in dashboard. Listens on localhost by default; publish it with a
    reverse proxy such as ``tailscale serve``."""

    enabled: bool = False
    host: str = DEFAULT_WEB_HOST
    port: int = DEFAULT_WEB_PORT


@dataclass(frozen=True, slots=True)
class BridgeConfig:
    """The whole bridge."""

    sensors: tuple[SensorConfig, ...]
    name: str = DEFAULT_BRIDGE_NAME
    port: int = DEFAULT_PORT
    address: str | None = None
    stale_after_minutes: int = DEFAULT_STALE_AFTER_MINUTES
    bluetooth: BluetoothConfig = BluetoothConfig()
    history: HistoryConfig = HistoryConfig()
    weather: WeatherConfig = WeatherConfig()
    web: WebConfig = WebConfig()


def normalize_mac(value: str) -> str:
    """Return ``value`` as upper-case, colon separated MAC address."""
    compact = re.sub(r"[:\-.]", "", value.strip()).upper()
    if not _MAC_RE.match(compact):
        raise ConfigError(f"invalid MAC address: {value!r}")
    return ":".join(compact[i : i + 2] for i in range(0, 12, 2))


def bindkey_env_var(mac: str) -> str:
    """Name of the environment variable holding the bindkey for ``mac``."""
    return BINDKEY_ENV_PREFIX + normalize_mac(mac).replace(":", "")


def parse_bindkey(value: str) -> bytes | None:
    """Parse a 32 hex character bindkey. An empty string means "no key"."""
    cleaned = value.strip().lower()
    if not cleaned:
        return None
    if not _BINDKEY_RE.match(cleaned):
        raise ConfigError("bindkey must be exactly 32 hex characters")
    return bytes.fromhex(cleaned)


def _check_keys(table: dict[str, Any], allowed: set[str], where: str) -> None:
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise ConfigError(f"unknown option(s) in {where}: {', '.join(unknown)}")


def _require_str(table: dict[str, Any], key: str, where: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{where}: '{key}' must be a non-empty string")
    return value.strip()


def _table(data: dict[str, Any], key: str, allowed: set[str]) -> dict[str, Any]:
    table = data.get(key, {})
    if not isinstance(table, dict):
        raise ConfigError(f"[{key}] must be a table")
    _check_keys(table, allowed, f"[{key}]")
    return table


def _bool(table: dict[str, Any], key: str, default: bool, where: str) -> bool:
    value = table.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"{where}: '{key}' must be true or false")
    return value


def _int(table: dict[str, Any], key: str, default: int, low: int, high: int, where: str) -> int:
    value = table.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
        raise ConfigError(f"{where}: '{key}' must be an integer between {low} and {high}")
    return value


def _float(table: dict[str, Any], key: str, low: float, high: float, where: str) -> float | None:
    value = table.get(key)
    if value is None:
        return None
    if not isinstance(value, int | float) or isinstance(value, bool) or not low <= value <= high:
        raise ConfigError(f"{where}: '{key}' must be a number between {low} and {high}")
    return float(value)


def _opt_str(table: dict[str, Any], key: str, where: str) -> str | None:
    value = table.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{where}: '{key}' must be a non-empty string")
    return value.strip()


def _parse_bluetooth(data: dict[str, Any]) -> BluetoothConfig:
    where = "[bluetooth]"
    table = _table(data, "bluetooth", _BLUETOOTH_KEYS)
    adapter = _opt_str(table, "adapter", where) or DEFAULT_ADAPTER
    if not re.fullmatch(r"hci[0-9]{1,2}", adapter):
        raise ConfigError(f"{where}: 'adapter' must be a BlueZ adapter name such as \"hci0\"")
    mode = _opt_str(table, "scanning_mode", where) or "active"
    if mode == "active":
        scanning_mode: ScanningMode = "active"
    elif mode == "passive":
        scanning_mode = "passive"
    else:
        raise ConfigError(f"{where}: 'scanning_mode' must be one of: {', '.join(SCANNING_MODES)}")
    return BluetoothConfig(adapter=adapter, scanning_mode=scanning_mode)


def _parse_history(data: dict[str, Any]) -> HistoryConfig:
    table = _table(data, "history", _HISTORY_KEYS)
    return HistoryConfig(
        enabled=_bool(table, "enabled", True, "[history]"),
        interval_minutes=_int(
            table, "interval_minutes", DEFAULT_HISTORY_INTERVAL_MINUTES, 1, 60, "[history]"
        ),
    )


def _parse_weather(data: dict[str, Any]) -> WeatherConfig:
    where = "[weather]"
    table = _table(data, "weather", _WEATHER_KEYS)
    enabled = _bool(table, "enabled", False, where)
    provider = _opt_str(table, "provider", where) or WEATHER_PROVIDERS[0]
    if provider not in WEATHER_PROVIDERS:
        raise ConfigError(f"{where}: 'provider' must be one of: {', '.join(WEATHER_PROVIDERS)}")
    postal_code = table.get("postal_code")
    if isinstance(postal_code, int) and not isinstance(postal_code, bool):
        raise ConfigError(f'{where}: write the postal code as a string, e.g. "{postal_code}"')
    postal_code = _opt_str(table, "postal_code", where)
    country = _opt_str(table, "country", where)
    if country is not None:
        if not re.fullmatch(r"[A-Za-z]{2}", country):
            raise ConfigError(f"{where}: 'country' must be a two-letter code such as \"DE\"")
        country = country.upper()
    latitude = _float(table, "latitude", -90, 90, where)
    longitude = _float(table, "longitude", -180, 180, where)

    by_postal_code = postal_code is not None or country is not None
    by_coordinates = latitude is not None or longitude is not None
    if by_postal_code and by_coordinates:
        raise ConfigError(f"{where}: use either postal_code/country or latitude/longitude")
    if by_postal_code and (postal_code is None or country is None):
        raise ConfigError(f"{where}: 'postal_code' and 'country' must be set together")
    if by_coordinates and (latitude is None or longitude is None):
        raise ConfigError(f"{where}: 'latitude' and 'longitude' must be set together")
    if enabled and not (by_postal_code or by_coordinates):
        raise ConfigError(
            f"{where}: set a location (postal_code + country, or latitude + longitude)"
        )

    return WeatherConfig(
        enabled=enabled,
        provider=provider,
        name=_opt_str(table, "name", where) or DEFAULT_WEATHER_NAME,
        postal_code=postal_code,
        country=country,
        latitude=latitude,
        longitude=longitude,
        interval_minutes=_int(
            table, "interval_minutes", DEFAULT_WEATHER_INTERVAL_MINUTES, 5, 180, where
        ),
    )


def _parse_web(data: dict[str, Any]) -> WebConfig:
    where = "[web]"
    table = _table(data, "web", _WEB_KEYS)
    return WebConfig(
        enabled=_bool(table, "enabled", False, where),
        host=_opt_str(table, "host", where) or DEFAULT_WEB_HOST,
        port=_int(table, "port", DEFAULT_WEB_PORT, 1, 65535, where),
    )


def _parse_sensor(raw: Any, index: int, environ: Mapping[str, str]) -> SensorConfig:
    where = f"sensors[{index}]"
    if not isinstance(raw, dict):
        raise ConfigError(f"{where} must be a table")
    if "bindkey" in raw:
        raise ConfigError(
            f"{where}: bindkeys are secrets and must not be stored in the config file. "
            f"Set the environment variable {BINDKEY_ENV_PREFIX}<MAC> instead (see README)."
        )
    _check_keys(raw, _SENSOR_KEYS, where)
    try:
        mac = normalize_mac(_require_str(raw, "mac", where))
        name = _require_str(raw, "name", where)
        target = _float(raw, "target_temperature", 5, 30, where)
        env_var = bindkey_env_var(mac)
        try:
            bindkey = parse_bindkey(environ.get(env_var, ""))
        except ConfigError as err:
            raise ConfigError(f"${env_var}: {err}") from err
        return SensorConfig(name=name, mac=mac, bindkey=bindkey, target_temperature=target)
    except ConfigError as err:
        if str(err).startswith(where):
            raise
        raise ConfigError(f"{where}: {err}") from err


def parse_config(data: dict[str, Any], environ: Mapping[str, str] | None = None) -> BridgeConfig:
    """Build a :class:`BridgeConfig` from parsed TOML data and the environment."""
    env = os.environ if environ is None else environ
    _check_keys(data, _TOP_LEVEL_KEYS, "top level")

    bridge = data.get("bridge", {})
    if not isinstance(bridge, dict):
        raise ConfigError("[bridge] must be a table")
    _check_keys(bridge, _BRIDGE_KEYS, "[bridge]")

    name = bridge.get("name", DEFAULT_BRIDGE_NAME)
    if not isinstance(name, str) or not name.strip():
        raise ConfigError("[bridge]: 'name' must be a non-empty string")

    port = bridge.get("port", DEFAULT_PORT)
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise ConfigError("[bridge]: 'port' must be an integer between 1 and 65535")

    address = bridge.get("address")
    if address is not None and (not isinstance(address, str) or not address.strip()):
        raise ConfigError("[bridge]: 'address' must be a non-empty string")

    stale = bridge.get("stale_after_minutes", DEFAULT_STALE_AFTER_MINUTES)
    if not isinstance(stale, int) or isinstance(stale, bool) or stale < 1:
        raise ConfigError("[bridge]: 'stale_after_minutes' must be a positive integer")

    raw_sensors = data.get("sensors", [])
    if not isinstance(raw_sensors, list) or not raw_sensors:
        raise ConfigError("at least one [[sensors]] entry is required")
    sensors = tuple(_parse_sensor(raw, i, env) for i, raw in enumerate(raw_sensors))

    for attr in ("name", "mac"):
        values = [getattr(s, attr) for s in sensors]
        duplicates = sorted({v for v in values if values.count(v) > 1})
        if duplicates:
            raise ConfigError(f"duplicate sensor {attr}(s): {', '.join(duplicates)}")

    bluetooth = _parse_bluetooth(data)
    history = _parse_history(data)
    weather = _parse_weather(data)
    web = _parse_web(data)
    if weather.enabled and not history.enabled:
        raise ConfigError("[weather] needs [history] enabled: outdoor values are only recorded")
    if web.enabled and not history.enabled:
        raise ConfigError("[web] needs [history] enabled: the dashboard shows recorded data")
    if web.enabled and web.port == port:
        raise ConfigError("[web]: 'port' must differ from the HomeKit port in [bridge]")
    if weather.enabled and weather.name in {s.name for s in sensors}:
        raise ConfigError(f"[weather]: name {weather.name!r} is already used by a sensor")

    return BridgeConfig(
        sensors=sensors,
        name=name.strip(),
        port=port,
        address=address.strip() if address else None,
        stale_after_minutes=stale,
        bluetooth=bluetooth,
        history=history,
        weather=weather,
        web=web,
    )


def load_config(path: Path, environ: Mapping[str, str] | None = None) -> BridgeConfig:
    """Read and validate the configuration file at ``path``."""
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except FileNotFoundError as err:
        raise ConfigError(f"config file not found: {path}") from err
    except tomllib.TOMLDecodeError as err:
        raise ConfigError(f"{path}: {err}") from err
    return parse_config(data, environ)
