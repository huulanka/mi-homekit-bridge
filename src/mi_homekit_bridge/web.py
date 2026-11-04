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
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal

from aiohttp import web

from . import __version__, climate
from .analysis import (
    Airing,
    OutdoorLookup,
    detect_airings,
    find_gaps,
    local_midnights,
    mould_share,
    outdoor_days,
    room_days,
)
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
DAILY_DAYS = (15, 31, 92, 366)
SPARK_SECONDS = 24 * 3600
SPARK_BUCKET = 1800
MOULD_SECONDS = 7 * 86400
AIRING_MARKER_SECONDS = 31 * 86400
"""Airings are marked in the history up to this range (beyond, there are too many)."""
OUTDOOR_FRESH_SECONDS = 75 * 60
MIN_GAP_SECONDS = 15 * 60
EVENTS_LIMIT = 50

_STORE: web.AppKey[HistoryStore] = web.AppKey("store")
_CLOCK: web.AppKey[Clock] = web.AppKey("clock")
_STATIC: web.AppKey[Path] = web.AppKey("static_dir")
_STATUS: web.AppKey[StatusProvider | None] = web.AppKey("status")
_INTERVAL: web.AppKey[int] = web.AppKey("interval")


def dew_point(temperature: float | None, humidity: float | None) -> float | None:
    """Dew point in °C, rounded to 0.1."""
    return _round(climate.dew_point(temperature, humidity), 1)


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
        _round(b.absolute_min),
        _round(b.absolute_avg),
        _round(b.absolute_max),
    ]


def _sensor_json(sensor: SensorInfo) -> dict[str, Any]:
    return {
        "id": sensor.id,
        "name": sensor.name,
        "kind": sensor.kind,
        "target_temperature": sensor.target_temperature,
        "surface_factor": (
            None
            if sensor.kind != "ble"
            else sensor.surface_factor or climate.DEFAULT_SURFACE_FACTOR
        ),
    }


def _airing_json(airing: Airing) -> dict[str, Any]:
    return {
        "sensor_id": airing.sensor_id,
        "start": airing.start,
        "lowest": airing.lowest,
        "drop": round(airing.drop, 1),
        "drying": round(airing.drying, 1),
        "recovery_minutes": airing.recovery_minutes,
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


def _midnight(now: int) -> int:
    return int(datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0).timestamp())


# -- API handlers -------------------------------------------------------------


def _air_json(
    store: HistoryStore, sensor: SensorInfo, now: int, outdoor: SensorInfo | None
) -> dict[str, Any]:
    """Mould risk, airing advice and today's airings of one indoor sensor (blocking)."""
    latest = store.latest(sensor.id)
    outside = store.latest_full(outdoor.id) if outdoor else None
    if outside is not None and now - outside.ts > OUTDOOR_FRESH_SECONDS:
        outside = None
    factor = sensor.surface_factor or climate.DEFAULT_SURFACE_FACTOR
    air = climate.assess(
        latest.temperature if latest else None,
        latest.humidity if latest else None,
        outside.temperature if outside else None,
        outside.humidity if outside else None,
        factor,
    )
    outdoor_rows = store.rows(outdoor.id, now - MOULD_SECONDS - 3600, now + 1) if outdoor else []
    lookup = OutdoorLookup(outdoor_rows, sensor.surface_factor)
    share = mould_share(store.rows(sensor.id, now - MOULD_SECONDS, now + 1), lookup)
    midnight = _midnight(now)
    today = [
        a
        for a in detect_airings(sensor.id, store.rows(sensor.id, midnight - 3600, now + 1))
        if a.start >= midnight
    ]
    return {
        "air": {
            "absolute_humidity": _round(air.absolute_humidity, 1),
            "outdoor_absolute_humidity": _round(air.outdoor_absolute_humidity, 1),
            "surface_humidity": _round(air.surface_humidity, 0),
            "level": air.level,
            "basis": air.basis,
            "ventilation": air.ventilation,
            "minutes": air.minutes,
        },
        "mould": None
        if share.share is None
        else {
            "threshold": climate.MOULD_LIMIT
            if share.basis == "surface"
            else climate.ROOM_MOULD_LIMIT,
            "basis": share.basis,
            "share": _round(share.share, 3),
            "hours": share.hours,
        },
        "airings": {"today": len(today), "last": _airing_json(today[-1]) if today else None},
    }


async def overview(request: web.Request) -> web.Response:
    store, now = request.app[_STORE], int(request.app[_CLOCK]())
    midnight = _midnight(now)
    sensors = await _run(store.sensors)
    outdoor = next((s for s in sensors if s.kind == "weather"), None)
    result = []
    for sensor in sensors:
        latest = await _run(store.latest_full, sensor.id)
        battery = await _run(store.last_battery, sensor.id)
        today = await _run(store.series, sensor.id, midnight, now + 1, DAY)
        spark = await _run(store.series, sensor.id, now - SPARK_SECONDS, now + 1, SPARK_BUCKET)
        extra: dict[str, Any] = {"air": None, "mould": None, "airings": None}
        if sensor.kind == "ble":
            extra = await _run(_air_json, store, sensor, now, outdoor)
        latest_json = None
        if latest is not None:
            latest_json = {
                "ts": latest.ts,
                "temperature": _round(latest.temperature, 1),
                "humidity": _round(latest.humidity, 1),
                "absolute_humidity": _round(
                    climate.absolute_humidity(latest.temperature, latest.humidity), 1
                ),
                "dew_point": dew_point(latest.temperature, latest.humidity),
            }
            if sensor.kind == "weather":
                latest_json |= {
                    "radiation": _round(latest.radiation, 0),
                    "wind": _round(latest.wind, 0),
                    "precipitation": _round(latest.precipitation, 1),
                }
        result.append(
            _sensor_json(sensor)
            | {
                "latest": latest_json,
                "battery": None if battery is None else {"ts": battery[0], "level": battery[1]},
                "today": _bucket_row(today[-1])[1:] if today else None,
                "spark": [[b.ts, _round(b.temperature_avg), _round(b.humidity_avg)] for b in spark],
            }
            | extra
        )
    return web.json_response(
        {
            "generated_at": now,
            "first_ts": await _run(store.first_timestamp),
            "sensors": result,
        }
    )


def _amount(bucket: Bucket, step: int, now: int) -> float | None:
    """Precipitation in mm in a bucket: the mean rate over its (elapsed) length."""
    if bucket.precipitation_avg is None:
        return None
    hours = max(0, min(now, bucket.ts + step) - bucket.ts) / 3600
    return round(bucket.precipitation_avg * hours, 2)


def _surface_series(
    rooms: list[Bucket], outdoor: list[Bucket], factor: float, step: int
) -> list[list[float | int | None]]:
    """Wall humidity per bucket, from the bucket means (outdoor carried forward)."""
    result: list[list[float | int | None]] = []
    j = 0
    for bucket in rooms:
        while j + 1 < len(outdoor) and outdoor[j + 1].ts <= bucket.ts:
            j += 1
        outside = None
        if (
            outdoor
            and outdoor[j].ts <= bucket.ts
            and bucket.ts - outdoor[j].ts <= max(step, OUTDOOR_FRESH_SECONDS)
        ):
            outside = outdoor[j].temperature_avg
        value = climate.surface_humidity(
            bucket.temperature_avg, bucket.humidity_avg, outside, factor
        )
        result.append([bucket.ts, _round(value, 1)])
    return result


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
    step = 86400 if selected.bucket == DAY else int(selected.bucket)
    sensors_info = await _run(store.sensors)
    buckets = {
        s.id: await _run(store.series, s.id, start, now + 1, selected.bucket) for s in sensors_info
    }
    outdoor = next((s for s in sensors_info if s.kind == "weather"), None)
    sensors = []
    airings: list[dict[str, Any]] = []
    for sensor in sensors_info:
        entry = _sensor_json(sensor) | {"points": [_bucket_row(b) for b in buckets[sensor.id]]}
        if sensor.kind == "weather":
            entry["weather"] = [
                [b.ts, _round(b.radiation_avg, 0), _round(b.wind_avg, 1), _amount(b, step, now)]
                for b in buckets[sensor.id]
            ]
        else:
            entry["surface"] = _surface_series(
                buckets[sensor.id],
                buckets[outdoor.id] if outdoor else [],
                sensor.surface_factor or climate.DEFAULT_SURFACE_FACTOR,
                step,
            )
            if now - start <= AIRING_MARKER_SECONDS:
                rows = await _run(store.rows, sensor.id, start, now + 1)
                airings += [_airing_json(a) for a in detect_airings(sensor.id, rows)]
        sensors.append(entry)

    recorded = await _run(store.recorded_timestamps, "ble", start, now + 1)
    events = await _run(store.events_between, start, now + 1)
    min_gap = max(MIN_GAP_SECONDS, round(2.5 * request.app[_INTERVAL]), step)
    gaps = find_gaps(recorded, min_gap=min_gap, end=now, events=events) if recorded else []
    return web.json_response(
        {
            "range": name,
            "bucket": selected.bucket,
            "start": start,
            "end": now,
            "sensors": sensors,
            "gaps": [[g.start, g.end, g.cause] for g in gaps],
            "airings": airings,
        }
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
                    [
                        p.hour,
                        _round(p.temperature_avg),
                        _round(p.humidity_avg),
                        p.samples,
                        _round(p.absolute_avg),
                    ]
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
                    [
                        c.day,
                        c.hour,
                        _round(c.temperature_avg),
                        _round(c.humidity_avg),
                        _round(c.absolute_avg),
                    ]
                    for c in cells
                ]
            }
        )
    return web.json_response({"days": days, "sensors": sensors})


def _rounded(row: Any) -> dict[str, Any]:
    return {k: round(v, 3) if isinstance(v, float) else v for k, v in asdict(row).items()}


class DailyCache:
    """Daily statistics per sensor. Past days do not change and are kept in memory;
    today is computed again on every request."""

    def __init__(self) -> None:
        self._days: dict[str, dict[str, dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def get(self, store: HistoryStore, days: int, now: int) -> list[dict[str, Any]]:
        today = datetime.fromtimestamp(now).date()
        wanted = local_midnights(today - timedelta(days=days - 1), today)
        with self._lock:
            missing = [(d, m) for d, m in wanted if d not in self._days or d == today.isoformat()]
            if missing:
                self._compute(store, missing, today, now)
            sensors = store.sensors()
            return [
                _sensor_json(sensor)
                | {
                    "days": [
                        self._days[d][sensor.id] for d, _ in wanted if sensor.id in self._days[d]
                    ]
                }
                for sensor in sensors
            ]

    def _compute(
        self, store: HistoryStore, missing: list[tuple[str, int]], today: date, now: int
    ) -> None:
        span = local_midnights(date.fromisoformat(missing[0][0]), today)
        start, end = span[0][1], now + 1
        sensors = store.sensors()
        outdoor = next((s for s in sensors if s.kind == "weather"), None)
        outdoor_rows = store.rows(outdoor.id, start - 3600, end) if outdoor else []
        computed: dict[str, dict[str, dict[str, Any]]] = {d: {} for d, _ in span}
        for sensor in sensors:
            if sensor.kind == "weather":
                stats: list[Any] = outdoor_days(
                    [r for r in outdoor_rows if r[0] >= start], span, now=now
                )
            else:
                stats = room_days(
                    sensor.id,
                    store.rows(sensor.id, start, end),
                    outdoor_rows,
                    span,
                    target=sensor.target_temperature,
                    surface_factor=sensor.surface_factor,
                )
            for item in stats:
                if item.samples:
                    computed[item.day][sensor.id] = _rounded(item)
        self._days.update(computed)


_DAILY: web.AppKey[DailyCache] = web.AppKey("daily")
_WARM_UP: web.AppKey[asyncio.Task[None]] = web.AppKey("warm_up")


async def daily(request: web.Request) -> web.Response:
    store, now = request.app[_STORE], int(request.app[_CLOCK]())
    days = _int_choice(request, "days", DAILY_DAYS, 15)
    sensors = await _run(request.app[_DAILY].get, store, days, now)
    return web.json_response({"days": days, "sensors": sensors})


async def export_csv(request: web.Request) -> web.Response:
    rows = await _run(lambda: list(request.app[_STORE].export_rows()))
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "time",
            "sensor",
            "temperature_c",
            "humidity_percent",
            "battery_percent",
            "radiation_w_m2",
            "wind_kmh",
            "precipitation_mm_h",
        ]
    )
    for name, ts, *values in rows:
        writer.writerow([datetime.fromtimestamp(ts).astimezone().isoformat(), name, *values])
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
    interval: int = 300,
) -> web.Application:
    """The dashboard app. Without ``status`` (demo mode) there is no live status.

    ``interval`` is the recording interval in seconds (to tell outages from the
    normal spacing of samples).
    """
    app = web.Application(middlewares=[headers_middleware])
    app[_STORE] = store
    app[_CLOCK] = clock
    app[_STATIC] = static_dir
    app[_STATUS] = status
    app[_INTERVAL] = interval
    app[_DAILY] = DailyCache()
    app.router.add_get("/api/overview", overview)
    app.router.add_get("/api/series", series)
    app.router.add_get("/api/profile", profile)
    app.router.add_get("/api/heatmap", heatmap)
    app.router.add_get("/api/daily", daily)
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
    """Start the dashboard server; call ``runner.cleanup()`` to stop it.

    The daily statistics of the past year are computed in the background right
    away, so the first visit does not wait for them (seconds on a Raspberry Pi).
    """
    app = create_app(store, **kwargs)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    await web.TCPSite(runner, host, port).start()
    _LOGGER.info("Dashboard on http://%s:%d", host, port)
    clock = app[_CLOCK]

    async def warm_up() -> None:
        try:
            await asyncio.to_thread(app[_DAILY].get, store, max(DAILY_DAYS), int(clock()))
        except Exception:  # only a cache: the request will compute it again
            _LOGGER.exception("Could not precompute the daily statistics")

    app[_WARM_UP] = asyncio.create_task(warm_up())
    return runner
