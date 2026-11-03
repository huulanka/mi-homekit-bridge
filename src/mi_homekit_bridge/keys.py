"""Fetch bindkeys for stock-firmware sensors from the Xiaomi cloud.

Uses the cloud client that ships with ``xiaomi-ble`` (the one Home Assistant
uses), but logs in only once for all sensors so Xiaomi's two-factor check is
triggered at most once.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Protocol

import aiohttp
from xiaomi_ble.cloud import SERVERS, XiaomiCloudConnector

from .config import bindkey_env_var, normalize_mac


class CloudConnector(Protocol):
    """The subset of :class:`XiaomiCloudConnector` used here."""

    userId: str | None  # attribute name defined by xiaomi-ble

    async def get_homes(self, country: str) -> dict[str, Any] | None: ...

    async def get_dev_cnt(self, country: str) -> dict[str, Any] | None: ...

    async def get_devices(
        self, country: str, home_id: str, owner_id: str
    ) -> dict[str, Any] | None: ...

    async def get_beaconkey(self, country: str, did: str) -> dict[str, Any] | None: ...


async def collect_bindkeys(
    connector: CloudConnector, macs: list[str], servers: list[str]
) -> dict[str, str]:
    """Return ``{mac: bindkey}`` for every requested MAC found in the account."""
    wanted = {normalize_mac(mac) for mac in macs}
    found: dict[str, str] = {}
    owner = connector.userId or ""

    for server in servers:
        homes: dict[str, str] = {}
        home_info = await connector.get_homes(server)
        if home_info is not None:
            for home in home_info["result"]["homelist"]:
                homes[str(home["id"])] = owner
        shared = await connector.get_dev_cnt(server)
        if shared is not None:
            for home in shared["result"]["share"]["share_family"]:
                homes[str(home["home_id"])] = str(home["home_owner"])

        for home_id, owner_id in homes.items():
            devices = await connector.get_devices(server, home_id, owner_id)
            if not devices or not devices.get("result"):
                continue
            for device in devices["result"].get("device_info") or []:
                mac = str(device.get("mac", "")).upper()
                did = str(device.get("did", ""))
                if mac not in wanted or mac in found or "blt" not in did:
                    continue
                key_result = await connector.get_beaconkey(server, did)
                beaconkey = ((key_result or {}).get("result") or {}).get("beaconkey")
                if beaconkey:
                    found[mac] = str(beaconkey)
        if found.keys() >= wanted:
            break
    return found


async def fetch_bindkeys(
    username: str, password: str, macs: list[str], servers: list[str] | None = None
) -> dict[str, str]:
    """Log in to the Xiaomi cloud once and fetch the bindkeys for ``macs``.

    Raises the ``xiaomi_ble.cloud`` exceptions on login problems, including
    ``XiaomiCloudTwoFactorAuthenticationException`` (with a ``url`` to open).
    """
    async with aiohttp.ClientSession() as session:
        connector = XiaomiCloudConnector(username, password, session)
        await connector.login()
        return await collect_bindkeys(connector, macs, servers or list(SERVERS))


def write_env_file(path: Path, bindkeys: dict[str, str]) -> None:
    """Create or update an environment file (``KEY=value`` lines) with bindkeys.

    The file is meant for systemd's ``EnvironmentFile=``. Unrelated lines are kept,
    a new file is created with mode 600, an existing file keeps its mode.
    """
    wanted = {bindkey_env_var(mac): key for mac, key in bindkeys.items()}
    lines = path.read_text().splitlines() if path.exists() else []
    output: list[str] = []
    for line in lines:
        match = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=", line)
        name = match.group(1) if match else None
        if name in wanted:
            output.append(f"{name}={wanted.pop(name)}")
        else:
            output.append(line)
    output.extend(f"{name}={key}" for name, key in wanted.items())

    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w") as fh:
        fh.write("\n".join(output) + "\n")
    os.chmod(tmp, mode)
    tmp.replace(path)
