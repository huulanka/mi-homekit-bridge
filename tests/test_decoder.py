import logging

import pytest

from mi_homekit_bridge.decoder import Reading, SensorDecoder, describe_format

from .helpers import (
    TEST_BINDKEY,
    WRONG_BINDKEY,
    battery_object,
    bthome_info,
    bthome_plaintext,
    encrypted_mibeacon,
    humidity_object,
    service_info,
    temperature_object,
    unpaired_mibeacon,
)


def test_decrypts_temperature() -> None:
    decoder = SensorDecoder(TEST_BINDKEY)
    reading = decoder.decode(service_info(encrypted_mibeacon(temperature_object(21.4))))
    assert reading is not None
    assert reading.temperature == pytest.approx(21.4)
    assert reading.humidity is None
    assert reading.battery is None


def test_decrypts_negative_temperature() -> None:
    decoder = SensorDecoder(TEST_BINDKEY)
    reading = decoder.decode(service_info(encrypted_mibeacon(temperature_object(-3.5))))
    assert reading is not None
    assert reading.temperature == pytest.approx(-3.5)


def test_decrypts_humidity_and_battery_from_consecutive_frames() -> None:
    decoder = SensorDecoder(TEST_BINDKEY)
    humidity = decoder.decode(service_info(encrypted_mibeacon(humidity_object(48.7), counter=1)))
    battery = decoder.decode(service_info(encrypted_mibeacon(battery_object(87), counter=2)))
    # xiaomi-ble truncates LYWSD03MMC humidity to whole percent (sensor resolution).
    assert humidity == Reading(humidity=48.0)
    assert battery == Reading(battery=87)


def test_old_values_are_not_repeated() -> None:
    decoder = SensorDecoder(TEST_BINDKEY)
    frame = encrypted_mibeacon(temperature_object(21.4), counter=1)
    assert decoder.decode(service_info(frame)) is not None
    # A frame that cannot be decrypted must not look like a fresh reading.
    garbage = encrypted_mibeacon(temperature_object(30.0), bindkey=WRONG_BINDKEY, counter=2)
    assert decoder.decode(service_info(garbage)) is None


def test_wrong_bindkey_yields_nothing() -> None:
    decoder = SensorDecoder(WRONG_BINDKEY)
    assert decoder.decode(service_info(encrypted_mibeacon(temperature_object(21.4)))) is None


def test_missing_bindkey_warns_once(caplog: pytest.LogCaptureFixture) -> None:
    decoder = SensorDecoder(None)
    with caplog.at_level(logging.WARNING, logger="mi_homekit_bridge.decoder"):
        for counter in (1, 2):
            frame = encrypted_mibeacon(temperature_object(21.4), counter=counter)
            assert decoder.decode(service_info(frame)) is None
    warnings = [r for r in caplog.records if r.name == "mi_homekit_bridge.decoder"]
    assert len(warnings) == 1
    assert "fetch-keys" in warnings[0].getMessage()


def test_unpaired_beacon_has_no_reading() -> None:
    assert SensorDecoder(TEST_BINDKEY).decode(service_info(unpaired_mibeacon())) is None


def test_bthome_plaintext() -> None:
    decoder = SensorDecoder(None)
    frame = bthome_plaintext(temperature=22.5, humidity=50.55, battery=93)
    reading = decoder.decode(bthome_info(frame))
    assert reading is not None
    assert reading.temperature == pytest.approx(22.5)
    assert reading.humidity == pytest.approx(50.55)
    assert reading.battery == 93


def test_unrelated_service_data_is_ignored() -> None:
    info = service_info(b"\x01\x02", uuid="0000180f-0000-1000-8000-00805f9b34fb")
    assert SensorDecoder(None).decode(info) is None


@pytest.mark.parametrize(
    ("service_data", "expected"),
    [
        ({"0000fe95-0000-1000-8000-00805f9b34fb": unpaired_mibeacon()}, "pair it"),
        (
            {"0000fe95-0000-1000-8000-00805f9b34fb": encrypted_mibeacon(temperature_object(1))},
            "encrypted",
        ),
        (
            {
                "0000fcd2-0000-1000-8000-00805f9b34fb": bthome_plaintext(
                    temperature=1, humidity=1, battery=1
                )
            },
            "BTHome v2 (plaintext)",
        ),
    ],
)
def test_describe_format(service_data: dict[str, bytes], expected: str) -> None:
    description = describe_format(service_data)
    assert description is not None
    assert expected in description


def test_describe_format_unknown() -> None:
    assert describe_format({"0000180f-0000-1000-8000-00805f9b34fb": b"\x00"}) is None
