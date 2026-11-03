"""Glue between the Bluetooth scanner, the decoders and HomeKit."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
from dataclasses import dataclass, field
from pathlib import Path

from habluetooth import BluetoothServiceInfoBleak
from pyhap.accessory_driver import AccessoryDriver

from .config import BridgeConfig, SensorConfig
from .decoder import SensorDecoder
from .homekit import ThermometerAccessory, create_bridge, create_driver
from .scanner import create_scanner

_LOGGER = logging.getLogger(__name__)

STALE_CHECK_INTERVAL_SECONDS = 60.0


@dataclass(slots=True)
class SensorChannel:
    """Everything that belongs to one physical sensor."""

    config: SensorConfig
    decoder: SensorDecoder
    accessory: ThermometerAccessory
    last_seen: float | None = None
    stale: bool = field(default=True)
    """Sensors start as stale ("no data yet") until the first reading arrives."""


class BridgeApp:
    """Routes advertisements to the right accessory and tracks stale sensors."""

    def __init__(self, config: BridgeConfig, driver: AccessoryDriver) -> None:
        self._stale_after = config.stale_after_minutes * 60.0
        _, accessories = create_bridge(driver, config)
        self.channels: dict[str, SensorChannel] = {
            sensor.mac: SensorChannel(
                config=sensor,
                decoder=SensorDecoder(sensor.bindkey),
                accessory=accessories[sensor.mac],
            )
            for sensor in config.sensors
        }

    def handle_advertisement(self, info: BluetoothServiceInfoBleak, now: float) -> None:
        channel = self.channels.get(info.address.upper())
        if channel is None:
            return
        reading = channel.decoder.decode(info)
        if reading is None:
            return
        channel.accessory.apply(reading)
        channel.last_seen = now
        if channel.stale:
            channel.stale = False
            channel.accessory.set_fault(False)
            _LOGGER.info("%s is reporting (rssi %s dBm)", channel.config.name, info.rssi)
        _LOGGER.debug("%s: %s (rssi %s dBm)", channel.config.name, reading, info.rssi)

    def check_stale(self, now: float) -> bool:
        """Flag sensors without readings for too long. Returns ``True`` if all are stale."""
        for channel in self.channels.values():
            if channel.stale or channel.last_seen is None:
                continue
            if now - channel.last_seen >= self._stale_after:
                channel.stale = True
                channel.accessory.set_fault(True)
                _LOGGER.warning(
                    "%s has not reported for %d minutes",
                    channel.config.name,
                    self._stale_after // 60,
                )
        return all(channel.stale for channel in self.channels.values())


async def run_bridge(config: BridgeConfig, state_dir: Path) -> None:
    """Run until SIGINT/SIGTERM."""
    loop = asyncio.get_running_loop()
    driver = create_driver(config, state_dir, loop)
    app = BridgeApp(config, driver)

    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    scanner = create_scanner(lambda info: app.handle_advertisement(info, loop.time()))
    await driver.async_start()
    await scanner.start()
    _LOGGER.info("Bridge '%s' running with %d sensor(s)", config.name, len(app.channels))
    last_restart = loop.time()
    try:
        while not stop.is_set():
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=STALE_CHECK_INTERVAL_SECONDS)
            now = loop.time()
            if app.check_stale(now) and now - last_restart >= config.stale_after_minutes * 60:
                # No sensor reported at all: the BlueZ discovery session may have died
                # (e.g. bluetoothd restart). Restarting the scan is cheap and harmless.
                _LOGGER.warning("No sensor is reporting, restarting Bluetooth scan")
                last_restart = now
                await scanner.stop()
                await scanner.start()
    finally:
        _LOGGER.info("Shutting down")
        await scanner.stop()
        await driver.async_stop()
