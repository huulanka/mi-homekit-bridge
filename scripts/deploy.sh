#!/usr/bin/env bash
# Build mi-homekit-bridge locally and install/upgrade it on a Linux host via SSH.
#
#   scripts/deploy.sh user@host
#
# Installs into /opt/mi-homekit-bridge/venv with the exact, hash-pinned
# dependency versions from uv.lock and (re)installs the systemd unit.
# It never touches /etc/mi-homekit-bridge/config.toml or bindkeys.env.
set -euo pipefail

host="${1:?usage: scripts/deploy.sh user@host}"
cd "$(dirname "$0")/.."

rm -rf dist
uv build --wheel --quiet
uv export --frozen --no-dev --no-emit-project --format requirements.txt \
    --output-file dist/requirements.txt --quiet
wheel="$(basename dist/*.whl)"

remote_tmp="$(ssh "$host" mktemp -d)"
scp -q dist/requirements.txt "dist/$wheel" deploy/mi-homekit-bridge.service "$host:$remote_tmp/"

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

install -d -m 755 /etc/mi-homekit-bridge
install -m 644 "$tmp/mi-homekit-bridge.service" /etc/systemd/system/mi-homekit-bridge.service
systemctl daemon-reload
if systemctl is-active --quiet mi-homekit-bridge; then
    systemctl restart mi-homekit-bridge
fi
rm -rf "$tmp"
echo "Installed $("$prefix/venv/bin/mi-homekit-bridge" --version)"
REMOTE
