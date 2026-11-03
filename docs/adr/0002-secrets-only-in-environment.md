# 2. Secrets only in environment variables

- Status: accepted
- Date: 2026-11-03

## Context

The repository is public. The bridge needs one secret per stock-firmware sensor
(the bindkey). A config file that mixes harmless settings with secrets is easy to
commit, paste into an issue or share by accident.

## Decision

- The TOML config holds only non-secret settings (names, MAC addresses, port).
- Bindkeys are read exclusively from environment variables named
  `MI_HOMEKIT_BRIDGE_BINDKEY_<MAC without colons>`.
- The config parser rejects a `bindkey` entry with an error, so secrets cannot creep
  back into the config file.
- On a systemd host the variables come from `EnvironmentFile=/etc/mi-homekit-bridge/bindkeys.env`
  (root-only, mode 600). systemd reads the file before dropping privileges, so the
  service user (`DynamicUser=yes`) cannot read the file itself.
- Xiaomi credentials are never stored; `fetch-keys` prompts for them.
- Tests use generated, throw-away keys and example MAC addresses only.
- CI runs gitleaks on the full history.

## Consequences

- Config files can be shared safely for support.
- Environment variables are visible to root and to the service's own user via
  `/proc/<pid>/environ`. With a dedicated dynamic user this is acceptable for these
  low-impact secrets.
