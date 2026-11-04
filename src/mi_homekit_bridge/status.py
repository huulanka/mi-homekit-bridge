"""Live state of the running bridge, for the dashboard and ``/api/health``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .system import SystemHealth


@dataclass(frozen=True, slots=True)
class SensorStatus:
    id: str
    name: str
    reporting: bool
    """A reading arrived within the configured ``stale_after_minutes``."""
    problem: bool
    """Not reporting although it should (it did before, or the bridge runs long enough)."""
    last_seen: int | None
    """Wall-clock time of the last reading, UTC epoch seconds."""
    rssi: int | None


@dataclass(frozen=True, slots=True)
class BridgeStatus:
    version: str
    started_at: int
    bluetooth_state: str
    """``starting``, ``running``, ``recovering`` or ``failed``."""
    bluetooth_since: int
    bluetooth_error: str | None
    scanning_mode: str
    last_advertisement: int | None
    homekit_paired: bool
    homekit_controllers: int
    sensors: tuple[SensorStatus, ...]
    system: SystemHealth | None = None
    """Power supply and CPU temperature of the host, if known."""

    @property
    def problems(self) -> list[str]:
        problems = [] if self.bluetooth_state in ("starting", "running") else ["bluetooth"]
        problems += [f"sensor:{s.id}" for s in self.sensors if s.problem]
        if not self.homekit_paired:
            problems.append("homekit")
        return problems

    def to_json(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "started_at": self.started_at,
            "bluetooth": {
                "state": self.bluetooth_state,
                "since": self.bluetooth_since,
                "error": self.bluetooth_error,
                "scanning_mode": self.scanning_mode,
                "last_advertisement": self.last_advertisement,
            },
            "homekit": {"paired": self.homekit_paired, "controllers": self.homekit_controllers},
            "sensors": [
                {
                    "id": s.id,
                    "name": s.name,
                    "reporting": s.reporting,
                    "problem": s.problem,
                    "last_seen": s.last_seen,
                    "rssi": s.rssi,
                }
                for s in self.sensors
            ],
            "system": None if self.system is None else self.system.to_json(),
            "problems": self.problems,
        }
