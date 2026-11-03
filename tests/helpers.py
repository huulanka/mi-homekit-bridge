"""Builders for synthetic BLE advertisements.

All test data is generated here with a throw-away key, so no real device keys or
captured advertisements end up in the repository.
"""

from __future__ import annotations

from bleak.backends.device import BLEDevice
from cryptography.hazmat.primitives.ciphers.aead import AESCCM
from habluetooth import BluetoothServiceInfoBleak

from mi_homekit_bridge.decoder import BTHOME_SERVICE_UUID, XIAOMI_SERVICE_UUID

TEST_MAC = "A4:C1:38:00:00:01"
OTHER_MAC = "A4:C1:38:00:00:02"
# Throw-away keys, generated so that no key-shaped literal lives in the repository.
TEST_BINDKEY = bytes(range(16))
TEST_BINDKEY_HEX = TEST_BINDKEY.hex()
WRONG_BINDKEY = bytes(range(16, 32))

_LYWSD03MMC_PRODUCT_ID = 0x055B
# MiBeacon v5, auth mode 2, object + MAC included, encrypted.
_FRAME_CONTROL_ENCRYPTED = 0x5858
# Same, but registered-only beacon without object (what unpaired sensors send).
_FRAME_CONTROL_NO_OBJECT = 0x5830


def mibeacon_object(object_id: int, value: bytes) -> bytes:
    return object_id.to_bytes(2, "little") + bytes([len(value)]) + value


def temperature_object(celsius: float) -> bytes:
    return mibeacon_object(0x1004, round(celsius * 10).to_bytes(2, "little", signed=True))


def humidity_object(percent: float) -> bytes:
    return mibeacon_object(0x1006, round(percent * 10).to_bytes(2, "little"))


def battery_object(percent: int) -> bytes:
    return mibeacon_object(0x100A, bytes([percent]))


def encrypted_mibeacon(
    obj: bytes, *, mac: str = TEST_MAC, bindkey: bytes = TEST_BINDKEY, counter: int = 1
) -> bytes:
    """MiBeacon v5 frame as sent by a paired LYWSD03MMC on stock firmware."""
    mac_reversed = bytes.fromhex(mac.replace(":", ""))[::-1]
    header = (
        _FRAME_CONTROL_ENCRYPTED.to_bytes(2, "little")
        + _LYWSD03MMC_PRODUCT_ID.to_bytes(2, "little")
        + bytes([counter & 0xFF])
    )
    ext_counter = b"\x00\x00\x00"
    nonce = mac_reversed + header[2:5] + ext_counter
    sealed = AESCCM(bindkey, tag_length=4).encrypt(nonce, obj, b"\x11")
    ciphertext, mic = sealed[:-4], sealed[-4:]
    return header + mac_reversed + ciphertext + ext_counter + mic


def unpaired_mibeacon(mac: str = TEST_MAC) -> bytes:
    mac_reversed = bytes.fromhex(mac.replace(":", ""))[::-1]
    return (
        _FRAME_CONTROL_NO_OBJECT.to_bytes(2, "little")
        + _LYWSD03MMC_PRODUCT_ID.to_bytes(2, "little")
        + b"\x01"
        + mac_reversed
        + b"\x08"
    )


def bthome_plaintext(*, temperature: float, humidity: float, battery: int) -> bytes:
    """BTHome v2 frame as sent by the pvvx custom firmware."""
    return (
        b"\x40"
        + b"\x01"
        + bytes([battery])
        + b"\x02"
        + round(temperature * 100).to_bytes(2, "little", signed=True)
        + b"\x03"
        + round(humidity * 100).to_bytes(2, "little")
    )


def service_info(
    payload: bytes,
    *,
    uuid: str = XIAOMI_SERVICE_UUID,
    address: str = TEST_MAC,
    time: float = 0.0,
    rssi: int = -60,
) -> BluetoothServiceInfoBleak:
    return BluetoothServiceInfoBleak(
        name="LYWSD03MMC",
        address=address,
        rssi=rssi,
        manufacturer_data={},
        service_data={uuid: payload},
        service_uuids=[uuid],
        source="local",
        device=BLEDevice(address, "LYWSD03MMC", None),
        advertisement=None,
        connectable=True,
        time=time,
        tx_power=None,
    )


def bthome_info(
    payload: bytes, *, address: str = TEST_MAC, time: float = 0.0
) -> BluetoothServiceInfoBleak:
    return service_info(payload, uuid=BTHOME_SERVICE_UUID, address=address, time=time)
