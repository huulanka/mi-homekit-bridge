"""Keep the Bluetooth scan alive.

A Bluetooth controller can stop working while the bridge runs. On a Raspberry Pi 3
the built-in BCM43438 occasionally stops answering HCI commands after hours of
scanning; BlueZ then refuses every new scan with ``org.bluez.Error.InProgress``.
Restarting the scan does not help in that state, only resetting the controller does.

:class:`ScanSupervisor` handles this in three steps:

1. If no advertisement at all arrives for a while, the scan is restarted.
2. If starting the scan fails, it is retried with increasing delays. HomeKit and
   the dashboard keep running meanwhile.
3. If that does not help, it raises :class:`ControllerResetRequired`. The bridge
   then exits with :data:`EXIT_CONTROLLER_RESET`, and the systemd unit resets the
   controller as root (``mi-homekit-bridge reset-bluetooth``) before it is
   restarted. At most one reset is requested per :attr:`Timings.reset_cooldown`;
   in between the supervisor keeps retrying on its own.

If nothing has been received at all since the start, a ``fallback`` gets the chance
to change the configuration first (passive scanning may start fine on systems
that do not support it, and then deliver nothing): a reset cannot fix that.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from bleak.exc import BleakError

_LOGGER = logging.getLogger(__name__)

EXIT_CONTROLLER_RESET = 75
"""Exit status asking the systemd unit to reset the Bluetooth controller (EX_TEMPFAIL)."""

RESET_MARKER = "bluetooth-reset.json"


class ScanState(StrEnum):
    STARTING = "starting"
    RUNNING = "running"
    RECOVERING = "recovering"
    """Starting the scan failed or nothing is received; retrying."""
    FAILED = "failed"
    """Retrying did not help and a controller reset is not possible right now."""


class ControllerResetRequired(Exception):
    """The Bluetooth controller needs a reset; exit with :data:`EXIT_CONTROLLER_RESET`."""


class Scanner(Protocol):
    async def start(self) -> None: ...

    async def stop(self) -> None: ...


@dataclass(frozen=True, slots=True)
class Timings:
    start_timeout: float = 20.0
    """A scan start (or stop) that takes longer than this counts as failed."""
    silence: float = 300.0
    """No advertisement from any device for this long means the scan is dead."""
    confirm: float = 60.0
    """After a restart, an advertisement has to arrive within this time."""
    first_advertisement: float = 120.0
    """After the very first start, an advertisement has to arrive within this time
    (longer than ``confirm``: right after a controller reset bluetoothd needs a
    while to set the adapter up)."""
    retry_delays: tuple[float, ...] = (10.0, 30.0, 60.0, 120.0, 300.0)
    """Delays between attempts while recovering; the last one repeats."""
    escalate_after: int = 3
    """Failed attempts in a row before a controller reset is requested."""
    reset_cooldown: float = 1800.0
    """Minimum time between two controller resets."""


DEFAULT_TIMINGS = Timings()

Listener = Callable[[str, dict[str, object]], None]
"""Called with an event kind and its parameters, e.g. to record it in the history."""

Fallback = Callable[[str], bool]
"""Called with the reason when nothing works since the start. Returns ``True`` if it
changed how scanners are created (e.g. passive -> active), so trying again makes
sense right away."""


class ScanSupervisor:
    """Starts the scan, watches that advertisements arrive and recovers if not.

    A scan only counts as recovered once an advertisement arrives, not when
    starting it succeeds. All times are monotonic (``loop.time()``), except the
    reset marker, which has to survive a restart and stores wall-clock time.
    """

    def __init__(
        self,
        factory: Callable[[], Scanner],
        *,
        state_dir: Path | None = None,
        timings: Timings = DEFAULT_TIMINGS,
        listener: Listener | None = None,
        fallback: Fallback | None = None,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self._factory = factory
        self._fallback = fallback
        self._timings = timings
        self._marker = state_dir / RESET_MARKER if state_dir is not None else None
        self._listener = listener
        self._wall_clock = wall_clock
        self._scanner: Scanner | None = None
        self.state = ScanState.STARTING
        self.since = 0.0
        """When the current state was entered."""
        self.last_advertisement: float | None = None
        self.last_error: str | None = None
        self._failures = 0
        """Unsuccessful attempts in a row (start failed, or started but silent)."""
        self._started_at = 0.0
        self._trouble_since = 0.0
        self._next_attempt = 0.0

    @property
    def healthy(self) -> bool:
        return self.state is ScanState.RUNNING

    # -- inputs ----------------------------------------------------------------

    def advertisement_seen(self, now: float) -> None:
        """Call for every advertisement received, from any device."""
        self.last_advertisement = now
        if self.state is ScanState.RUNNING:
            return
        if self.state is not ScanState.STARTING:
            seconds = round(now - self._trouble_since)
            _LOGGER.info("Bluetooth is receiving again after %d seconds", seconds)
            self._emit("scan_recovered", seconds=seconds)
        self._failures = 0
        self.last_error = None
        self._set_state(ScanState.RUNNING, now)

    async def start(self, now: float) -> None:
        """Start scanning. Failures are not raised but retried by :meth:`check`."""
        self.since = self._trouble_since = now
        if await self._try_start(now) or await self._fallback_start(now):
            self._set_state(ScanState.RUNNING, now)
        else:
            self._failed_attempt(now, emit="scan_failed")

    async def check(self, now: float) -> None:
        """Call periodically. May raise :class:`ControllerResetRequired`."""
        if self.state is ScanState.RUNNING:
            quiet_since = max(self.last_advertisement or 0.0, self._started_at)
            limit = (
                self._timings.silence
                if self.last_advertisement is not None
                else self._timings.first_advertisement
            )
            if now - quiet_since < limit:
                return
            if self.last_advertisement is None:
                self.last_error = "nothing was received since the start"
                if await self._fallback_start(now):
                    return
            minutes = round((now - quiet_since) / 60)
            _LOGGER.warning("No Bluetooth advertisements for %d minutes, restarting scan", minutes)
            self.last_error = f"no advertisements for {minutes} minutes"
            self._trouble_since = now
            self._failed_attempt(now, emit="scan_silent", minutes=minutes)
            await self._attempt(now)
            return

        if self._scanner is not None:
            # Started successfully, waiting for the first advertisement.
            if now - self._started_at < self._timings.confirm:
                return
            self.last_error = "scan started but nothing was received"
            _LOGGER.warning("Bluetooth scan started but nothing was received")
            await self._stop_scanner()
            if not await self._fallback_start(now):
                self._failed_attempt(now)
            return

        if now >= self._next_attempt:
            await self._attempt(now)

    async def stop(self) -> None:
        await self._stop_scanner()

    # -- internals -------------------------------------------------------------

    async def _attempt(self, now: float) -> None:
        if not (await self._try_start(now) or await self._fallback_start(now)):
            self._failed_attempt(now)

    async def _fallback_start(self, now: float) -> bool:
        """Let the fallback change the configuration and start again, but only as
        long as nothing has been received at all since the start."""
        if self.last_advertisement is not None or self._fallback is None:
            return False
        if not self._fallback(self.last_error or "unknown"):
            return False
        return await self._try_start(now)

    async def _try_start(self, now: float) -> bool:
        await self._stop_scanner()
        scanner = self._factory()
        try:
            async with asyncio.timeout(self._timings.start_timeout):
                await scanner.start()
        except (BleakError, OSError, TimeoutError) as err:
            self.last_error = str(err) or type(err).__name__
            _LOGGER.warning("Could not start Bluetooth scan: %s", self.last_error)
            with contextlib.suppress(BleakError, OSError, TimeoutError):
                async with asyncio.timeout(self._timings.start_timeout):
                    await scanner.stop()
            return False
        self._scanner = scanner
        self._started_at = now
        return True

    async def _stop_scanner(self) -> None:
        scanner, self._scanner = self._scanner, None
        if scanner is None:
            return
        try:
            async with asyncio.timeout(self._timings.start_timeout):
                await scanner.stop()
        except (BleakError, OSError, TimeoutError) as err:
            _LOGGER.debug("Stopping the scan failed: %s", err)

    def _failed_attempt(self, now: float, emit: str | None = None, **data: object) -> None:
        self._failures += 1
        if emit is not None:
            self._emit(emit, error=self.last_error or "", **data)
        if self.state in (ScanState.STARTING, ScanState.RUNNING):
            self._set_state(ScanState.RECOVERING, now)
        if self._failures >= self._timings.escalate_after:
            self._escalate(now)
        delays = self._timings.retry_delays
        self._next_attempt = now + delays[min(self._failures - 1, len(delays) - 1)]

    def _escalate(self, now: float) -> None:
        if self._reset_allowed():
            _LOGGER.error("Bluetooth does not recover, requesting a controller reset")
            self._write_marker()
            self._emit("bluetooth_reset", error=self.last_error or "")
            raise ControllerResetRequired(self.last_error or "Bluetooth does not recover")
        if self.state is not ScanState.FAILED:
            _LOGGER.error(
                "Bluetooth does not recover and the controller was reset recently; "
                "retrying every %d minutes",
                round(self._timings.retry_delays[-1] / 60),
            )
            self._emit("bluetooth_failed", error=self.last_error or "")
            self._set_state(ScanState.FAILED, now)
        self._failures = max(self._failures, len(self._timings.retry_delays))

    def _set_state(self, state: ScanState, now: float) -> None:
        if state is not self.state:
            self.state = state
            self.since = now

    def _emit(self, kind: str, **data: object) -> None:
        if self._listener is not None:
            self._listener(kind, data)

    # -- reset marker ------------------------------------------------------------

    def last_reset(self) -> float | None:
        """Wall-clock time of the last requested controller reset, if known."""
        if self._marker is None:
            return None
        try:
            return float(json.loads(self._marker.read_text())["requested_at"])
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def _reset_allowed(self) -> bool:
        if self._marker is None:
            return False
        last = self.last_reset()
        return last is None or self._wall_clock() - last >= self._timings.reset_cooldown

    def _write_marker(self) -> None:
        if self._marker is None:  # pragma: no cover - checked by _reset_allowed
            return
        tmp = self._marker.with_name(self._marker.name + ".tmp")
        tmp.write_text(json.dumps({"requested_at": self._wall_clock()}))
        os.replace(tmp, self._marker)


# -- controller reset (runs as root) ---------------------------------------------


class ResetError(RuntimeError):
    """The controller could not be reset."""


def reset_controller(
    adapter: str,
    *,
    sys_root: Path = Path("/sys"),
    timeout: float = 20.0,
    sleep: Callable[[float], None] = time.sleep,
) -> Path:
    """Reset a Bluetooth controller by re-binding its kernel driver. Needs root.

    Unbinding detaches the device (for the UART-attached chip of a Raspberry Pi
    this also toggles its power line); binding again re-initializes it, including
    the firmware patch. ``bluetoothd`` then sets it up as usual. Works the same way
    for USB adapters (``btusb``). Returns the device path.
    """
    device_link = sys_root / "class" / "bluetooth" / adapter / "device"
    if not device_link.exists():
        raise ResetError(f"Bluetooth adapter {adapter} not found")
    device = device_link.resolve()
    driver = (device / "driver").resolve()
    if not (driver / "bind").exists():
        raise ResetError(f"{adapter}: no driver bound to {device}")
    name = device.name
    _LOGGER.info("Resetting %s: re-binding %s to %s", adapter, name, driver.name)
    try:
        (driver / "unbind").write_text(name)
        sleep(1.0)
        (driver / "bind").write_text(name)
    except OSError as err:
        raise ResetError(f"{adapter}: re-binding {name} failed: {err}") from err

    deadline = time.monotonic() + timeout
    while not any((device / "bluetooth").glob("hci*")):
        if time.monotonic() >= deadline:
            raise ResetError(f"{adapter} did not come back within {timeout:.0f} seconds")
        sleep(0.5)
    return device
