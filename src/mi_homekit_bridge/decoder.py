"""Turn raw BLE advertisements into sensor readings.

The actual parsing and decryption is done by ``xiaomi-ble`` and ``bthome-ble``,
the same libraries Home Assistant uses. This module only picks the right parser
and reduces its output to the three values HomeKit cares about.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from bthome_ble import BTHomeBluetoothDeviceData
from habluetooth import BluetoothServiceInfoBleak
from sensor_state_data import SensorUpdate, SensorValue
from xiaomi_ble import XiaomiBluetoothDeviceData

_LOGGER = logging.getLogger(__name__)

_WANTED_KEYS = ("temperature", "humidity", "battery")

XIAOMI_SERVICE_UUID = "0000fe95-0000-1000-8000-00805f9b34fb"
BTHOME_SERVICE_UUID = "0000fcd2-0000-1000-8000-00805f9b34fb"


@dataclass(frozen=True, slots=True)
class Reading:
    """Values decoded from one advertisement. Missing values are ``None``."""

    temperature: float | None = None
    humidity: float | None = None
    battery: int | None = None

    @property
    def is_empty(self) -> bool:
        return self.temperature is None and self.humidity is None and self.battery is None


class SensorDecoder:
    """Stateful decoder for one physical sensor."""

    def __init__(self, bindkey: bytes | None = None) -> None:
        self._has_bindkey = bindkey is not None
        self._xiaomi = XiaomiBluetoothDeviceData(bindkey=bindkey)
        self._bthome = BTHomeBluetoothDeviceData(bindkey=bindkey)
        self._warned_missing_key = False
        self._warned_plaintext = False
        self._seen: dict[str, SensorValue] = {}

    def decode(self, service_info: BluetoothServiceInfoBleak) -> Reading | None:
        """Return the reading in ``service_info`` or ``None`` if it carries none."""
        if XIAOMI_SERVICE_UUID in service_info.service_data:
            update = self._xiaomi.update(service_info)
            encrypted = _mibeacon_is_encrypted(service_info.service_data[XIAOMI_SERVICE_UUID])
        elif BTHOME_SERVICE_UUID in service_info.service_data:
            encrypted = _bthome_is_encrypted(service_info.service_data[BTHOME_SERVICE_UUID])
            if self._has_bindkey and not encrypted:
                # bthome-ble drops plaintext data once a key is known (downgrade
                # protection) and warns about every single advertisement.
                if not self._warned_plaintext:
                    self._warned_plaintext = True
                    _LOGGER.warning(
                        "%s sends unencrypted BTHome data but a bindkey is configured, "
                        "so its data is ignored. After flashing custom firmware without "
                        "encryption, remove its bindkey from the environment.",
                        service_info.address,
                    )
                return None
            update = self._bthome.update(service_info)
        else:
            return None

        if encrypted and not self._has_bindkey and not self._warned_missing_key:
            self._warned_missing_key = True
            _LOGGER.warning(
                "%s sends encrypted data but no bindkey is configured "
                "(run 'mi-homekit-bridge fetch-keys')",
                service_info.address,
            )

        reading = self._fresh_reading(update)
        return None if reading.is_empty else reading

    def _fresh_reading(self, update: SensorUpdate) -> Reading:
        """Values that were decoded from *this* advertisement.

        The parsers return every value they have ever seen with each update. They
        create a new ``SensorValue`` whenever a value is decoded, so object identity
        tells fresh values apart from repeated old ones.
        """
        fresh: dict[str, float] = {}
        for sensor_value in update.entity_values.values():
            key = sensor_value.device_key.key
            native = sensor_value.native_value
            if key not in _WANTED_KEYS or self._seen.get(key) is sensor_value:
                continue
            self._seen[key] = sensor_value
            if isinstance(native, int | float):
                fresh[key] = float(native)
        battery = fresh.get("battery")
        return Reading(
            temperature=fresh.get("temperature"),
            humidity=fresh.get("humidity"),
            battery=round(battery) if battery is not None else None,
        )


def _mibeacon_is_encrypted(payload: bytes) -> bool:
    # Frame control, little endian: bit 3 = "is encrypted".
    return len(payload) >= 1 and bool(payload[0] & 0x08)


def _bthome_is_encrypted(payload: bytes) -> bool:
    # Device information byte: bit 0 = "encryption flag".
    return len(payload) >= 1 and bool(payload[0] & 0x01)


def describe_format(service_data: dict[str, bytes]) -> str | None:
    """Human readable advertisement format, used by the ``scan`` command."""
    if XIAOMI_SERVICE_UUID in service_data:
        payload = service_data[XIAOMI_SERVICE_UUID]
        has_data = len(payload) >= 1 and bool(payload[0] & 0x40)
        if not has_data:
            return "Xiaomi MiBeacon (no measurements - pair it in the Mi Home app)"
        if _mibeacon_is_encrypted(payload):
            return "Xiaomi MiBeacon (encrypted, needs bindkey)"
        return "Xiaomi MiBeacon (plaintext)"
    if BTHOME_SERVICE_UUID in service_data:
        if _bthome_is_encrypted(service_data[BTHOME_SERVICE_UUID]):
            return "BTHome v2 (encrypted, needs bindkey)"
        return "BTHome v2 (plaintext)"
    return None
