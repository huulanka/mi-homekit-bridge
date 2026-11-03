"""Command line interface: ``run``, ``scan`` and ``fetch-keys``."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import logging
import sys
from pathlib import Path

from . import __version__
from .config import ConfigError, bindkey_env_var, load_config

DEFAULT_CONFIG = Path("/etc/mi-homekit-bridge/config.toml")
DEFAULT_STATE_DIR = Path("/var/lib/mi-homekit-bridge")


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
    return parser


def _cmd_run(args: argparse.Namespace) -> int:
    from .app import run_bridge

    config = load_config(args.config)
    asyncio.run(run_bridge(config, args.state_dir))
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

    commands = {"run": _cmd_run, "scan": _cmd_scan, "fetch-keys": _cmd_fetch_keys}
    try:
        return commands[args.command](args)
    except ConfigError as err:
        print(f"Configuration error: {err}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
