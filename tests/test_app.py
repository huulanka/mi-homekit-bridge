import asyncio
import stat
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from pyhap.accessory_driver import AccessoryDriver

from mi_homekit_bridge.app import (
    WEATHER_SENSOR_ID,
    BridgeApp,
    EventLog,
    Recorder,
    ScannerFactory,
    _fetch_weather,
    sensor_infos,
)
from mi_homekit_bridge.bluetooth import ScanState, ScanSupervisor
from mi_homekit_bridge.config import BluetoothConfig, BridgeConfig, SensorConfig, WeatherConfig
from mi_homekit_bridge.history import HistoryStore, Sample, SensorInfo
from mi_homekit_bridge.homekit import aid_for_mac, create_driver, load_or_create_setup
from mi_homekit_bridge.weather import Observation, WeatherError

from .helpers import (
    OTHER_MAC,
    TEST_BINDKEY,
    TEST_MAC,
    battery_object,
    encrypted_mibeacon,
    service_info,
    temperature_object,
)

CONFIG = BridgeConfig(
    name="Test Bridge",
    address="127.0.0.1",
    stale_after_minutes=10,
    sensors=(
        SensorConfig(name="Living Room", mac=TEST_MAC, bindkey=TEST_BINDKEY),
        SensorConfig(name="Bedroom", mac=OTHER_MAC, bindkey=TEST_BINDKEY),
    ),
)


@pytest.fixture
async def driver(tmp_path: Path) -> AccessoryDriver:
    return create_driver(CONFIG, tmp_path, asyncio.get_running_loop())


async def test_advertisement_updates_accessory(driver: AccessoryDriver) -> None:
    app = BridgeApp(CONFIG, driver)
    accessory = app.channels[TEST_MAC].accessory
    assert accessory.fault  # no data yet

    app.handle_advertisement(service_info(encrypted_mibeacon(temperature_object(21.4))), now=1.0)
    frame = encrypted_mibeacon(battery_object(15), counter=2)
    app.handle_advertisement(service_info(frame), now=2.0)

    assert accessory.temperature == pytest.approx(21.4)
    assert accessory.battery == 15
    assert not accessory.fault
    assert app.channels[OTHER_MAC].accessory.fault  # untouched


async def test_address_is_matched_case_insensitively(driver: AccessoryDriver) -> None:
    app = BridgeApp(CONFIG, driver)
    info = service_info(encrypted_mibeacon(temperature_object(19.0)), address=TEST_MAC.lower())
    app.handle_advertisement(info, now=1.0)
    assert app.channels[TEST_MAC].accessory.temperature == pytest.approx(19.0)


async def test_unknown_sensor_is_ignored(driver: AccessoryDriver) -> None:
    app = BridgeApp(CONFIG, driver)
    stranger = "A4:C1:38:99:99:99"
    frame = encrypted_mibeacon(temperature_object(30.0), mac=stranger)
    app.handle_advertisement(service_info(frame, address=stranger), now=1.0)
    assert all(channel.last_seen is None for channel in app.channels.values())


@pytest.fixture
def store(tmp_path: Path) -> Iterator[HistoryStore]:
    db = HistoryStore(tmp_path / "h.db")
    db.upsert_sensors(sensor_infos(CONFIG))
    yield db
    db.close()


async def test_stale_sensor_is_flagged_and_recovers(
    driver: AccessoryDriver, store: HistoryStore
) -> None:
    app = BridgeApp(CONFIG, driver, events=EventLog(store, clock=lambda: 5000))
    accessory = app.channels[TEST_MAC].accessory
    app.handle_advertisement(service_info(encrypted_mibeacon(temperature_object(21.0))), now=0.0)

    app.check_stale(now=9 * 60)
    assert not accessory.fault
    app.check_stale(now=10 * 60)
    assert accessory.fault

    frame = encrypted_mibeacon(temperature_object(21.5), counter=2)
    app.handle_advertisement(service_info(frame), now=25 * 60)
    assert not accessory.fault
    assert [(e.kind, e.sensor_id, dict(e.data)) for e in store.events()] == [
        ("sensor_back", TEST_MAC, {"minutes": 25}),
        ("sensor_lost", TEST_MAC, {"minutes": 10}),
    ]


async def test_bluetooth_down_flags_all_sensors_until_they_report(
    driver: AccessoryDriver, store: HistoryStore
) -> None:
    app = BridgeApp(CONFIG, driver, events=EventLog(store))
    app.handle_advertisement(service_info(encrypted_mibeacon(temperature_object(21.0))), now=0.0)
    app.bluetooth_down()
    assert app.channels[TEST_MAC].accessory.fault
    assert app.samples(300, now=60.0) == []

    frame = encrypted_mibeacon(temperature_object(21.5), counter=2)
    app.handle_advertisement(service_info(frame), now=120.0)
    assert not app.channels[TEST_MAC].accessory.fault
    assert store.events() == []  # covered by the Bluetooth events, not per sensor


async def test_accessory_ids_are_stable(driver: AccessoryDriver) -> None:
    app = BridgeApp(CONFIG, driver)
    aids = {mac: channel.accessory.aid for mac, channel in app.channels.items()}
    assert aids == {TEST_MAC: aid_for_mac(TEST_MAC), OTHER_MAC: aid_for_mac(OTHER_MAC)}
    assert all(aid >= 2 for aid in aids.values())
    assert driver.accessory.aid == 1


def test_setup_code_is_persisted(tmp_path: Path) -> None:
    first = load_or_create_setup(tmp_path)
    second = load_or_create_setup(tmp_path)
    assert first == second
    assert len(first.pincode) == 10
    assert stat.S_IMODE((tmp_path / "setup.json").stat().st_mode) == 0o600


async def test_driver_reuses_setup_code(tmp_path: Path) -> None:
    loop = asyncio.get_running_loop()
    first = create_driver(CONFIG, tmp_path, loop)
    second = create_driver(CONFIG, tmp_path, loop)
    assert first.state.pincode == second.state.pincode
    assert first.state.setup_id == second.state.setup_id


async def test_samples_contain_only_reporting_sensors(
    driver: AccessoryDriver, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(driver, "config_changed", lambda: None)
    app = BridgeApp(CONFIG, driver)
    assert app.samples(300, now=3.0) == []

    app.handle_advertisement(service_info(encrypted_mibeacon(temperature_object(21.4))), now=1.0)
    frame = encrypted_mibeacon(battery_object(80), counter=2)
    app.handle_advertisement(service_info(frame), now=2.0)

    (sample,) = app.samples(300, now=3.0)
    assert (sample.sensor_id, sample.ts, sample.humidity, sample.battery) == (
        TEST_MAC,
        300,
        None,
        80,
    )
    assert sample.temperature == pytest.approx(21.4)


async def test_silent_sensor_is_not_recorded_with_its_last_value(driver: AccessoryDriver) -> None:
    """Regression: on 2026-11-04 a frozen value was recorded for an hour."""
    app = BridgeApp(CONFIG, driver)  # history interval 5 minutes
    app.handle_advertisement(service_info(encrypted_mibeacon(temperature_object(23.6))), now=0.0)
    assert len(app.samples(300, now=299.0)) == 1
    assert app.samples(600, now=301.0) == []  # still within stale_after, but not fresh


async def test_battery_service_appears_with_the_first_battery_level(
    driver: AccessoryDriver, monkeypatch: pytest.MonkeyPatch
) -> None:
    changes: list[None] = []
    monkeypatch.setattr(driver, "config_changed", lambda: changes.append(None))
    app = BridgeApp(CONFIG, driver)
    accessory = app.channels[TEST_MAC].accessory
    app.handle_advertisement(service_info(encrypted_mibeacon(temperature_object(21.0))), now=1.0)
    assert accessory.battery is None  # not 0 %
    services = {s.display_name for s in accessory.services}
    assert "BatteryService" not in services

    app.handle_advertisement(service_info(encrypted_mibeacon(battery_object(77), counter=2)), 2.0)
    assert accessory.battery == 77
    assert "BatteryService" in {s.display_name for s in accessory.services}
    assert len(changes) == 1  # iOS is told to reload the accessory

    app.handle_advertisement(service_info(encrypted_mibeacon(battery_object(76), counter=3)), 3.0)
    assert len(changes) == 1


async def test_known_battery_creates_service_right_away(driver: AccessoryDriver) -> None:
    app = BridgeApp(CONFIG, driver, with_battery=frozenset({TEST_MAC}))
    assert app.channels[TEST_MAC].accessory.battery == 0
    assert app.channels[OTHER_MAC].accessory.battery is None


async def test_restore_shows_last_values_but_keeps_fault(driver: AccessoryDriver) -> None:
    app = BridgeApp(CONFIG, driver)
    app.restore(
        {TEST_MAC: Sample(TEST_MAC, 100, 19.5, 55.0, 64), "AA:BB:CC:DD:EE:FF": Sample("x", 1)}
    )

    accessory = app.channels[TEST_MAC].accessory
    assert accessory.temperature == pytest.approx(19.5)
    assert accessory.battery == 64
    assert accessory.fault
    assert app.samples(400, now=1.0) == []  # restored values are not recorded again


def test_sensor_infos_include_weather() -> None:
    config = replace(
        CONFIG, weather=WeatherConfig(enabled=True, name="Outdoor", latitude=1, longitude=1)
    )
    infos = sensor_infos(config)
    assert [(i.id, i.kind) for i in infos] == [
        (TEST_MAC, "ble"),
        (OTHER_MAC, "ble"),
        (WEATHER_SENSOR_ID, "weather"),
    ]


class FakeProvider:
    def __init__(self, result: Observation | WeatherError) -> None:
        self._result = result

    async def current(self) -> Observation:
        if isinstance(self._result, WeatherError):
            raise self._result
        return self._result


async def test_fetch_weather_stores_observation(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "h.db")
    store.upsert_sensors([SensorInfo(WEATHER_SENSOR_ID, "Outdoor", "weather")])

    await _fetch_weather(FakeProvider(Observation(900, 4.5, 80.0)), store)
    await _fetch_weather(FakeProvider(WeatherError("offline")), store)  # logged, not raised

    assert store.latest(WEATHER_SENSOR_ID) == Sample(WEATHER_SENSOR_ID, 900, 4.5, 80.0, None)
    store.close()


async def test_status(driver: AccessoryDriver) -> None:
    app = BridgeApp(CONFIG, driver)
    supervisor = ScanSupervisor(lambda: None)  # type: ignore[arg-type, return-value]
    supervisor.state, supervisor.since = ScanState.RUNNING, 10.0
    supervisor.last_advertisement = 95.0
    info = service_info(encrypted_mibeacon(temperature_object(21.0)), rssi=-71)
    app.handle_advertisement(info, now=90.0)

    status = app.status(supervisor, scanning_mode="active", started=0.0, now=100.0, wall=10_000.0)
    assert status.started_at == 9900
    assert (status.bluetooth_state, status.bluetooth_since) == ("running", 9910)
    assert status.last_advertisement == 9995
    assert not status.homekit_paired
    living, bedroom = status.sensors
    assert (living.reporting, living.problem, living.last_seen, living.rssi) == (
        True,
        False,
        9990,
        -71,
    )
    # Bedroom never reported, but the bridge only runs for 100 s: no problem yet.
    assert (bedroom.reporting, bedroom.problem) == (False, False)
    assert status.problems == ["homekit"]

    later = app.status(supervisor, scanning_mode="active", started=0.0, now=700.0, wall=10_600.0)
    assert "sensor:" + OTHER_MAC in later.problems
    assert app.status_line(supervisor) == "Bluetooth running, 1/2 sensors reporting"


async def test_recorder_waits_for_clock_sync(driver: AccessoryDriver, store: HistoryStore) -> None:
    app = BridgeApp(CONFIG, driver)
    app.handle_advertisement(service_info(encrypted_mibeacon(temperature_object(21.0))), now=0.0)
    synced = False
    recorder = Recorder(app, store, monotonic=lambda: 10.0, clock_ok=lambda: synced)

    await recorder(300)
    assert store.latest(TEST_MAC) is None
    synced = True
    await recorder(600)
    latest = store.latest(TEST_MAC)
    assert latest is not None
    assert latest.ts == 600


def test_scanner_factory_falls_back_from_passive_once(store: HistoryStore) -> None:
    factory = ScannerFactory(
        lambda _info: None, BluetoothConfig(scanning_mode="passive"), EventLog(store)
    )
    assert factory.fall_back("nothing was received since the start")
    assert factory.mode == "active"
    assert not factory.fall_back("again")
    (event,) = store.events()
    assert (event.kind, dict(event.data)) == (
        "passive_unavailable",
        {"reason": "nothing was received since the start"},
    )


def test_scanner_factory_never_falls_back_from_active(store: HistoryStore) -> None:
    factory = ScannerFactory(lambda _info: None, BluetoothConfig(), EventLog(store))
    assert not factory.fall_back("whatever")
    assert store.events() == []
