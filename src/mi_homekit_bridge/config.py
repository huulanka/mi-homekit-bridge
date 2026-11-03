"""Load and validate the configuration.

Non-secret settings (names, MAC addresses, port) live in a TOML file. Secrets
(bindkeys) are only ever read from environment variables, so the config file can
be shared or versioned without leaking anything.
"""

from __future__ import annotations

import os
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_BRIDGE_NAME = "Mi Thermometers"
DEFAULT_PORT = 51826
DEFAULT_STALE_AFTER_MINUTES = 60

_MAC_RE = re.compile(r"^[0-9A-F]{12}$")
_BINDKEY_RE = re.compile(r"^[0-9a-f]{32}$")

_BRIDGE_KEYS = {"name", "port", "address", "stale_after_minutes"}
_SENSOR_KEYS = {"name", "mac"}

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


@dataclass(frozen=True, slots=True)
class BridgeConfig:
    """The whole bridge."""

    sensors: tuple[SensorConfig, ...]
    name: str = DEFAULT_BRIDGE_NAME
    port: int = DEFAULT_PORT
    address: str | None = None
    stale_after_minutes: int = DEFAULT_STALE_AFTER_MINUTES


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
        env_var = bindkey_env_var(mac)
        try:
            bindkey = parse_bindkey(environ.get(env_var, ""))
        except ConfigError as err:
            raise ConfigError(f"${env_var}: {err}") from err
        return SensorConfig(name=name, mac=mac, bindkey=bindkey)
    except ConfigError as err:
        if str(err).startswith(where):
            raise
        raise ConfigError(f"{where}: {err}") from err


def parse_config(data: dict[str, Any], environ: Mapping[str, str] | None = None) -> BridgeConfig:
    """Build a :class:`BridgeConfig` from parsed TOML data and the environment."""
    env = os.environ if environ is None else environ
    _check_keys(data, {"bridge", "sensors"}, "top level")

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

    return BridgeConfig(
        sensors=sensors,
        name=name.strip(),
        port=port,
        address=address.strip() if address else None,
        stale_after_minutes=stale,
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
