# 3. Local measurement history in SQLite, inside the bridge

- Status: accepted
- Date: 2026-11-03
- Amends: [ADR 1](0001-standalone-python-bridge.md) ("no history of its own")

## Context

Apple Home only shows current values. The goal is to look at temperature and
humidity over days, months and years, together with the outdoor climate. Constraints:
everything runs on the Raspberry Pi (1 GB RAM), no second project or container to
maintain, no dependency on other machines.

## Options

1. **Separate recorder service + Postgres** (on the Pi or a NAS): clean separation, but
   a second deployment and a database server to operate and upgrade.
2. **Prometheus/InfluxDB + Grafana**: standard tooling, but two more services with their
   own storage, users and upgrades, ~250 MB RAM.
3. **History inside the bridge, stored in SQLite**: the bridge already holds the current
   values; SQLite is part of Python, needs no server and no administration.

## Decision

Option 3. The bridge writes one sample per sensor every few minutes into
`<state dir>/history.db`. The feature can be switched off in the config.

SQLite is a good fit here because exactly one local process reads and writes the
file; the usual concerns about file databases (concurrent writers, network shares)
do not apply. WAL mode allows reading while writing. The data volume is tiny
(about 15 MB per year for three sensors at 5-minute intervals), so aggregation is
done on the fly in SQL without pre-computed rollups.

## Consequences

- One service, one file to back up (`sqlite3 .backup`).
- The bridge gains an optional dependency on the network for weather data; failures
  are logged and never affect HomeKit.
- Day boundaries use the server's local time zone.
- Schema changes are versioned with `PRAGMA user_version`.
