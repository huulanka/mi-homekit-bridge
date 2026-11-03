"""Glue between the Bluetooth scanner, the decoders, HomeKit and the history."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

import aiohttp
from habluetooth import BluetoothServiceInfoBleak
from pyhap.accessory_driver import AccessoryDriver

from .config import BridgeConfig, SensorConfig
from .decoder import Reading, SensorDecoder
from .history import HistoryStore, Sample, SensorInfo
from .homekit import ThermometerAccessory, create_bridge, create_driver
from .scanner import create_scanner
from .weather import WeatherError, WeatherProvider, create_provider
from .web import start_web

_LOGGER = logging.getLogger(__name__)

STALE_CHECK_INTERVAL_SECONDS = 60.0
WEATHER_SENSOR_ID = "weather"
HISTORY_FILENAME = "history.db"


@dataclass(slots=True)
class SensorChannel:
    """Everything that belongs to one physical sensor."""

    config: SensorConfig
    decoder: SensorDecoder
    accessory: ThermometerAccessory
    last_seen: float | None = None
    stale: bool = field(default=True)
    """Sensors start as stale ("no data yet") until the first reading arrives."""
    temperature: float | None = None
    humidity: float | None = None
    battery: int | None = None

    def remember(self, reading: Reading) -> None:
        if reading.temperature is not None:
            self.temperature = reading.temperature
        if reading.humidity is not None:
            self.humidity = reading.humidity
        if reading.battery is not None:
            self.battery = reading.battery


class BridgeApp:
    """Routes advertisements to the right accessory and tracks stale sensors."""

    def __init__(self, config: BridgeConfig, driver: AccessoryDriver) -> None:
        self._config = config
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
        channel.remember(reading)
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

    # -- history ---------------------------------------------------------------

    def sensor_infos(self) -> list[SensorInfo]:
        infos = [SensorInfo(mac, ch.config.name, "ble") for mac, ch in self.channels.items()]
        if self._config.weather.enabled:
            infos.append(SensorInfo(WEATHER_SENSOR_ID, self._config.weather.name, "weather"))
        return infos

    def restore(self, latest: dict[str, Sample]) -> None:
        """Show the last recorded values after a restart instead of zeros.

        Sensors stay flagged as faulty until they report again, and restored values
        are not recorded a second time.
        """
        for mac, sample in latest.items():
            channel = self.channels.get(mac)
            if channel is None:
                continue
            reading = Reading(sample.temperature, sample.humidity, sample.battery)
            channel.accessory.apply(reading)
            channel.remember(reading)

    def samples(self, ts: int) -> list[Sample]:
        """Current values of all sensors that are reporting."""
        return [
            Sample(mac, ts, ch.temperature, ch.humidity, ch.battery)
            for mac, ch in self.channels.items()
            if not ch.stale and (ch.temperature is not None or ch.humidity is not None)
        ]


async def _run_aligned(
    interval_seconds: int, stop: asyncio.Event, job: Callable[[int], Awaitable[None]]
) -> None:
    """Call ``job(ts)`` on wall-clock aligned boundaries (e.g. :00, :05, :10)."""
    while not stop.is_set():
        delay = interval_seconds - (time.time() % interval_seconds)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=delay)
        if stop.is_set():
            return
        ts = int(time.time() // interval_seconds * interval_seconds)
        try:
            await job(ts)
        except Exception:  # keep the bridge running whatever happens here
            _LOGGER.exception("Periodic job %s failed", getattr(job, "__name__", job))


async def _fetch_weather(provider: WeatherProvider, store: HistoryStore) -> None:
    try:
        observation = await provider.current()
    except WeatherError as err:
        _LOGGER.warning("Weather update failed: %s", err)
        return
    sample = Sample(
        WEATHER_SENSOR_ID, observation.ts, observation.temperature, observation.humidity
    )
    await asyncio.to_thread(store.add_samples, [sample])
    _LOGGER.debug("Weather: %s", observation)


async def run_bridge(config: BridgeConfig, state_dir: Path) -> None:
    """Run until SIGINT/SIGTERM."""
    loop = asyncio.get_running_loop()
    driver = create_driver(config, state_dir, loop)
    app = BridgeApp(config, driver)

    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    async with contextlib.AsyncExitStack() as stack:
        store: HistoryStore | None = None
        if config.history.enabled:
            store = HistoryStore(state_dir / HISTORY_FILENAME)
            stack.callback(store.close)
            await asyncio.to_thread(store.upsert_sensors, app.sensor_infos())
            latest = {mac: await asyncio.to_thread(store.latest, mac) for mac in app.channels}
            app.restore({mac: sample for mac, sample in latest.items() if sample})
            _LOGGER.info(
                "Recording every %d minute(s) to %s",
                config.history.interval_minutes,
                store.path,
            )
            if config.web.enabled:
                runner = await start_web(store, config.web.host, config.web.port)
                stack.push_async_callback(runner.cleanup)

        scanner = create_scanner(lambda info: app.handle_advertisement(info, loop.time()))
        await driver.async_start()
        stack.push_async_callback(driver.async_stop)
        await scanner.start()
        stack.push_async_callback(scanner.stop)
        _LOGGER.info("Bridge '%s' running with %d sensor(s)", config.name, len(app.channels))

        background: list[asyncio.Task[None]] = []
        if store is not None:
            history_store = store

            async def record(ts: int) -> None:
                samples = app.samples(ts)
                if samples:
                    await asyncio.to_thread(history_store.add_samples, samples)

            background.append(
                asyncio.create_task(
                    _run_aligned(config.history.interval_minutes * 60, stop, record)
                )
            )

            if config.weather.enabled:
                session = await stack.enter_async_context(aiohttp.ClientSession())
                provider = create_provider(session, config.weather)

                async def weather(_ts: int) -> None:
                    await _fetch_weather(provider, history_store)

                await weather(0)
                background.append(
                    asyncio.create_task(
                        _run_aligned(config.weather.interval_minutes * 60, stop, weather)
                    )
                )

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
            stop.set()
            await asyncio.gather(*background, return_exceptions=True)
