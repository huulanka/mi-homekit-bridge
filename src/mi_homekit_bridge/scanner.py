"""Bluetooth scanning via bleak (BlueZ over D-Bus on Linux)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from bleak import BleakScanner
from bleak.args.bluez import BlueZScannerArgs, OrPattern
from bleak.assigned_numbers import AdvertisementDataType
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from habluetooth import BluetoothServiceInfoBleak

from .config import DEFAULT_ADAPTER, ScanningMode
from .decoder import BTHOME_SERVICE_UUID, XIAOMI_SERVICE_UUID, describe_format

ServiceInfoCallback = Callable[[BluetoothServiceInfoBleak], None]


def _uuid16_le(uuid: str) -> bytes:
    """``0000fe95-0000-...`` -> ``b"\\x95\\xfe"`` (as it appears in service data)."""
    return int(uuid[4:8], 16).to_bytes(2, "little")


# Passive scanning goes through BlueZ advertisement monitors, which need patterns.
# These match the service data of MiBeacon and BTHome advertisements, so BlueZ
# only forwards advertisements of supported sensors.
PASSIVE_PATTERNS = [
    OrPattern(0, AdvertisementDataType.SERVICE_DATA_UUID16, _uuid16_le(uuid))
    for uuid in (XIAOMI_SERVICE_UUID, BTHOME_SERVICE_UUID)
]


def service_info_from_bleak(
    device: BLEDevice, advertisement: AdvertisementData, now: float
) -> BluetoothServiceInfoBleak:
    """Convert bleak's callback arguments into what the parser libraries expect."""
    return BluetoothServiceInfoBleak(
        name=advertisement.local_name or device.name or device.address,
        address=device.address,
        rssi=advertisement.rssi,
        manufacturer_data=advertisement.manufacturer_data,
        service_data=advertisement.service_data,
        service_uuids=advertisement.service_uuids,
        source="local",
        device=device,
        advertisement=advertisement,
        connectable=True,
        time=now,
        tx_power=advertisement.tx_power,
    )


def create_scanner(
    callback: ServiceInfoCallback,
    *,
    adapter: str = DEFAULT_ADAPTER,
    scanning_mode: ScanningMode = "active",
) -> BleakScanner:
    """A scanner that forwards every advertisement to ``callback``."""
    loop = asyncio.get_running_loop()

    def on_detection(device: BLEDevice, advertisement: AdvertisementData) -> None:
        callback(service_info_from_bleak(device, advertisement, loop.time()))

    bluez: BlueZScannerArgs = {"adapter": adapter}
    if scanning_mode == "passive":
        bluez["or_patterns"] = list(PASSIVE_PATTERNS)
    return BleakScanner(detection_callback=on_detection, scanning_mode=scanning_mode, bluez=bluez)


async def discover(seconds: float) -> list[tuple[str, str, int, str]]:
    """Scan for supported thermometers: ``(address, name, best_rssi, format)``."""
    found: dict[str, tuple[str, str, int, str]] = {}

    def on_info(info: BluetoothServiceInfoBleak) -> None:
        fmt = describe_format(info.service_data)
        if fmt is None:
            return
        previous = found.get(info.address)
        rssi = info.rssi if previous is None else max(previous[2], info.rssi)
        found[info.address] = (info.address, info.name, rssi, fmt)

    scanner = create_scanner(on_info)
    await scanner.start()
    try:
        await asyncio.sleep(seconds)
    finally:
        await scanner.stop()
    return sorted(found.values(), key=lambda item: item[2], reverse=True)
