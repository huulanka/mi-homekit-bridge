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

Optionally it also keeps a **measurement history** in a local SQLite database,
records the **outdoor temperature and humidity** for your postal code from a weather
service, and serves a small **web dashboard** to explore it all over days, months
and years.

![Dashboard with sample data](docs/screenshots/dashboard-light.png)

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
confirm, and run the command again.

#### Accounts without a password (Sign in with Apple/Google) or captcha prompts

`fetch-keys` can only do a plain password login. If your Xiaomi account was created
with *Sign in with Apple/Google/Facebook*, or Xiaomi insists on a captcha, the login
is rejected ("Xiaomi rejected the login"). Use the QR-code login of the
[Xiaomi Cloud Tokens Extractor](https://github.com/PiotrMachowski/Xiaomi-cloud-tokens-extractor)
instead: choose `q`, scan the code with the Mi Home app and note the `BLE KEY` of each
sensor. Then store each key (the prompt is hidden, the file is created with mode 600):

```sh
sudo /opt/mi-homekit-bridge/venv/bin/mi-homekit-bridge set-key A4:C1:38:XX:XX:XX
```

The extractor also prints tokens for your other Xiaomi devices (e.g. a vacuum).
Treat them as secrets and do not paste them anywhere.

### 4. Start

```sh
sudo systemctl enable --now mi-homekit-bridge
journalctl -u mi-homekit-bridge -o cat     # shows the HomeKit setup code and a QR code
```

### 5. Add to the Home app

Home app → **+** → **Add Accessory** → scan the QR code from the log or enter the
setup code manually. The setup code is also stored in
`/var/lib/mi-homekit-bridge/setup.json` and stays the same across restarts.

## Dashboard

An optional, read-only web dashboard built into the bridge (no extra service):

- **Overview**: one card per room with temperature, humidity, dew point, battery,
  today's range, the difference to outdoor and the last 24 hours.
- **History**: all sensors in one chart for 24 hours up to everything recorded.
  Longer ranges show averages with a min–max band.
- **Indoor minus outdoor**: how much warmer (or more humid) it is inside.
- **Daily profile**: the typical course of a day by hour.
- **Hour × day heatmap**: patterns such as heating schedules, airing or sun.
- Every chart has a table view. CSV export of all data. Light and dark mode follow
  the system, the language follows the browser (English, German).

| Patterns | Phone, dark mode |
|---|---|
| ![Daily profile and heatmap](docs/screenshots/patterns-light.png) | ![Mobile dark mode](docs/screenshots/mobile-dark.png) |

*Screenshots use generated sample data (`mi-homekit-bridge demo`).*

Enable it in the config:

```toml
[web]
enabled = true          # requires [history]
host = "127.0.0.1"      # keep it on localhost ...
port = 8080
```

... and publish it through a reverse proxy. With [Tailscale](https://tailscale.com),
only devices in your tailnet can reach it and you get HTTPS for free:

```sh
sudo tailscale serve --bg --https=443 http://127.0.0.1:8080
# keep other apps reachable under their path, e.g.
sudo tailscale serve --bg --https=443 --set-path=/smokeping http://127.0.0.1:80/smokeping
```

On the iPhone, open the URL in Safari and choose *Share → Add to Home Screen*.

The dashboard has no login of its own and relies on the proxy for access control.
It only offers read endpoints and sends strict security headers. Do not bind it to
`0.0.0.0` on a network you do not trust.

**Try it without sensors:**

```sh
uv run mi-homekit-bridge demo      # http://127.0.0.1:8080 with 400 days of sample data
```

<details>
<summary>API</summary>

| Endpoint | Returns |
|---|---|
| `GET /api/overview` | latest values, today's range and a 24 h sparkline per sensor |
| `GET /api/series?range=24h\|7d\|30d\|1y\|all` | min/avg/max buckets (5 min, 30 min, 1 h or 1 day) |
| `GET /api/profile?days=7\|30\|90\|365` | average per hour of day |
| `GET /api/heatmap?days=14\|30\|90` | average per day and hour |
| `GET /api/export.csv` | all samples |
| `GET /api/health` | status and version |

</details>

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

All settings live in `/etc/mi-homekit-bridge/config.toml` (see
[config.example.toml](config.example.toml)). Unknown options are reported as errors,
so typos do not go unnoticed. Restart the service after changes.

```toml
[bridge]
name = "Mi Thermometers"     # bridge name in the Home app
port = 51826                 # HomeKit TCP port
# address = "192.168.1.10"   # address announced via mDNS, auto-detected by default
stale_after_minutes = 60     # flag a sensor as faulty after this long without data

[[sensors]]
name = "Living Room"
mac = "A4:C1:38:00:00:01"

[history]                    # optional, enabled by default
enabled = true
interval_minutes = 5         # one sample per sensor every 5 minutes

[weather]                    # optional, disabled by default, requires [history]
enabled = true
provider = "open-meteo"
name = "Outdoor"
postal_code = "10115"        # postal code + country ...
country = "DE"
# latitude = 52.52           # ... or coordinates
# longitude = 13.405
interval_minutes = 15

[web]                        # optional, disabled by default, requires [history]
enabled = true
host = "127.0.0.1"
port = 8080
```

### History

With `[history]` enabled, the bridge stores one sample per reporting sensor every
`interval_minutes` in `/var/lib/mi-homekit-bridge/history.db` (SQLite). Samples are
aligned to the clock (:00, :05, ...). Sensors that stopped reporting are not recorded,
so gaps stay gaps. A year of 5-minute samples for three sensors is roughly 15 MB.
After a restart the bridge shows the last recorded values (including battery level)
until the sensors report again.

Back up the database while the service is running with:

```sh
sudo sqlite3 /var/lib/mi-homekit-bridge/history.db ".backup '/tmp/history-backup.db'"
```

### Outdoor weather

With `[weather]` enabled, the current outdoor temperature and humidity are fetched
from [Open-Meteo](https://open-meteo.com) and stored like an additional sensor.
Open-Meteo is free for non-commercial use and needs no API key. A postal code is
resolved to coordinates once at startup. Weather data by
[Open-Meteo.com](https://open-meteo.com), licensed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

## Commands

| Command | Purpose |
|---|---|
| `mi-homekit-bridge run` | run the bridge (used by the systemd unit) |
| `mi-homekit-bridge scan [-t SECONDS]` | list nearby supported sensors with signal strength |
| `mi-homekit-bridge fetch-keys [--env-file PATH] [--server REGION]` | fetch bindkeys from the Xiaomi cloud |
| `mi-homekit-bridge set-key MAC [--env-file PATH]` | store a bindkey you got elsewhere (hidden prompt) |
| `mi-homekit-bridge demo [--port 8080] [--days 400]` | serve the dashboard with generated sample data |

Add `-v` for debug logging.

## Troubleshooting

- **Sensor shows a warning in the Home app**: it has not reported for
  `stale_after_minutes`. Check the range with `scan` (below about -90 dBm gets unreliable).
- **"sends encrypted data but no bindkey is configured"**: run `fetch-keys` or `set-key`.
- **"Xiaomi rejected the login"** although the password is right: see
  [Accounts without a password](#accounts-without-a-password-sign-in-with-applegoogle-or-captcha-prompts).
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

The dashboard lives in [`frontend/`](frontend) (React, TypeScript, Tailwind CSS,
Apache ECharts, built with Vite). It needs Node.js 26.12.1 or newer (older versions
are affected by the Brotli decoder vulnerability CVE-2026-111497):

```sh
uv run mi-homekit-bridge demo                  # API with sample data on :8080
cd frontend && npm ci && npm run dev           # http://localhost:5173, proxies /api
npm run lint && npm run typecheck && npm test  # checks
npm run build                                  # writes into src/mi_homekit_bridge/static
```

`scripts/deploy.sh` builds the frontend before packaging. Chart colors come from a
palette validated for color-vision deficiencies in light and dark mode.

## Disclaimer

This is an independent hobby project. It is not affiliated with, endorsed by or
supported by Xiaomi or Apple. HomeKit is a trademark of Apple Inc.

## License

[MIT](LICENSE)
