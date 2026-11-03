"""Expose Xiaomi LYWSD03MMC and BTHome BLE thermometers to Apple HomeKit."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("mi-homekit-bridge")
except PackageNotFoundError:  # pragma: no cover - only when running from a raw checkout
    __version__ = "0.0.0"
