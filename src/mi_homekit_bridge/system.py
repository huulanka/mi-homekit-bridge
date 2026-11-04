"""Health of the machine the bridge runs on: power supply and CPU temperature.

On a Raspberry Pi the firmware reports under-voltage through the ``rpi_volt``
hwmon device (``in0_lcrit_alarm``). A weak power supply is a common cause of
Bluetooth and Wi-Fi trouble, so it is worth showing. Elsewhere the values are
simply unknown.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

_LOGGER = logging.getLogger(__name__)

POLL_SECONDS = 5.0
"""The alarm is not latched: poll often enough to catch short dips."""
EVENT_COOLDOWN_SECONDS = 600
"""At most one under-voltage event per ten minutes, however often it flickers."""

EventSink = Callable[..., None]


@dataclass(frozen=True, slots=True)
class SystemHealth:
    cpu_temperature: float | None
    """°C, ``None`` if unknown."""
    undervoltage: bool | None
    """Under-voltage right now; ``None`` if this is not a Raspberry Pi."""
    undervoltage_count: int
    """How often under-voltage started since the bridge started."""
    last_undervoltage: int | None
    """Wall-clock time of the last under-voltage, UTC epoch seconds."""

    def to_json(self) -> dict[str, object]:
        return {
            "cpu_temperature": self.cpu_temperature,
            "undervoltage": self.undervoltage,
            "undervoltage_count": self.undervoltage_count,
            "last_undervoltage": self.last_undervoltage,
        }


def _read(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return path.read_text().strip()
    except OSError:
        return None


def find_undervoltage_alarm(sys_root: Path) -> Path | None:
    """The ``in0_lcrit_alarm`` file of the ``rpi_volt`` hwmon device, if any."""
    for hwmon in sorted((sys_root / "class" / "hwmon").glob("hwmon*")):
        if _read(hwmon / "name") == "rpi_volt" and (hwmon / "in0_lcrit_alarm").is_file():
            return hwmon / "in0_lcrit_alarm"
    return None


class SystemMonitor:
    """Polls the under-voltage alarm and reads the CPU temperature."""

    def __init__(
        self,
        *,
        sys_root: Path = Path("/sys"),
        events: EventSink | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._alarm = find_undervoltage_alarm(sys_root)
        self._thermal = sys_root / "class" / "thermal" / "thermal_zone0" / "temp"
        self._events = events
        self._clock = clock
        self._active = False
        self._count = 0
        self._last: int | None = None
        self._last_event: float | None = None

    @property
    def available(self) -> bool:
        return self._alarm is not None or self._thermal.is_file()

    def poll(self) -> None:
        raw = _read(self._alarm)
        if raw is None:
            return
        active = raw == "1"
        if active and not self._active:
            now = self._clock()
            self._count += 1
            self._last = round(now)
            _LOGGER.warning("Under-voltage detected: check the power supply")
            if self._events is not None and (
                self._last_event is None or now - self._last_event >= EVENT_COOLDOWN_SECONDS
            ):
                self._events("undervoltage", count=self._count)
                self._last_event = now
        self._active = active

    def health(self) -> SystemHealth:
        raw = _read(self._thermal)
        try:
            temperature = round(int(raw) / 1000, 1) if raw is not None else None
        except ValueError:
            temperature = None
        return SystemHealth(
            cpu_temperature=temperature,
            undervoltage=None if self._alarm is None else self._active,
            undervoltage_count=self._count,
            last_undervoltage=self._last,
        )
