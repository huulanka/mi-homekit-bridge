import stat
from pathlib import Path

import pytest

from mi_homekit_bridge import cli

from .helpers import OTHER_MAC, TEST_BINDKEY_HEX, TEST_MAC

KEY = TEST_BINDKEY_HEX

CONFIG = f"""
[[sensors]]
name = "Living Room"
mac = "{TEST_MAC}"

[[sensors]]
name = "Bedroom"
mac = "{OTHER_MAC}"
"""


def test_config_error_exit_code(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["run", "--config", str(tmp_path / "missing.toml")]) == 2
    assert "Configuration error" in capsys.readouterr().err


def _fake_cloud(monkeypatch: pytest.MonkeyPatch, result: dict[str, str]) -> None:
    async def fake_fetch(
        username: str, password: str, macs: list[str], servers: list[str] | None
    ) -> dict[str, str]:
        assert (username, password) == ("me@example.com", "secret")
        assert macs == [TEST_MAC, OTHER_MAC]
        return result

    monkeypatch.setattr("builtins.input", lambda _prompt: "me@example.com")
    monkeypatch.setattr("getpass.getpass", lambda _prompt: "secret")
    monkeypatch.setattr("mi_homekit_bridge.keys.fetch_bindkeys", fake_fetch)


def test_fetch_keys_writes_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "config.toml"
    config.write_text(CONFIG)
    env_file = tmp_path / "bindkeys.env"
    _fake_cloud(monkeypatch, {TEST_MAC: KEY})

    exit_code = cli.main(["fetch-keys", "--config", str(config), "--env-file", str(env_file)])

    out = capsys.readouterr()
    assert exit_code == 1  # Bedroom was not found
    assert KEY not in out.out  # keys are not echoed when written to a file
    assert "Bedroom" in out.err
    assert env_file.read_text() == f"MI_HOMEKIT_BRIDGE_BINDKEY_A4C138000001={KEY}\n"
    assert KEY not in config.read_text()


def test_fetch_keys_prints_env_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "config.toml"
    config.write_text(CONFIG)
    _fake_cloud(monkeypatch, {TEST_MAC: KEY, OTHER_MAC: KEY})

    assert cli.main(["fetch-keys", "--config", str(config)]) == 0
    assert f"MI_HOMEKIT_BRIDGE_BINDKEY_A4C138000002={KEY}" in capsys.readouterr().out


def test_rejected_login_explains_alternatives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from xiaomi_ble.cloud import XiaomiCloudInvalidPasswordException

    config = tmp_path / "config.toml"
    config.write_text(CONFIG)

    async def rejecting_fetch(*_args: object) -> dict[str, str]:
        raise XiaomiCloudInvalidPasswordException("Invalid password.")

    monkeypatch.setattr("builtins.input", lambda _prompt: "12345")
    monkeypatch.setattr("getpass.getpass", lambda _prompt: "pw")
    monkeypatch.setattr("mi_homekit_bridge.keys.fetch_bindkeys", rejecting_fetch)

    assert cli.main(["fetch-keys", "--config", str(config)]) == 2
    err = capsys.readouterr().err
    assert "Sign in with Apple" in err
    assert "set-key" in err


def test_set_key_stores_hidden_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    env_file = tmp_path / "bindkeys.env"
    monkeypatch.setattr("getpass.getpass", lambda _prompt: f" {KEY.upper()} ")

    assert cli.main(["set-key", TEST_MAC.lower(), "--env-file", str(env_file)]) == 0

    assert env_file.read_text() == f"MI_HOMEKIT_BRIDGE_BINDKEY_A4C138000001={KEY}\n"
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
    assert KEY not in capsys.readouterr().out


@pytest.mark.parametrize(
    ("mac", "key"), [("not-a-mac", KEY), (TEST_MAC, "too-short"), (TEST_MAC, "")]
)
def test_set_key_rejects_bad_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mac: str, key: str
) -> None:
    env_file = tmp_path / "bindkeys.env"
    monkeypatch.setattr("getpass.getpass", lambda _prompt: key)
    assert cli.main(["set-key", mac, "--env-file", str(env_file)]) == 2
    assert not env_file.exists()
