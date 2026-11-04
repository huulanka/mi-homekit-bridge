"""Built-in dashboard: a small read-only JSON API plus the bundled web frontend.

The server listens on localhost by default and is meant to be published through a
reverse proxy such as ``tailscale serve``, which also provides HTTPS and access
control. There is deliberately no write endpoint.
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal

from aiohttp import web

from . import __version__
from .history import DAY, Bucket, HistoryStore, SensorInfo
from .status import BridgeStatus

_LOGGER = logging.getLogger(__name__)

DEFAULT_STATIC_DIR = Path(str(files("mi_homekit_bridge") / "static"))

Clock = Callable[[], float]
StatusProvider = Callable[[], BridgeStatus]


@dataclass(frozen=True, slots=True)
class Range:
    seconds: int | None
    """``None`` means "everything recorded"."""
    bucket: int | Literal["day"]


RANGES: dict[str, Range] = {
    "24h": Range(24 * 3600, 300),
    "7d": Range(7 * 86400, 1800),
    "30d": Range(30 * 86400, 3600),
    "1y": Range(365 * 86400, DAY),
    "all": Range(None, DAY),
}
PROFILE_DAYS = (7, 30, 90, 365)
HEATMAP_DAYS = (14, 30, 90)
SPARK_SECONDS = 24 * 3600
SPARK_BUCKET = 1800
HUMID_THRESHOLD = 60.0
"""Relative humidity above which mould becomes likely if it persists (%)."""
HUMID_SECONDS = 7 * 86400
EVENTS_LIMIT = 50

_STORE: web.AppKey[HistoryStore] = web.AppKey("store")
_CLOCK: web.AppKey[Clock] = web.AppKey("clock")
_STATIC: web.AppKey[Path] = web.AppKey("static_dir")
_STATUS: web.AppKey[StatusProvider | None] = web.AppKey("status")


def dew_point(temperature: float | None, humidity: float | None) -> float | None:
    """Dew point in °C (Magnus formula, valid for -45 °C to 60 °C)."""
    if temperature is None or humidity is None or humidity <= 0:
        return None
    a, b = 17.62, 243.12
    gamma = math.log(humidity / 100) + a * temperature / (b + temperature)
    return round(b * gamma / (a - gamma), 1)


def _round(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(value, digits)


def _bucket_row(b: Bucket) -> list[float | int | None]:
    return [
        b.ts,
        _round(b.temperature_min),
        _round(b.temperature_avg),
        _round(b.temperature_max),
        _round(b.humidity_min),
        _round(b.humidity_avg),
        _round(b.humidity_max),
    ]


def _sensor_json(sensor: SensorInfo) -> dict[str, Any]:
    return {
        "id": sensor.id,
        "name": sensor.name,
        "kind": sensor.kind,
        "target_temperature": sensor.target_temperature,
    }


def _int_choice(request: web.Request, name: str, choices: tuple[int, ...], default: int) -> int:
    raw = request.query.get(name, str(default))
    if not raw.isdigit() or int(raw) not in choices:
        allowed = ", ".join(map(str, choices))
        raise web.HTTPBadRequest(
            text=f'{{"error": "{name} must be one of {allowed}"}}', content_type="application/json"
        )
    return int(raw)


async def _run(func: Callable[..., Any], *args: Any) -> Any:
    return await asyncio.to_thread(func, *args)


# -- API handlers -------------------------------------------------------------


async def overview(request: web.Request) -> web.Response:
    store, now = request.app[_STORE], int(request.app[_CLOCK]())
    midnight = int(datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0).timestamp())
    result = []
    for sensor in await _run(store.sensors):
        latest = await _run(store.latest, sensor.id)
        today = await _run(store.series, sensor.id, midnight, now + 1, DAY)
        spark = await _run(store.series, sensor.id, now - SPARK_SECONDS, now + 1, SPARK_BUCKET)
        humid = None
        if sensor.kind == "ble":
            share = await _run(
                store.humidity_share, sensor.id, now - HUMID_SECONDS, now + 1, HUMID_THRESHOLD
            )
            if share.share is not None:
                humid = {
                    "threshold": HUMID_THRESHOLD,
                    "share": _round(share.share, 3),
                    "hours": share.hours,
                }
        result.append(
            _sensor_json(sensor)
            | {
                "latest": None
                if latest is None
                else {
                    "ts": latest.ts,
                    "temperature": _round(latest.temperature, 1),
                    "humidity": _round(latest.humidity, 1),
                    "battery": latest.battery,
                    "dew_point": dew_point(latest.temperature, latest.humidity),
                },
                "today": _bucket_row(today[-1])[1:] if today else None,
                "spark": [[b.ts, _round(b.temperature_avg), _round(b.humidity_avg)] for b in spark],
                "humid": humid,
            }
        )
    return web.json_response(
        {
            "generated_at": now,
            "first_ts": await _run(store.first_timestamp),
            "sensors": result,
        }
    )


async def series(request: web.Request) -> web.Response:
    store, now = request.app[_STORE], int(request.app[_CLOCK]())
    name = request.query.get("range", "24h")
    selected = RANGES.get(name)
    if selected is None:
        raise web.HTTPBadRequest(
            text=f'{{"error": "range must be one of {", ".join(RANGES)}"}}',
            content_type="application/json",
        )
    if selected.seconds is None:
        start = await _run(store.first_timestamp) or now - 86400
    else:
        start = now - selected.seconds
    sensors = []
    for sensor in await _run(store.sensors):
        buckets = await _run(store.series, sensor.id, start, now + 1, selected.bucket)
        sensors.append(_sensor_json(sensor) | {"points": [_bucket_row(b) for b in buckets]})
    return web.json_response(
        {"range": name, "bucket": selected.bucket, "start": start, "end": now, "sensors": sensors}
    )


async def profile(request: web.Request) -> web.Response:
    store, now = request.app[_STORE], int(request.app[_CLOCK]())
    days = _int_choice(request, "days", PROFILE_DAYS, 30)
    sensors = []
    for sensor in await _run(store.sensors):
        points = await _run(store.hourly_profile, sensor.id, now - days * 86400, now + 1)
        sensors.append(
            _sensor_json(sensor)
            | {
                "points": [
                    [p.hour, _round(p.temperature_avg), _round(p.humidity_avg), p.samples]
                    for p in points
                ]
            }
        )
    return web.json_response({"days": days, "sensors": sensors})


async def heatmap(request: web.Request) -> web.Response:
    store, now = request.app[_STORE], int(request.app[_CLOCK]())
    days = _int_choice(request, "days", HEATMAP_DAYS, 30)
    # Whole local days only, so the first column is not a partial day.
    first_day = datetime.fromtimestamp(now) - timedelta(days=days - 1)
    start = int(first_day.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    sensors = []
    for sensor in await _run(store.sensors):
        cells = await _run(store.heatmap, sensor.id, start, now + 1)
        sensors.append(
            _sensor_json(sensor)
            | {
                "cells": [
                    [c.day, c.hour, _round(c.temperature_avg), _round(c.humidity_avg)]
                    for c in cells
                ]
            }
        )
    return web.json_response({"days": days, "sensors": sensors})


async def export_csv(request: web.Request) -> web.Response:
    rows = await _run(lambda: list(request.app[_STORE].export_rows()))
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["time", "sensor", "temperature_c", "humidity_percent", "battery_percent"])
    for name, ts, temperature, humidity, battery in rows:
        writer.writerow(
            [
                datetime.fromtimestamp(ts).astimezone().isoformat(),
                name,
                temperature,
                humidity,
                battery,
            ]
        )
    stamp = datetime.fromtimestamp(request.app[_CLOCK]()).strftime("%Y%m%d")
    return web.Response(
        text=buffer.getvalue(),
        content_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="climate-history-{stamp}.csv"'},
    )


async def event_list(request: web.Request) -> web.Response:
    store = request.app[_STORE]
    items = await _run(store.events, EVENTS_LIMIT)
    return web.json_response(
        {
            "events": [
                {"ts": e.ts, "kind": e.kind, "sensor_id": e.sensor_id, "data": dict(e.data)}
                for e in items
            ]
        }
    )


async def live_status(request: web.Request) -> web.Response:
    provider = request.app[_STATUS]
    if provider is None:
        raise web.HTTPNotFound(
            text='{"error": "no live status in this mode"}', content_type="application/json"
        )
    return web.json_response(provider().to_json())


async def health(request: web.Request) -> web.Response:
    """``200`` if everything works, ``503`` with the list of problems otherwise."""
    provider = request.app[_STATUS]
    problems = provider().problems if provider is not None else []
    return web.json_response(
        {"status": "degraded" if problems else "ok", "version": __version__, "problems": problems},
        status=503 if problems else 200,
    )


# -- frontend -----------------------------------------------------------------


async def index(request: web.Request) -> web.StreamResponse:
    page = request.app[_STATIC] / "index.html"
    if not page.is_file():
        return web.Response(
            text="The dashboard frontend is not built. Run 'npm run build' in frontend/.",
            status=503,
        )
    return web.FileResponse(page, headers={"Cache-Control": "no-cache"})


async def root_file(request: web.Request) -> web.StreamResponse:
    """Top-level files such as the favicon and the web app manifest."""
    name = request.match_info["name"]
    path = request.app[_STATIC] / name
    if "/" in name or name.startswith(".") or name == "index.html" or not path.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(path, headers={"Cache-Control": "public, max-age=86400"})


# -- middleware ---------------------------------------------------------------

_CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
    "form-action 'none'"
)

Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


@web.middleware
async def headers_middleware(request: web.Request, handler: Handler) -> web.StreamResponse:
    response = await handler(request)
    response.headers.setdefault("Content-Security-Policy", _CSP)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if request.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    elif request.path.startswith("/assets/"):
        # File names contain a content hash, so they never change.
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


def create_app(
    store: HistoryStore,
    *,
    status: StatusProvider | None = None,
    static_dir: Path = DEFAULT_STATIC_DIR,
    clock: Clock = time.time,
) -> web.Application:
    """The dashboard app. Without ``status`` (demo mode) there is no live status."""
    app = web.Application(middlewares=[headers_middleware])
    app[_STORE] = store
    app[_CLOCK] = clock
    app[_STATIC] = static_dir
    app[_STATUS] = status
    app.router.add_get("/api/overview", overview)
    app.router.add_get("/api/series", series)
    app.router.add_get("/api/profile", profile)
    app.router.add_get("/api/heatmap", heatmap)
    app.router.add_get("/api/export.csv", export_csv)
    app.router.add_get("/api/events", event_list)
    app.router.add_get("/api/status", live_status)
    app.router.add_get("/api/health", health)
    app.router.add_get("/", index)
    if (static_dir / "assets").is_dir():
        app.router.add_static("/assets", static_dir / "assets")
    app.router.add_get("/{name}", root_file)
    return app


async def start_web(store: HistoryStore, host: str, port: int, **kwargs: Any) -> web.AppRunner:
    """Start the dashboard server; call ``runner.cleanup()`` to stop it."""
    runner = web.AppRunner(create_app(store, **kwargs), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, host, port).start()
    _LOGGER.info("Dashboard on http://%s:%d", host, port)
    return runner
