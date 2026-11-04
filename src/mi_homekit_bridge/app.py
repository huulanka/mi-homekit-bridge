"""Glue between the Bluetooth scanner, the decoders, HomeKit and the history."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import sqlite3
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import aiohttp
from bleak import BleakScanner
from habluetooth import BluetoothServiceInfoBleak
from pyhap.accessory_driver import AccessoryDriver

from . import __version__, climate
from .bluetooth import ScanSupervisor
from .config import BluetoothConfig, BridgeConfig, ScanningMode, SensorConfig
from .decoder import Reading, SensorDecoder
from .history import Event, HistoryStore, Sample, SensorInfo
from .homekit import ThermometerAccessory, create_bridge, create_driver
from .scanner import ServiceInfoCallback, create_scanner
from .status import BridgeStatus, SensorStatus
from .system import POLL_SECONDS, SystemMonitor
from .systemd import clock_synchronized, notify, watchdog_interval
from .weather import WeatherError, WeatherProvider, create_provider
from .web import start_web

_LOGGER = logging.getLogger(__name__)

MONITOR_INTERVAL_SECONDS = 30.0
WEATHER_SENSOR_ID = "weather"
HISTORY_FILENAME = "history.db"
MIN_FRESH_SECONDS = 300
"""A value is recorded only if it was received within the last history interval,
but at least within this many seconds."""
OUTDOOR_MAX_AGE_SECONDS = 3 * 3600
"""Older outdoor values are not used for the HomeKit air quality."""


class EventLog:
    """Records events in the history database, if there is one. Never raises."""

    def __init__(self, store: HistoryStore | None, clock: Callable[[], float] = time.time) -> None:
        self._store = store
        self._clock = clock

    def __call__(self, kind: str, sensor_id: str | None = None, /, **data: object) -> None:
        if self._store is None:
            return
        try:
            self._store.add_event(Event(int(self._clock()), kind, sensor_id, data))
        except sqlite3.Error:
            _LOGGER.exception("Could not record event %s", kind)


class ScannerFactory:
    """Creates scanners as configured; falls back from passive to active once if
    passive scanning does not work on this system."""

    def __init__(
        self, callback: ServiceInfoCallback, bluetooth: BluetoothConfig, events: EventLog
    ) -> None:
        self._callback = callback
        self._adapter = bluetooth.adapter
        self._events = events
        self.mode: ScanningMode = bluetooth.scanning_mode

    def __call__(self) -> BleakScanner:
        return create_scanner(self._callback, adapter=self._adapter, scanning_mode=self.mode)

    def fall_back(self, reason: str) -> bool:
        if self.mode != "passive":
            return False
        self.mode = "active"
        _LOGGER.warning(
            "Passive scanning does not work on this system (%s), using active scanning. "
            "It needs bluetoothd --experimental and kernel support; set "
            'scanning_mode = "active" in [bluetooth] to silence this warning.',
            reason,
        )
        self._events("passive_unavailable", reason=reason)
        return True


@dataclass(slots=True)
class SensorChannel:
    """Everything that belongs to one physical sensor."""

    config: SensorConfig
    decoder: SensorDecoder
    accessory: ThermometerAccessory
    last_seen: float | None = None
    """Monotonic time of the last reading."""
    rssi: int | None = None
    stale: bool = field(default=True)
    """Sensors start as stale ("no data yet") until the first reading arrives."""
    lost: bool = False
    """It stopped reporting after it had reported before."""
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


def sensor_infos(config: BridgeConfig) -> list[SensorInfo]:
    """All sensors to register in the history, including the weather 'sensor'."""
    infos = [
        SensorInfo(sensor.mac, sensor.name, "ble", sensor.target_temperature, sensor.surface_factor)
        for sensor in config.sensors
    ]
    if config.weather.enabled:
        infos.append(SensorInfo(WEATHER_SENSOR_ID, config.weather.name, "weather"))
    return infos


class BridgeApp:
    """Routes advertisements to the right accessory and tracks stale sensors."""

    def __init__(
        self,
        config: BridgeConfig,
        driver: AccessoryDriver,
        *,
        events: EventLog | None = None,
        with_battery: frozenset[str] = frozenset(),
    ) -> None:
        self._config = config
        self._driver = driver
        self._events = events if events is not None else EventLog(None)
        self._stale_after = config.stale_after_minutes * 60.0
        self._fresh_for = max(config.history.interval_minutes * 60, MIN_FRESH_SECONDS)
        _, accessories = create_bridge(driver, config, with_battery)
        self.outdoor: Sample | None = None
        """The latest outdoor values (for the air quality)."""
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
        if channel.accessory.apply(reading):
            _LOGGER.info("%s reports its battery level, adding it to HomeKit", channel.config.name)
            self._driver.config_changed()
        channel.remember(reading)
        previous, channel.last_seen, channel.rssi = channel.last_seen, now, info.rssi
        if channel.stale:
            channel.stale = False
            channel.accessory.set_fault(False)
            _LOGGER.info("%s is reporting (rssi %s dBm)", channel.config.name, info.rssi)
            if channel.lost and previous is not None:
                self._events(
                    "sensor_back", channel.config.mac, minutes=round((now - previous) / 60)
                )
            channel.lost = False
        _LOGGER.debug("%s: %s (rssi %s dBm)", channel.config.name, reading, info.rssi)

    def check_stale(self, now: float) -> None:
        """Flag sensors without readings for ``stale_after_minutes`` as faulty."""
        for channel in self.channels.values():
            if channel.stale or channel.last_seen is None:
                continue
            if now - channel.last_seen >= self._stale_after:
                channel.stale = channel.lost = True
                channel.accessory.set_fault(True)
                minutes = round(self._stale_after / 60)
                _LOGGER.warning("%s has not reported for %d minutes", channel.config.name, minutes)
                self._events("sensor_lost", channel.config.mac, minutes=minutes)

    def bluetooth_down(self) -> None:
        """The scan does not work: flag all sensors as faulty right away."""
        for channel in self.channels.values():
            if not channel.stale:
                channel.stale = True
                channel.accessory.set_fault(True)

    def update_air_quality(self, wall: float) -> None:
        """Mould risk as HomeKit air quality, from the current indoor and outdoor values."""
        outdoor = self.outdoor
        outside = (
            outdoor.temperature
            if outdoor is not None and wall - outdoor.ts <= OUTDOOR_MAX_AGE_SECONDS
            else None
        )
        for channel in self.channels.values():
            surface = None
            if not channel.stale:
                surface = climate.surface_humidity(
                    channel.temperature,
                    channel.humidity,
                    outside,
                    channel.config.surface_factor or climate.DEFAULT_SURFACE_FACTOR,
                )
            channel.accessory.set_air_quality(climate.air_quality(surface))

    # -- history ---------------------------------------------------------------

    def restore(self, latest: Mapping[str, Sample]) -> None:
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

    def samples(self, ts: int, now: float) -> list[Sample]:
        """Values of all sensors that delivered a reading recently.

        A sensor that went silent is not recorded with its last value: the history
        shows a gap instead of a flat line.
        """
        return [
            Sample(mac, ts, ch.temperature, ch.humidity, ch.battery)
            for mac, ch in self.channels.items()
            if not ch.stale
            and ch.last_seen is not None
            and now - ch.last_seen <= self._fresh_for
            and (ch.temperature is not None or ch.humidity is not None)
        ]

    # -- status ----------------------------------------------------------------

    def status(
        self,
        supervisor: ScanSupervisor,
        *,
        scanning_mode: ScanningMode,
        started: float,
        now: float,
        wall: float,
        system: SystemMonitor | None = None,
    ) -> BridgeStatus:
        """Live status. ``started`` and ``now`` are monotonic, ``wall`` is ``time.time()``."""

        def to_wall(moment: float | None) -> int | None:
            return None if moment is None else round(wall - (now - moment))

        running_long = now - started >= self._stale_after
        state = self._driver.state
        return BridgeStatus(
            version=__version__,
            started_at=round(wall - (now - started)),
            bluetooth_state=supervisor.state.value,
            bluetooth_since=round(wall - (now - supervisor.since)),
            bluetooth_error=supervisor.last_error,
            scanning_mode=scanning_mode,
            last_advertisement=to_wall(supervisor.last_advertisement),
            homekit_paired=bool(state.paired),
            homekit_controllers=len(state.paired_clients),
            sensors=tuple(
                SensorStatus(
                    id=mac,
                    name=ch.config.name,
                    reporting=not ch.stale,
                    problem=ch.stale and (ch.last_seen is not None or running_long),
                    last_seen=to_wall(ch.last_seen),
                    rssi=ch.rssi,
                )
                for mac, ch in self.channels.items()
            ),
            system=system.health() if system is not None and system.available else None,
        )

    def status_line(self, supervisor: ScanSupervisor) -> str:
        """Short summary for ``systemctl status``."""
        reporting = sum(not ch.stale for ch in self.channels.values())
        return (
            f"Bluetooth {supervisor.state.value}, "
            f"{reporting}/{len(self.channels)} sensors reporting"
        )


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


async def _fetch_weather(provider: WeatherProvider, store: HistoryStore) -> Sample | None:
    try:
        observation = await provider.current()
    except WeatherError as err:
        _LOGGER.warning("Weather update failed: %s", err)
        return None
    sample = Sample(
        WEATHER_SENSOR_ID,
        observation.ts,
        observation.temperature,
        observation.humidity,
        radiation=observation.radiation,
        wind=observation.wind,
        precipitation=observation.precipitation,
    )
    await asyncio.to_thread(store.add_samples, [sample])
    _LOGGER.debug("Weather: %s", observation)
    return sample


class Recorder:
    """Writes the current values into the history every interval."""

    def __init__(
        self,
        app: BridgeApp,
        store: HistoryStore,
        monotonic: Callable[[], float],
        clock_ok: Callable[[], bool] = clock_synchronized,
    ) -> None:
        self._app = app
        self._store = store
        self._monotonic = monotonic
        self._clock_ok = clock_ok
        self._waiting_for_clock = False

    async def __call__(self, ts: int) -> None:
        if not self._clock_ok():
            if not self._waiting_for_clock:
                _LOGGER.warning("The system clock is not synchronized yet, not recording")
                self._waiting_for_clock = True
            return
        self._waiting_for_clock = False
        samples = self._app.samples(ts, self._monotonic())
        if samples:
            await asyncio.to_thread(self._store.add_samples, samples)


async def run_bridge(config: BridgeConfig, state_dir: Path) -> None:
    """Run until SIGINT/SIGTERM.

    Raises :class:`~mi_homekit_bridge.bluetooth.ControllerResetRequired` if the
    Bluetooth controller is stuck; the caller exits with the matching status.
    """
    loop = asyncio.get_running_loop()
    started = loop.time()
    driver = create_driver(config, state_dir, loop)

    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    async with contextlib.AsyncExitStack() as stack:
        store: HistoryStore | None = None
        latest: dict[str, Sample] = {}
        outdoor: Sample | None = None
        if config.history.enabled:
            store = HistoryStore(state_dir / HISTORY_FILENAME)
            stack.callback(store.close)
            await asyncio.to_thread(store.upsert_sensors, sensor_infos(config))
            for sensor in config.sensors:
                sample = await asyncio.to_thread(store.latest, sensor.mac)
                if sample is not None:
                    latest[sensor.mac] = sample
            if config.weather.enabled:
                outdoor = await asyncio.to_thread(store.latest, WEATHER_SENSOR_ID)

        events = EventLog(store)
        app = BridgeApp(
            config,
            driver,
            events=events,
            with_battery=frozenset(m for m, s in latest.items() if s.battery is not None),
        )
        app.restore(latest)
        app.outdoor = outdoor
        system = SystemMonitor(events=lambda kind, **data: events(kind, **data))

        def on_advertisement(info: BluetoothServiceInfoBleak) -> None:
            now = loop.time()
            supervisor.advertisement_seen(now)
            app.handle_advertisement(info, now)

        factory = ScannerFactory(on_advertisement, config.bluetooth, events)
        supervisor = ScanSupervisor(
            factory,
            state_dir=state_dir,
            listener=lambda kind, data: events(kind, **data),
            fallback=factory.fall_back,
        )

        def status() -> BridgeStatus:
            return app.status(
                supervisor,
                scanning_mode=factory.mode,
                started=started,
                now=loop.time(),
                wall=time.time(),
                system=system,
            )

        if store is not None:
            _LOGGER.info(
                "Recording every %d minute(s) to %s",
                config.history.interval_minutes,
                store.path,
            )
            if config.web.enabled:
                runner = await start_web(
                    store,
                    config.web.host,
                    config.web.port,
                    status=status,
                    interval=config.history.interval_minutes * 60,
                )
                stack.push_async_callback(runner.cleanup)

        await driver.async_start()
        stack.push_async_callback(driver.async_stop)
        await supervisor.start(loop.time())
        stack.push_async_callback(supervisor.stop)
        events("started", version=__version__)
        _LOGGER.info(
            "Bridge '%s' running with %d sensor(s), %s Bluetooth scan on %s",
            config.name,
            len(app.channels),
            config.bluetooth.scanning_mode,
            config.bluetooth.adapter,
        )
        notify("READY=1", f"STATUS={app.status_line(supervisor)}")

        background: list[asyncio.Task[None]] = []
        if system.available:

            async def system_loop() -> None:
                while not stop.is_set():
                    system.poll()
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(stop.wait(), timeout=POLL_SECONDS)

            background.append(asyncio.create_task(system_loop()))
        if store is not None:
            recorder = Recorder(app, store, loop.time)
            background.append(
                asyncio.create_task(
                    _run_aligned(config.history.interval_minutes * 60, stop, recorder)
                )
            )
            if config.weather.enabled:
                session = await stack.enter_async_context(aiohttp.ClientSession())
                provider = create_provider(session, config.weather)
                history_store = store

                async def weather(_ts: int) -> None:
                    sample = await _fetch_weather(provider, history_store)
                    if sample is not None:
                        app.outdoor = sample
                        app.update_air_quality(time.time())

                async def weather_loop() -> None:
                    try:
                        await weather(0)
                    except Exception:  # same protection as in _run_aligned
                        _LOGGER.exception("First weather update failed")
                    await _run_aligned(config.weather.interval_minutes * 60, stop, weather)

                background.append(asyncio.create_task(weather_loop()))

        watchdog = watchdog_interval()
        period = (
            MONITOR_INTERVAL_SECONDS
            if watchdog is None
            else min(MONITOR_INTERVAL_SECONDS, watchdog)
        )
        try:
            while not stop.is_set():
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=period)
                if stop.is_set():
                    break
                now = loop.time()
                app.check_stale(now)
                await supervisor.check(now)
                if not supervisor.healthy:
                    app.bluetooth_down()
                app.update_air_quality(time.time())
                states = [f"STATUS={app.status_line(supervisor)}"]
                if watchdog is not None:
                    states.append("WATCHDOG=1")
                notify(*states)
            events("stopped")
        finally:
            _LOGGER.info("Shutting down")
            notify("STOPPING=1")
            stop.set()
            await asyncio.gather(*background, return_exceptions=True)
