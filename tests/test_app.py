import asyncio
import stat
from dataclasses import replace
from pathlib import Path

import pytest
from pyhap.accessory_driver import AccessoryDriver

from mi_homekit_bridge.app import WEATHER_SENSOR_ID, BridgeApp, _fetch_weather
from mi_homekit_bridge.config import BridgeConfig, SensorConfig, WeatherConfig
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


async def test_stale_sensor_is_flagged_and_recovers(driver: AccessoryDriver) -> None:
    app = BridgeApp(CONFIG, driver)
    accessory = app.channels[TEST_MAC].accessory
    app.handle_advertisement(service_info(encrypted_mibeacon(temperature_object(21.0))), now=0.0)

    assert not app.check_stale(now=9 * 60)
    assert not accessory.fault
    assert app.check_stale(now=10 * 60)  # other sensor never reported -> all stale
    assert accessory.fault

    frame = encrypted_mibeacon(temperature_object(21.5), counter=2)
    app.handle_advertisement(service_info(frame), now=11 * 60)
    assert not accessory.fault
    assert not app.check_stale(now=11 * 60)


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


async def test_samples_contain_only_reporting_sensors(driver: AccessoryDriver) -> None:
    app = BridgeApp(CONFIG, driver)
    assert app.samples(300) == []

    app.handle_advertisement(service_info(encrypted_mibeacon(temperature_object(21.4))), now=1.0)
    frame = encrypted_mibeacon(battery_object(80), counter=2)
    app.handle_advertisement(service_info(frame), now=2.0)

    (sample,) = app.samples(300)
    assert (sample.sensor_id, sample.ts, sample.humidity, sample.battery) == (
        TEST_MAC,
        300,
        None,
        80,
    )
    assert sample.temperature == pytest.approx(21.4)


async def test_restore_shows_last_values_but_keeps_fault(driver: AccessoryDriver) -> None:
    app = BridgeApp(CONFIG, driver)
    app.restore(
        {TEST_MAC: Sample(TEST_MAC, 100, 19.5, 55.0, 64), "AA:BB:CC:DD:EE:FF": Sample("x", 1)}
    )

    accessory = app.channels[TEST_MAC].accessory
    assert accessory.temperature == pytest.approx(19.5)
    assert accessory.battery == 64
    assert accessory.fault
    assert app.samples(400) == []  # restored values are not recorded again


async def test_sensor_infos_include_weather(driver: AccessoryDriver) -> None:
    config = replace(
        CONFIG, weather=WeatherConfig(enabled=True, name="Outdoor", latitude=1, longitude=1)
    )
    infos = BridgeApp(config, driver).sensor_infos()
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
