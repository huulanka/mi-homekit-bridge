# 5. Bluetooth recovery with a privileged reset step

- Status: accepted
- Date: 2026-11-04

## Context

In the night of 2026-11-04 the built-in Bluetooth controller of the Raspberry Pi 3
(BCM43438, attached via UART) stopped answering HCI commands after about six hours
of active scanning (`command 0x200c tx timeout`). From then on BlueZ refused every
scan start with `org.bluez.Error.InProgress`. The bridge only noticed after 60
minutes without sensor data, tried to restart the scan, crashed on the exception
and ended up in a restart loop: HomeKit showed "No Response" and the dashboard was
unreachable for almost four hours.

Findings:

- Restarting the scan, restarting `bluetoothd` or powering the adapter off and on
  through BlueZ (`btmgmt power off`) did not help: the controller answered "Busy".
- Re-binding the kernel driver (`hci_uart_bcm` for the Pi's UART chip, `btusb` for
  USB dongles) did: it power-cycles the chip and reloads its firmware patch.
- Re-binding needs root. The bridge runs as an unprivileged, sandboxed system user.
- With active scanning the kernel logged about 400 UART framing errors per hour
  (`Frame reassembly failed`); before the bridge was installed there were none.

## Options

1. **Run the bridge as root**: simplest, but throws away the sandbox for a process
   that parses untrusted radio input and serves HTTP.
2. **Polkit rule or sudoers entry** so the bridge user may run one reset command:
   more configuration outside the unit, and a privileged entry point the service
   can trigger at any time.
3. **A path unit** watching a request file, triggering a root oneshot service: no
   restart of the bridge, but two more units and recovery logic split across them.
4. **Exit with a dedicated status and reset in `ExecStopPost=+`**: systemd runs the
   reset command as root after the bridge has exited, only for that status, then
   restarts the bridge as usual.

## Decision

Option 4, together with a supervisor inside the bridge:

- The scan is watched by `ScanSupervisor`. No advertisement from any device for
  5 minutes means the scan is dead; it is restarted. Failed starts are retried with
  increasing delays while HomeKit and the dashboard keep running and the sensors
  are flagged as faulty in HomeKit right away.
- After three failed attempts in a row the bridge exits with status 75
  (`EX_TEMPFAIL`). `ExecStopPost=-+... reset-bluetooth --if-exit-status 75` re-binds
  the driver; systemd restarts the bridge 10 seconds later. In the incident above
  this means about 6 minutes of outage instead of 4 hours.
- At most one reset per 30 minutes (marker file in the state directory). In between
  the bridge stays up and retries every 5 minutes, reporting the failure in the
  dashboard, `/api/health` (503) and the event log.
- The bridge never gets root. The reset command runs from the root-owned venv in
  `/opt`, which `scripts/deploy.sh` keeps unwritable for anyone else, and only
  accepts an adapter name (`hci[0-9]+`).
- `Type=notify` with `WatchdogSec=180`: systemd also restarts the bridge if it
  hangs instead of crashing.
- `[bluetooth] scanning_mode = "passive"` is offered to reduce radio and UART
  traffic: BlueZ advertisement monitors with patterns for MiBeacon and BTHome
  service data. It stays opt-in: it needs `bluetoothd --experimental`, and on the
  Raspberry Pi 3 (BlueZ 5.82, no monitor offloading in the controller) it started
  without an error but BlueZ forwarded nothing at all. A reset cannot fix a mode the
  system does not support, so as long as nothing has been received since the start
  the supervisor first asks a fallback to switch to active scanning, and only then
  counts failures.

## Consequences

- Recovery works without manual intervention, also for USB adapters.
- HomeKit sees the bridge restart once per reset (about 20 seconds).
- Outages and recoveries are recorded as events in the history database, so they
  can be traced after a reboot even with a volatile journal.
- A config error (exit status 2) no longer causes endless restarts
  (`RestartPreventExitStatus=2`).
