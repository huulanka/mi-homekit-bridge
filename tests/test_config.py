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
