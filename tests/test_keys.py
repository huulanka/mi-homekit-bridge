import stat
from pathlib import Path
from typing import Any

from mi_homekit_bridge.keys import collect_bindkeys, write_env_file

from .helpers import OTHER_MAC, TEST_BINDKEY_HEX, TEST_MAC


class FakeConnector:
    """Mimics the Xiaomi cloud responses used by ``collect_bindkeys``."""

    userId: str | None = "1000"

    def __init__(self) -> None:
        self.beaconkey_calls: list[str] = []

    async def get_homes(self, country: str) -> dict[str, Any] | None:
        if country != "de":
            return None
        return {"result": {"homelist": [{"id": 1}]}}

    async def get_dev_cnt(self, country: str) -> dict[str, Any] | None:
        if country != "de":
            return None
        return {"result": {"share": {"share_family": [{"home_id": 2, "home_owner": 2000}]}}}

    async def get_devices(self, country: str, home_id: str, owner_id: str) -> dict[str, Any] | None:
        devices = {
            "1": [
                {"mac": TEST_MAC.lower(), "did": "blt.3.own"},
                {"mac": "AA:BB:CC:DD:EE:FF", "did": "123456"},  # e.g. a Wi-Fi vacuum
            ],
            "2": [{"mac": OTHER_MAC, "did": "blt.3.shared"}],
        }
        return {"result": {"device_info": devices.get(home_id, [])}}

    async def get_beaconkey(self, country: str, did: str) -> dict[str, Any] | None:
        self.beaconkey_calls.append(did)
        return {"result": {"beaconkey": f"key-for-{did}"}}


async def test_collect_bindkeys_from_own_and_shared_homes() -> None:
    connector = FakeConnector()
    found = await collect_bindkeys(connector, [TEST_MAC, OTHER_MAC], ["cn", "de", "us"])
    assert found == {TEST_MAC: "key-for-blt.3.own", OTHER_MAC: "key-for-blt.3.shared"}
    # Non-BLE devices are never queried; search stops once everything is found.
    assert connector.beaconkey_calls == ["blt.3.own", "blt.3.shared"]


async def test_collect_bindkeys_reports_only_found_devices() -> None:
    found = await collect_bindkeys(FakeConnector(), ["A4:C1:38:12:34:56"], ["de"])
    assert found == {}


def test_write_env_file_creates_private_file(tmp_path: Path) -> None:
    path = tmp_path / "bindkeys.env"
    write_env_file(path, {TEST_MAC: TEST_BINDKEY_HEX})
    assert path.read_text() == f"MI_HOMEKIT_BRIDGE_BINDKEY_A4C138000001={TEST_BINDKEY_HEX}\n"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_write_env_file_updates_in_place(tmp_path: Path) -> None:
    path = tmp_path / "bindkeys.env"
    path.write_text(
        "# managed by hand\nOTHER=1\nexport MI_HOMEKIT_BRIDGE_BINDKEY_A4C138000001=old\n"
    )
    path.chmod(0o640)

    write_env_file(path, {TEST_MAC: "new1", OTHER_MAC: "new2"})

    assert path.read_text().splitlines() == [
        "# managed by hand",
        "OTHER=1",
        "MI_HOMEKIT_BRIDGE_BINDKEY_A4C138000001=new1",
        "MI_HOMEKIT_BRIDGE_BINDKEY_A4C138000002=new2",
    ]
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
