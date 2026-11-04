"""HomeKit side: one bridge with one accessory per thermometer."""

from __future__ import annotations

import asyncio
import json
import os
import zlib
from dataclasses import dataclass
from pathlib import Path

from pyhap import util
from pyhap.accessory import Accessory, Bridge
from pyhap.accessory_driver import AccessoryDriver
from pyhap.characteristic import Characteristic
from pyhap.const import CATEGORY_SENSOR

from . import __version__
from .config import BridgeConfig
from .decoder import Reading

LOW_BATTERY_PERCENT = 20

_NO_FAULT = 0
_GENERAL_FAULT = 1
_BATTERY_NORMAL = 0
_BATTERY_LOW = 1
_NOT_CHARGEABLE = 2


def aid_for_mac(mac: str) -> int:
    """Stable HomeKit accessory id derived from the MAC address.

    HomeKit identifies bridged accessories by their ``aid``. Deriving it from the
    MAC keeps rooms and automations intact when sensors are reordered in the config.
    ``aid`` 1 is reserved for the bridge itself.
    """
    return (zlib.crc32(mac.encode()) & 0x7FFFFFFF) | 0x2


class ThermometerAccessory(Accessory):
    """Temperature, humidity and battery of one sensor.

    The battery service is only added once a battery level is known: some sensors
    (e.g. the LYWSD03MMC on recent stock firmware) never broadcast it, and HomeKit
    has no "unknown" value, so it would show 0 % forever.
    """

    category = CATEGORY_SENSOR

    def __init__(
        self, driver: AccessoryDriver, name: str, mac: str, *, battery: bool = False
    ) -> None:
        super().__init__(driver, name, aid=aid_for_mac(mac))
        self.set_info_service(
            firmware_revision=__version__,
            manufacturer="mi-homekit-bridge",
            model="BLE thermometer",
            serial_number=mac,
        )
        temperature = self.add_preload_service("TemperatureSensor", chars=["StatusFault"])
        humidity = self.add_preload_service("HumiditySensor", chars=["StatusFault"])

        self._temperature = temperature.configure_char("CurrentTemperature")
        self._humidity = humidity.configure_char("CurrentRelativeHumidity")
        self._faults = [
            temperature.configure_char("StatusFault", value=_GENERAL_FAULT),
            humidity.configure_char("StatusFault", value=_GENERAL_FAULT),
        ]
        self._battery: tuple[Characteristic, Characteristic] | None = None
        """``(BatteryLevel, StatusLowBattery)`` once the battery service exists."""
        if battery:
            self._battery = self._add_battery_service()

    def _add_battery_service(self) -> tuple[Characteristic, Characteristic]:
        service = self.driver.loader.get_service("BatteryService")
        self.add_service(service)
        service.configure_char("ChargingState", value=_NOT_CHARGEABLE)
        return service.configure_char("BatteryLevel"), service.configure_char("StatusLowBattery")

    def apply(self, reading: Reading) -> bool:
        """Push new values to HomeKit.

        Returns ``True`` if the accessory gained its battery service. While the
        bridge runs, call ``driver.config_changed()`` then, so iOS reloads it.
        """
        if reading.temperature is not None:
            self._temperature.set_value(round(reading.temperature, 1))
        if reading.humidity is not None:
            self._humidity.set_value(round(reading.humidity))
        if reading.battery is None:
            return False
        added = self._battery is None
        if self._battery is None:
            self._battery = self._add_battery_service()
        level_char, low_char = self._battery
        level = max(0, min(100, reading.battery))
        level_char.set_value(level)
        low_char.set_value(_BATTERY_LOW if level < LOW_BATTERY_PERCENT else _BATTERY_NORMAL)
        return added

    def set_fault(self, fault: bool) -> None:
        """Flag the sensor as faulty in HomeKit, e.g. when it stopped reporting."""
        value = _GENERAL_FAULT if fault else _NO_FAULT
        for char in self._faults:
            char.set_value(value)

    @property
    def temperature(self) -> float:
        return float(self._temperature.get_value())

    @property
    def humidity(self) -> float:
        return float(self._humidity.get_value())

    @property
    def battery(self) -> int | None:
        return None if self._battery is None else int(self._battery[0].get_value())

    @property
    def fault(self) -> bool:
        return bool(self._faults[0].get_value() == _GENERAL_FAULT)


@dataclass(frozen=True, slots=True)
class SetupInfo:
    """Pairing code and setup id. HAP-python does not persist these itself."""

    pincode: str
    setup_id: str


def load_or_create_setup(state_dir: Path) -> SetupInfo:
    """Keep the HomeKit setup code stable across restarts."""
    path = state_dir / "setup.json"
    if path.exists():
        data = json.loads(path.read_text())
        return SetupInfo(pincode=data["pincode"], setup_id=data["setup_id"])
    info = SetupInfo(
        pincode=util.generate_pincode().decode(),
        setup_id=util.generate_setup_id(),
    )
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump({"pincode": info.pincode, "setup_id": info.setup_id}, fh)
    return info


def create_driver(
    config: BridgeConfig, state_dir: Path, loop: asyncio.AbstractEventLoop
) -> AccessoryDriver:
    """Create the HAP driver with persistent state in ``state_dir``."""
    state_dir.mkdir(parents=True, exist_ok=True)
    setup = load_or_create_setup(state_dir)
    driver = AccessoryDriver(
        address=config.address,
        port=config.port,
        persist_file=str(state_dir / "accessory.state"),
        pincode=setup.pincode.encode(),
        loop=loop,
    )
    driver.state.setup_id = setup.setup_id
    return driver


def create_bridge(
    driver: AccessoryDriver, config: BridgeConfig, with_battery: frozenset[str] = frozenset()
) -> tuple[Bridge, dict[str, ThermometerAccessory]]:
    """Create the bridge and one accessory per configured sensor, keyed by MAC.

    Sensors in ``with_battery`` (MACs) get their battery service right away.
    """
    bridge = Bridge(driver, config.name)
    bridge.set_info_service(
        firmware_revision=__version__,
        manufacturer="mi-homekit-bridge",
        model="Bridge",
        serial_number=driver.state.mac,
    )
    accessories: dict[str, ThermometerAccessory] = {}
    seen_aids: dict[int, str] = {}
    for sensor in config.sensors:
        accessory = ThermometerAccessory(
            driver, sensor.name, sensor.mac, battery=sensor.mac in with_battery
        )
        if accessory.aid in seen_aids:  # pragma: no cover - 1 in 2^31 chance
            raise ValueError(f"aid collision between {seen_aids[accessory.aid]} and {sensor.mac}")
        seen_aids[accessory.aid] = sensor.mac
        bridge.add_accessory(accessory)
        accessories[sensor.mac] = accessory
    driver.add_accessory(bridge)
    return bridge, accessories
