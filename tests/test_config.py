from pathlib import Path
from typing import Any

import pytest

from mi_homekit_bridge.config import (
    DEFAULT_PORT,
    ConfigError,
    bindkey_env_var,
    load_config,
    normalize_mac,
    parse_bindkey,
    parse_config,
)

from .helpers import TEST_BINDKEY, TEST_BINDKEY_HEX

KEY_HEX = TEST_BINDKEY_HEX


def _sensor(**overrides: Any) -> dict[str, Any]:
    return {"name": "Living Room", "mac": "a4:c1:38:00:00:01"} | overrides


def test_minimal_config_uses_defaults() -> None:
    config = parse_config({"sensors": [_sensor()]}, environ={})
    assert config.port == DEFAULT_PORT
    assert config.address is None
    assert config.sensors[0].mac == "A4:C1:38:00:00:01"
    assert config.sensors[0].bindkey is None


@pytest.mark.parametrize("raw", ["a4c138000001", "A4-C1-38-00-00-01", " a4:c1:38:00:00:01 "])
def test_normalize_mac(raw: str) -> None:
    assert normalize_mac(raw) == "A4:C1:38:00:00:01"


@pytest.mark.parametrize("raw", ["", "A4:C1:38:00:00", "zz:c1:38:00:00:01"])
def test_normalize_mac_rejects_garbage(raw: str) -> None:
    with pytest.raises(ConfigError):
        normalize_mac(raw)


def test_parse_bindkey() -> None:
    assert parse_bindkey("") is None
    assert parse_bindkey(TEST_BINDKEY_HEX.upper()) == TEST_BINDKEY
    with pytest.raises(ConfigError):
        parse_bindkey("0011")


def test_bindkey_env_var_name() -> None:
    assert bindkey_env_var("a4:c1:38:00:00:01") == "MI_HOMEKIT_BRIDGE_BINDKEY_A4C138000001"


def test_bindkey_is_read_from_environment() -> None:
    environ = {"MI_HOMEKIT_BRIDGE_BINDKEY_A4C138000001": KEY_HEX.upper()}
    config = parse_config({"sensors": [_sensor()]}, environ=environ)
    assert config.sensors[0].bindkey == bytes.fromhex(KEY_HEX)


def test_invalid_bindkey_in_environment_names_variable() -> None:
    environ = {"MI_HOMEKIT_BRIDGE_BINDKEY_A4C138000001": "nope"}
    with pytest.raises(ConfigError, match=r"sensors\[0\].*MI_HOMEKIT_BRIDGE_BINDKEY_A4C138000001"):
        parse_config({"sensors": [_sensor()]}, environ=environ)


def test_bindkey_in_config_file_is_refused() -> None:
    with pytest.raises(ConfigError, match="must not be stored in the config file"):
        parse_config({"sensors": [_sensor(bindkey=KEY_HEX)]}, environ={})


@pytest.mark.parametrize("attr", ["name", "mac"])
def test_duplicates_are_rejected(attr: str) -> None:
    second = _sensor(name="Bedroom", mac="a4:c1:38:00:00:02")
    second[attr] = _sensor()[attr]
    with pytest.raises(ConfigError, match="duplicate"):
        parse_config({"sensors": [_sensor(), second]}, environ={})


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"sensors": []},
        {"sensors": [_sensor()], "typo": 1},
        {"sensors": [_sensor(colour="red")]},
        {"sensors": [_sensor()], "bridge": {"port": 0}},
        {"sensors": [_sensor()], "bridge": {"port": True}},
        {"sensors": [_sensor()], "bridge": {"stale_after_minutes": 0}},
        {"sensors": [_sensor()], "bridge": {"name": " "}},
        {"sensors": [{"mac": "a4c138000001"}]},
    ],
)
def test_invalid_configs(data: dict[str, Any]) -> None:
    with pytest.raises(ConfigError):
        parse_config(data, environ={})


def test_load_config(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        '[bridge]\nname = "Test"\naddress = "192.0.2.10"\n\n'
        '[[sensors]]\nname = "Bedroom"\nmac = "A4:C1:38:00:00:01"\n'
    )
    config = load_config(path, environ={bindkey_env_var("A4:C1:38:00:00:01"): KEY_HEX})
    assert config.name == "Test"
    assert config.address == "192.0.2.10"
    assert config.sensors[0].bindkey is not None


def test_load_config_errors(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "missing.toml")
    broken = tmp_path / "broken.toml"
    broken.write_text("[bridge\n")
    with pytest.raises(ConfigError):
        load_config(broken)


def test_example_config_is_valid() -> None:
    example = Path(__file__).parent.parent / "config.example.toml"
    config = load_config(example, environ={})
    assert len(config.sensors) == 2


def _weather(**weather: Any) -> dict[str, Any]:
    return {"sensors": [_sensor()], "weather": {"enabled": True} | weather}


def test_history_and_weather_defaults() -> None:
    config = parse_config({"sensors": [_sensor()]}, environ={})
    assert config.history.enabled
    assert config.history.interval_minutes == 5
    assert not config.weather.enabled


def test_weather_by_postal_code() -> None:
    config = parse_config(_weather(postal_code="80331", country="de", name="Außen"), environ={})
    assert config.weather.enabled
    assert (config.weather.postal_code, config.weather.country) == ("80331", "DE")
    assert config.weather.name == "Außen"
    assert config.weather.interval_minutes == 15


def test_weather_by_coordinates() -> None:
    config = parse_config(_weather(latitude=52.52, longitude=13.405), environ={})
    assert (config.weather.latitude, config.weather.longitude) == (52.52, 13.405)


@pytest.mark.parametrize(
    ("weather", "message"),
    [
        ({}, "set a location"),
        ({"postal_code": "80331"}, "set together"),
        ({"postal_code": 80331, "country": "DE"}, "as a string"),
        ({"postal_code": "80331", "country": "Germany"}, "two-letter"),
        ({"latitude": 52.5}, "set together"),
        ({"latitude": 91, "longitude": 0}, "between -90 and 90"),
        ({"postal_code": "1", "country": "DE", "latitude": 1, "longitude": 1}, "either"),
        ({"provider": "acme", "latitude": 1, "longitude": 1}, "one of"),
        ({"latitude": 1, "longitude": 1, "interval_minutes": 1}, "between 5 and 180"),
        ({"latitude": 1, "longitude": 1, "name": "Living Room"}, "already used"),
    ],
)
def test_invalid_weather(weather: dict[str, Any], message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        parse_config(_weather(**weather), environ={})


def test_weather_needs_history() -> None:
    data = _weather(latitude=1, longitude=1) | {"history": {"enabled": False}}
    with pytest.raises(ConfigError, match="needs \\[history\\]"):
        parse_config(data, environ={})


def test_disabled_weather_location_is_optional() -> None:
    config = parse_config({"sensors": [_sensor()], "weather": {"enabled": False}}, environ={})
    assert not config.weather.enabled


@pytest.mark.parametrize(
    "history", [{"enabled": "yes"}, {"interval_minutes": 0}, {"interval_minutes": 61}, {"x": 1}]
)
def test_invalid_history(history: dict[str, Any]) -> None:
    with pytest.raises(ConfigError):
        parse_config({"sensors": [_sensor()], "history": history}, environ={})


def test_web_defaults_and_options() -> None:
    assert not parse_config({"sensors": [_sensor()]}, environ={}).web.enabled
    web = parse_config(
        {"sensors": [_sensor()], "web": {"enabled": True, "port": 9000, "host": "0.0.0.0"}},  # noqa: S104
        environ={},
    ).web
    assert (web.enabled, web.host, web.port) == (True, "0.0.0.0", 9000)  # noqa: S104


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"web": {"enabled": True}, "history": {"enabled": False}}, "needs \\[history\\]"),
        ({"web": {"enabled": True, "port": 51826}}, "must differ"),
        ({"web": {"port": 0}}, "between 1 and 65535"),
        ({"web": {"enabled": 1}}, "true or false"),
        ({"web": {"listen": "x"}}, "unknown option"),
    ],
)
def test_invalid_web(data: dict[str, Any], message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        parse_config({"sensors": [_sensor()]} | data, environ={})
