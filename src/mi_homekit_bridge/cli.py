"""Command line interface: ``run``, ``scan``, ``fetch-keys``, ``set-key``, ``demo``
and ``reset-bluetooth``."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import logging
import os
import sys
from pathlib import Path

from . import __version__
from .config import (
    DEFAULT_ADAPTER,
    ConfigError,
    bindkey_env_var,
    load_config,
    normalize_mac,
    parse_bindkey,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_CONFIG = Path("/etc/mi-homekit-bridge/config.toml")
DEFAULT_STATE_DIR = Path("/var/lib/mi-homekit-bridge")
DEFAULT_ENV_FILE = Path("/etc/mi-homekit-bridge/bindkeys.env")

LOGIN_REJECTED_HINT = """\
Xiaomi rejected the login.

This message does not necessarily mean the password is wrong. Xiaomi also rejects
password logins when it wants a captcha, or when the account was created with
"Sign in with Apple/Google/Facebook" and has no Xiaomi password at all.
Do not retry too often, Xiaomi rate-limits failed logins.

Alternative: log in via QR code with the Xiaomi Cloud Tokens Extractor
(https://github.com/PiotrMachowski/Xiaomi-cloud-tokens-extractor) and store the
"BLE KEY" of each sensor with:  mi-homekit-bridge set-key <MAC>"""


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mi-homekit-bridge",
        description="Expose Xiaomi LYWSD03MMC and BTHome BLE thermometers to Apple HomeKit.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="enable debug logging")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run the bridge")
    run.add_argument("-c", "--config", type=Path, default=DEFAULT_CONFIG)
    run.add_argument("-s", "--state-dir", type=Path, default=DEFAULT_STATE_DIR)

    scan = sub.add_parser("scan", help="list nearby supported thermometers")
    scan.add_argument("-t", "--seconds", type=float, default=20.0)

    keys = sub.add_parser("fetch-keys", help="fetch bindkeys from your Xiaomi account")
    keys.add_argument("-c", "--config", type=Path, default=DEFAULT_CONFIG)
    keys.add_argument(
        "--env-file",
        type=Path,
        metavar="PATH",
        help="store the keys in this environment file (created with mode 600)",
    )
    keys.add_argument(
        "--server",
        action="append",
        dest="servers",
        metavar="REGION",
        help="Xiaomi cloud region, e.g. 'de' (repeatable, default: try all)",
    )

    setkey = sub.add_parser("set-key", help="store a bindkey obtained elsewhere (hidden prompt)")
    setkey.add_argument("mac", help="MAC address of the sensor")
    setkey.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE, metavar="PATH")

    reset = sub.add_parser(
        "reset-bluetooth",
        help="reset the Bluetooth controller by re-binding its driver (root, used by systemd)",
    )
    reset.add_argument("-c", "--config", type=Path, default=DEFAULT_CONFIG)
    reset.add_argument("--adapter", help="adapter name (default: from the config, else hci0)")
    reset.add_argument(
        "--if-exit-status",
        type=int,
        metavar="N",
        help="only reset if $EXIT_STATUS (set by systemd for ExecStopPost=) equals N",
    )

    demo = sub.add_parser("demo", help="serve the dashboard with generated sample data")
    demo.add_argument("--host", default="127.0.0.1")
    demo.add_argument("--port", type=int, default=8080)
    demo.add_argument("--days", type=int, default=400, help="days of sample data")
    return parser


def _cmd_run(args: argparse.Namespace) -> int:
    from .app import run_bridge
    from .bluetooth import EXIT_CONTROLLER_RESET, ControllerResetRequired

    config = load_config(args.config)
    try:
        asyncio.run(run_bridge(config, args.state_dir))
    except ControllerResetRequired as err:
        _LOGGER.error("Exiting so that the Bluetooth controller gets reset (%s)", err)
        return EXIT_CONTROLLER_RESET
    return 0


def _cmd_reset_bluetooth(args: argparse.Namespace) -> int:
    from .bluetooth import ResetError, reset_controller

    if args.if_exit_status is not None and os.environ.get("EXIT_STATUS") != str(
        args.if_exit_status
    ):
        return 0
    adapter = args.adapter
    if adapter is None:
        try:
            adapter = load_config(args.config).bluetooth.adapter
        except ConfigError as err:
            _LOGGER.warning("%s; using %s", err, DEFAULT_ADAPTER)
            adapter = DEFAULT_ADAPTER
    if os.geteuid() != 0:
        print("reset-bluetooth must run as root", file=sys.stderr)
        return 1
    try:
        device = reset_controller(adapter)
    except ResetError as err:
        print(f"Bluetooth reset failed: {err}", file=sys.stderr)
        return 1
    print(f"Bluetooth controller {adapter} reset ({device.name})")
    return 0


def _cmd_scan(args: argparse.Namespace) -> int:
    from .scanner import discover

    print(f"Scanning for {args.seconds:.0f} seconds...")
    results = asyncio.run(discover(args.seconds))
    if not results:
        print("No supported thermometers found.")
        return 1
    for address, name, rssi, fmt in results:
        print(f"{address}  {rssi:>4} dBm  {name:<14} {fmt}")
    return 0


def _cmd_fetch_keys(args: argparse.Namespace) -> int:
    from xiaomi_ble.cloud import (
        XiaomiCloudException,
        XiaomiCloudInvalidPasswordException,
        XiaomiCloudTwoFactorAuthenticationException,
    )

    from .keys import fetch_bindkeys, write_env_file

    config = load_config(args.config)
    macs = [sensor.mac for sensor in config.sensors]
    username = input("Xiaomi account (e-mail or account ID): ").strip()
    password = getpass.getpass("Password: ")
    try:
        found = asyncio.run(fetch_bindkeys(username, password, macs, args.servers))
    except XiaomiCloudTwoFactorAuthenticationException as err:
        print(
            "Xiaomi wants to verify this login. Open the following URL in a browser, "
            "complete the check and run this command again:\n" + err.url,
            file=sys.stderr,
        )
        return 2
    except XiaomiCloudInvalidPasswordException:
        print(LOGIN_REJECTED_HINT, file=sys.stderr)
        return 2
    except XiaomiCloudException as err:
        print(f"Xiaomi cloud login failed: {err}", file=sys.stderr)
        return 2

    for sensor in config.sensors:
        print(f"{sensor.name} ({sensor.mac}): {'found' if sensor.mac in found else 'NOT FOUND'}")
    if found:
        if args.env_file:
            write_env_file(args.env_file, found)
            print(f"Stored {len(found)} bindkey(s) in {args.env_file}")
        else:
            print("\nAdd these to the service environment (e.g. an EnvironmentFile):")
            for mac, key in found.items():
                print(f"{bindkey_env_var(mac)}={key}")
    missing = [s.name for s in config.sensors if s.mac not in found]
    if missing:
        print(
            "Not found in the account: " + ", ".join(missing) + ". "
            "Is the sensor added in the Mi Home app?",
            file=sys.stderr,
        )
        return 1
    return 0


def _cmd_set_key(args: argparse.Namespace) -> int:
    from .keys import write_env_file

    mac = normalize_mac(args.mac)
    key = getpass.getpass(f"Bindkey for {mac} (32 hex characters, input is hidden): ").strip()
    if parse_bindkey(key) is None:
        raise ConfigError("no bindkey entered")
    write_env_file(args.env_file, {mac: key.lower()})
    print(f"Stored {bindkey_env_var(mac)} in {args.env_file}")
    return 0


async def _serve_demo(host: str, port: int, days: int) -> None:
    import signal
    import tempfile

    from .demo import create_demo_store, demo_status
    from .web import start_web

    with tempfile.TemporaryDirectory(prefix="mi-homekit-bridge-demo-") as tmp:
        print(f"Generating {days} days of sample data...")
        store = await asyncio.to_thread(create_demo_store, Path(tmp) / "demo.db", days)
        runner = await start_web(store, host, port, status=demo_status)
        print(f"Demo dashboard: http://{host}:{port}  (Ctrl+C to stop)")
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
        try:
            await stop.wait()
        finally:
            await runner.cleanup()
            store.close()


def _cmd_demo(args: argparse.Namespace) -> int:
    asyncio.run(_serve_demo(args.host, args.port, args.days))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    if not args.verbose:
        # HAP-python and the parsers are chatty on INFO.
        for noisy in ("pyhap", "xiaomi_ble", "bthome_ble"):
            logging.getLogger(noisy).setLevel(logging.WARNING)

    commands = {
        "run": _cmd_run,
        "scan": _cmd_scan,
        "fetch-keys": _cmd_fetch_keys,
        "set-key": _cmd_set_key,
        "demo": _cmd_demo,
        "reset-bluetooth": _cmd_reset_bluetooth,
    }
    try:
        return commands[args.command](args)
    except ConfigError as err:
        print(f"Configuration error: {err}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
