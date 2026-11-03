# 1. Standalone Python bridge instead of a home automation platform

- Status: accepted
- Date: 2026-11-03

## Context

Two Xiaomi LYWSD03MMC thermometers should show up in Apple Home. The available
hardware is a Raspberry Pi 3 Model B (1 GB RAM) that already runs other services.
The goal is the smallest reliable solution that is easy to operate, not a general
home automation platform.

## Options

1. **Home Assistant + HomeKit Bridge integration**: excellent BLE support, but a large
   platform (database, web UI, update cadence) for two sensors. 1 GB RAM is the lower limit.
2. **Homebridge + an existing plugin**: Homebridge is the de-facto HomeKit bridge, but
   the available LYWSD03MMC plugins are barely maintained and rely on `noble`, a
   Node.js BLE library with a history of BlueZ issues. Adds Node.js and a web UI.
3. **Own Homebridge plugin**: HomeKit side solved by Homebridge, but BLE scanning and
   MiBeacon decryption would have to be written from scratch in JavaScript. Still needs
   Homebridge running.
4. **Own bridge in Rust or Go**: smallest footprint, but the HomeKit libraries
   (`hap-rs`, `brutella/hap`) have seen little maintenance since 2024.
5. **Own bridge in Python on top of Home Assistant's libraries**: `bleak`,
   `xiaomi-ble`, `bthome-ble` and `HAP-python` are maintained and used by every
   Home Assistant installation.

## Decision

Option 5. The bridge is a thin layer (config, routing, stale detection) over
well-maintained libraries. Parsing and decryption are not re-implemented.

## Consequences

- Small footprint (one Python process, no database, no UI).
- Supported devices follow upstream `xiaomi-ble` and `bthome-ble`.
- `HAP-python` is pinned to the major version Home Assistant uses.
- The bridge has no history or automations of its own; those live in Apple Home.
