#!/usr/bin/env bash
# Build mi-homekit-bridge locally and install/upgrade it on a Linux host via SSH.
#
#   scripts/deploy.sh user@host
#
# Builds the dashboard frontend (needs Node.js, see frontend/.node-version), then
# installs into /opt/mi-homekit-bridge/venv with the exact, hash-pinned
# dependency versions from uv.lock and (re)installs the systemd unit.
# It never touches /etc/mi-homekit-bridge/config.toml or bindkeys.env.
set -euo pipefail

host="${1:?usage: scripts/deploy.sh user@host}"
cd "$(dirname "$0")/.."

rm -rf dist
npm --prefix frontend ci --silent
npm --prefix frontend run build --silent
uv build --wheel --quiet
uv export --frozen --no-dev --no-emit-project --format requirements.txt \
    --output-file dist/requirements.txt --quiet
wheel="$(basename dist/*.whl)"

remote_tmp="$(ssh "$host" mktemp -d)"
scp -q dist/requirements.txt "dist/$wheel" deploy/mi-homekit-bridge.service \
    deploy/mi-homekit-bridge.sysusers "$host:$remote_tmp/"

ssh "$host" sudo bash -s -- "$remote_tmp" "$wheel" <<'REMOTE'
set -euo pipefail
tmp="$1"
wheel="$2"
prefix=/opt/mi-homekit-bridge

if [ ! -x "$prefix/venv/bin/python" ]; then
    python3 -m venv "$prefix/venv"
fi
"$prefix/venv/bin/pip" install --quiet --disable-pip-version-check \
    --require-hashes -r "$tmp/requirements.txt"
"$prefix/venv/bin/pip" install --quiet --disable-pip-version-check \
    --no-deps --force-reinstall "$tmp/$wheel"

# The unit runs "reset-bluetooth" from this venv as root (ExecStopPost=+), so
# nobody but root may be able to change it.
chown -R root:root "$prefix"
chmod -R go-w "$prefix"

install -D -m 644 "$tmp/mi-homekit-bridge.sysusers" /etc/sysusers.d/mi-homekit-bridge.conf
systemd-sysusers /etc/sysusers.d/mi-homekit-bridge.conf
install -d -m 755 /etc/mi-homekit-bridge
install -D -m 644 "$tmp/mi-homekit-bridge.service" /etc/systemd/system/mi-homekit-bridge.service
systemctl daemon-reload
if [ -f /etc/mi-homekit-bridge/config.toml ]; then
    # Start at boot. A first install without config is enabled in README step 4.
    systemctl enable --quiet mi-homekit-bridge
fi
if systemctl is-active --quiet mi-homekit-bridge; then
    systemctl restart mi-homekit-bridge
fi
rm -rf "$tmp"
echo "Installed $("$prefix/venv/bin/mi-homekit-bridge" --version)"
echo "Service: $(systemctl is-enabled mi-homekit-bridge 2>/dev/null || true)," \
    "$(systemctl is-active mi-homekit-bridge 2>/dev/null || true)"
REMOTE
