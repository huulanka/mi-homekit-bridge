# mi-homekit-bridge

[![CI](https://github.com/huulanka/mi-homekit-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/huulanka/mi-homekit-bridge/actions/workflows/ci.yml)

A tiny, single-purpose bridge that brings Bluetooth thermometers such as the
**Xiaomi Mi Temperature and Humidity Monitor 2 (LYWSD03MMC)** into **Apple Home**.
No Home Assistant, no Homebridge, no web UI: one small Python service on a
Raspberry Pi (or any Linux box with Bluetooth).

```
LYWSD03MMC ──BLE advertisements──▶ mi-homekit-bridge ──HomeKit (HAP)──▶ Home app / HomePod
```

Each sensor shows up in the Home app with temperature, humidity and battery level.
The bridge only listens to the advertisements the sensors broadcast anyway; it never
connects to them.

Under the hood it glues together the libraries that also power Home Assistant:
[bleak](https://github.com/hbldh/bleak) (Bluetooth),
[xiaomi-ble](https://github.com/Bluetooth-Devices/xiaomi-ble) and
[bthome-ble](https://github.com/Bluetooth-Devices/bthome-ble) (parsing and decryption),
and [HAP-python](https://github.com/ikalchev/HAP-python) (HomeKit).

## Supported sensors

| Sensor | Format | Bindkey needed |
|---|---|---|
| Xiaomi LYWSD03MMC, stock firmware | encrypted MiBeacon v4/v5 | yes, see [Bindkeys](#bindkeys-stock-firmware-only) |
| LYWSD03MMC with [pvvx custom firmware](https://github.com/pvvx/ATC_MiThermometer), or any other BTHome v2 sensor | BTHome v2 | only if you enabled BTHome encryption |

Other Xiaomi MiBeacon thermometers supported by `xiaomi-ble` will most likely work too,
but are untested.

## Requirements

- Linux with BlueZ (tested on a Raspberry Pi 3 Model B with Debian 13)
- Python 3.13
- The bridge must be in the same network as your iPhone and home hub (mDNS)

## Installation

### 1. Install the service

From a checkout on your computer (needs [uv](https://docs.astral.sh/uv/)):

```sh
scripts/deploy.sh user@your-pi
```

This installs the bridge into `/opt/mi-homekit-bridge/venv` with the hash-pinned
dependency versions from `uv.lock` and installs the systemd unit (needs `sudo` on the
host). Re-run it to upgrade. Your config and keys on the host are never touched.

### 2. Find your sensors

```sh
/opt/mi-homekit-bridge/venv/bin/mi-homekit-bridge scan
```

```
A4:C1:38:xx:xx:xx   -61 dBm  LYWSD03MMC     Xiaomi MiBeacon (encrypted, needs bindkey)
```

### 3. Configure

```sh
sudo install -m 644 config.example.toml /etc/mi-homekit-bridge/config.toml
sudoedit /etc/mi-homekit-bridge/config.toml   # names and MAC addresses
```

The config file never contains secrets, see [Secrets](#secrets-and-privacy).

### Bindkeys (stock firmware only)

Sensors on stock firmware only send measurements after they have been added to the
**Mi Home** app, and they encrypt them with a per-device *bindkey*. Fetch the keys
from your Xiaomi account:

```sh
sudo /opt/mi-homekit-bridge/venv/bin/mi-homekit-bridge fetch-keys \
    --env-file /etc/mi-homekit-bridge/bindkeys.env
```

You are asked for your Xiaomi account and password. They are only used for this
one login and are never stored. The keys end up in `bindkeys.env` (mode 600).
If Xiaomi asks for an additional verification, the command prints a link: open it,
confirm, and run the command again. As an alternative you can get the keys with the
[Xiaomi Cloud Tokens Extractor](https://github.com/PiotrMachowski/Xiaomi-cloud-tokens-extractor)
and write them into `bindkeys.env` yourself:

```sh
MI_HOMEKIT_BRIDGE_BINDKEY_A4C138XXXXXX=<32 hex characters>
```

### 4. Start

```sh
sudo systemctl enable --now mi-homekit-bridge
journalctl -u mi-homekit-bridge -o cat     # shows the HomeKit setup code and a QR code
```

### 5. Add to the Home app

Home app → **+** → **Add Accessory** → scan the QR code from the log or enter the
setup code manually. The setup code is also stored in
`/var/lib/mi-homekit-bridge/setup.json` and stays the same across restarts.

## Secrets and privacy

| What | Where | Notes |
|---|---|---|
| Bindkeys | environment variables `MI_HOMEKIT_BRIDGE_BINDKEY_<MAC>`, on the Pi in `/etc/mi-homekit-bridge/bindkeys.env` (root, mode 600) | read by systemd before the service starts; the config parser refuses a `bindkey` in the config file |
| HomeKit pairing keys and setup code | `/var/lib/mi-homekit-bridge/` (mode 700) | created on first start |
| Xiaomi account credentials | nowhere | prompted for by `fetch-keys`, used once |
| Names, MAC addresses, port | `/etc/mi-homekit-bridge/config.toml` | not secret, but personal: keep your real config out of git (`config.toml` is in `.gitignore`) |

The repository only contains example MAC addresses and throw-away test keys. CI runs
[gitleaks](https://github.com/gitleaks/gitleaks) on every push.

## Configuration reference

```toml
[bridge]
name = "Mi Thermometers"     # bridge name in the Home app
port = 51826                 # HomeKit TCP port
# address = "192.168.1.10"   # address announced via mDNS, auto-detected by default
stale_after_minutes = 60     # flag a sensor as faulty after this long without data

[[sensors]]
name = "Living Room"
mac = "A4:C1:38:00:00:01"
```

## Commands

| Command | Purpose |
|---|---|
| `mi-homekit-bridge run` | run the bridge (used by the systemd unit) |
| `mi-homekit-bridge scan [-t SECONDS]` | list nearby supported sensors with signal strength |
| `mi-homekit-bridge fetch-keys [--env-file PATH] [--server REGION]` | fetch bindkeys from the Xiaomi cloud |

Add `-v` for debug logging.

## Troubleshooting

- **Sensor shows a warning in the Home app**: it has not reported for
  `stale_after_minutes`. Check the range with `scan` (below about -90 dBm gets unreliable).
- **"sends encrypted data but no bindkey is configured"**: run `fetch-keys`.
- **"No measurements - pair it in the Mi Home app"** in `scan`: stock-firmware
  sensors stay silent until they have been added to Mi Home.
- **Bridge not found when pairing**: iPhone and bridge must be in the same network
  segment, and UDP 5353 (mDNS) and the HomeKit port must not be blocked.

## Development

```sh
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check . && uv run mypy
```

Tests use synthetic advertisements generated with throw-away keys (`tests/helpers.py`).
Design decisions are recorded in [docs/adr](docs/adr).

## Disclaimer

This is an independent hobby project. It is not affiliated with, endorsed by or
supported by Xiaomi or Apple. HomeKit is a trademark of Apple Inc.

## License

[MIT](LICENSE)
