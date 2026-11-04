import pytest

from mi_homekit_bridge import climate


def test_absolute_humidity_makes_indoor_and_outdoor_comparable() -> None:
    # Measured on 2026-11-04: the bedroom holds more than twice the water of the
    # outdoor air, although its relative humidity is lower.
    assert climate.absolute_humidity(22.2, 61) == pytest.approx(11.9, abs=0.05)
    assert climate.absolute_humidity(5.6, 71) == pytest.approx(5.0, abs=0.05)
    assert climate.absolute_humidity(None, 50) is None
    assert climate.water_content(20.0, 100) == pytest.approx(17.3, abs=0.1)  # table value


def test_dew_point() -> None:
    assert climate.dew_point(22.2, 61) == pytest.approx(14.3, abs=0.05)
    assert climate.dew_point(20.0, 0) is None


@pytest.mark.parametrize(
    ("factor", "expected"),
    [(0.7, 83), (0.8, 75), (0.6, 92)],
)
def test_surface_humidity_depends_on_the_wall(factor: float, expected: float) -> None:
    assert climate.surface_humidity(22.2, 61, 5.6, factor) == pytest.approx(expected, abs=1)


def test_cooler_room_with_the_same_water_is_damper() -> None:
    water = climate.water_content(22.2, 61)
    at_18 = water * (273.15 + 18) / 216.7 / climate.saturation_pressure(18) * 100
    assert at_18 == pytest.approx(78, abs=1)
    assert climate.surface_humidity(18.0, at_18, 5.6, 0.8) == pytest.approx(91, abs=1)


def test_surface_is_not_colder_than_the_room_in_summer() -> None:
    assert climate.surface_humidity(24.0, 55, 30.0) == pytest.approx(55)
    assert climate.surface_humidity(24.0, 55, None) is None
    assert climate.surface_humidity(22.0, 99, -20.0) == 100.0


def test_levels() -> None:
    assert [climate.mould_level(v) for v in (69.9, 70, 80)] == ["good", "warning", "critical"]
    assert [climate.room_level(v) for v in (59, 60, 70)] == ["good", "warning", "critical"]


def test_assess_recommends_airing_when_damp_and_drier_outside() -> None:
    air = climate.assess(22.2, 61, 5.6, 71, 0.8)
    assert (air.level, air.basis) == ("warning", "surface")
    assert (air.ventilation, air.minutes) == ("recommended", 10)
    assert air.surface_humidity == pytest.approx(75, abs=1)


def test_assess_advises_against_airing_into_humid_air() -> None:
    air = climate.assess(24.0, 75, 26.0, 70)
    assert (air.level, air.ventilation, air.minutes) == ("warning", "avoid", None)


def test_assess_without_outdoor_data_uses_the_room() -> None:
    air = climate.assess(21.0, 65, None, None)
    assert (air.level, air.basis, air.ventilation) == ("warning", "room", None)
    assert climate.assess(21.0, 45, 5.0, 80).ventilation == "not_needed"
    assert climate.assess(None, None, None, None).level is None


def test_airing_minutes_and_heating_degrees() -> None:
    assert [climate.airing_minutes(t) for t in (-3, 7, 12, 17, 25)] == [5, 10, 15, 20, 25]
    assert climate.heating_degrees(5.0) == 15.0
    assert climate.heating_degrees(15.0) == 0.0


def test_air_quality() -> None:
    assert [climate.air_quality(v) for v in (None, 55, 65, 75, 85, 95)] == [0, 1, 2, 3, 4, 5]
