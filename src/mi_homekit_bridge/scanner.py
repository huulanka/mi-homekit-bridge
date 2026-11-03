"""Bluetooth scanning via bleak (BlueZ over D-Bus on Linux)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from habluetooth import BluetoothServiceInfoBleak

from .decoder import describe_format

ServiceInfoCallback = Callable[[BluetoothServiceInfoBleak], None]


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


def create_scanner(callback: ServiceInfoCallback) -> BleakScanner:
    """A scanner that forwards every advertisement to ``callback``."""
    loop = asyncio.get_running_loop()

    def on_detection(device: BLEDevice, advertisement: AdvertisementData) -> None:
        callback(service_info_from_bleak(device, advertisement, loop.time()))

    return BleakScanner(detection_callback=on_detection)


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
