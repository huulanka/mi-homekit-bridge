from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from mi_homekit_bridge.climate import water_content
from mi_homekit_bridge.history import Event, HistoryStore, Sample, SensorInfo
from mi_homekit_bridge.status import BridgeStatus, SensorStatus
from mi_homekit_bridge.web import create_app, dew_point

NOW = 1_793_740_500  # 2026-11-03 21:15 UTC


@pytest.fixture
def store(tmp_path: Path) -> Iterator[HistoryStore]:
    db = HistoryStore(tmp_path / "h.db")
    db.upsert_sensors(
        [SensorInfo("A", "Living Room", "ble"), SensorInfo("weather", "Outdoor", "weather")]
    )
    db.add_samples(
        [Sample("A", NOW - 3600 + i * 300, 21.0 + i * 0.1, 50.0, 90) for i in range(12)]
        + [Sample("weather", NOW - 900, 4.0, 85.0)]
    )
    yield db
    db.close()


@pytest.fixture
def static_dir(tmp_path: Path) -> Path:
    root = tmp_path / "static"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<!doctype html><title>dashboard</title>")
    (root / "assets" / "app-1234.js").write_text("console.log(1)")
    (root / "assets" / "app-1234.js.br").write_bytes(b"brotli-bytes")
    (root / "favicon.svg").write_text("<svg/>")
    (root / ".secret").write_text("nope")
    return root


@pytest.fixture
async def client(store: HistoryStore, static_dir: Path) -> AsyncIterator[TestClient]:  # type: ignore[type-arg]
    app = create_app(store, static_dir=static_dir, clock=lambda: NOW)
    async with TestClient(TestServer(app)) as test_client:
        yield test_client


def test_dew_point() -> None:
    assert dew_point(20.0, 50.0) == pytest.approx(9.3, abs=0.1)
    assert dew_point(None, 50.0) is None
    assert dew_point(20.0, 0.0) is None


async def test_overview(client: TestClient) -> None:  # type: ignore[type-arg]
    response = await client.get("/api/overview")
    assert response.status == 200
    data = await response.json()
    sensors = {s["id"]: s for s in data["sensors"]}
    living = sensors["A"]
    assert living["kind"] == "ble"
    assert living["latest"]["temperature"] == pytest.approx(22.1)
    assert living["battery"] == {"ts": NOW - 300, "level": 90}
    assert living["latest"]["dew_point"] is not None
    assert living["latest"]["absolute_humidity"] == pytest.approx(water_content(22.1, 50), abs=0.1)
    assert len(living["spark"]) >= 2
    assert living["surface_factor"] == 0.7
    # 22.1 °C / 50 % inside, 4 °C outside: about 70 % at the coldest wall.
    air = living["air"]
    assert air["surface_humidity"] == pytest.approx(70, abs=1)
    assert (air["level"], air["basis"]) == ("warning", "surface")
    assert (air["ventilation"], air["minutes"]) == ("recommended", 5)
    assert living["airings"] == {"today": 0, "last": None}
    outdoor = sensors["weather"]
    assert outdoor["latest"]["temperature"] == 4.0
    assert outdoor["air"] is None
    assert outdoor["battery"] is None
    assert data["first_ts"] == NOW - 3600


async def test_series(client: TestClient) -> None:  # type: ignore[type-arg]
    data = await (await client.get("/api/series?range=24h")).json()
    assert data["bucket"] == 300
    living = next(s for s in data["sensors"] if s["id"] == "A")
    assert len(living["points"]) == 12
    _ts, t_min, t_avg, t_max, _h_min, h_avg, _h_max, _a_min, a_avg, _a_max = living["points"][0]
    assert (t_min, t_avg, t_max, h_avg) == (21.0, 21.0, 21.0, 50.0)
    assert a_avg == pytest.approx(water_content(21.0, 50.0), abs=0.01)
    surface = dict(living["surface"])
    assert surface[NOW - 3600] is None  # no outdoor value yet
    assert surface[NOW - 300] == pytest.approx(70, abs=1)
    outdoor = next(s for s in data["sensors"] if s["id"] == "weather")
    assert outdoor["weather"] == [[NOW - 900, None, None, None]]
    assert data["gaps"] == []
    assert data["airings"] == []

    yearly = await (await client.get("/api/series?range=1y")).json()
    assert yearly["bucket"] == "day"

    everything = await (await client.get("/api/series?range=all")).json()
    assert everything["start"] == NOW - 3600


async def test_profile_and_heatmap(client: TestClient) -> None:  # type: ignore[type-arg]
    profile = await (await client.get("/api/profile?days=7")).json()
    living = next(s for s in profile["sensors"] if s["id"] == "A")
    assert sum(point[3] for point in living["points"]) == 12

    heatmap = await (await client.get("/api/heatmap?days=14")).json()
    living = next(s for s in heatmap["sensors"] if s["id"] == "A")
    assert all(len(cell) == 5 for cell in living["cells"])


@pytest.mark.parametrize(
    "path", ["/api/series?range=2w", "/api/profile?days=5", "/api/heatmap?days=abc"]
)
async def test_invalid_parameters(client: TestClient, path: str) -> None:  # type: ignore[type-arg]
    response = await client.get(path)
    assert response.status == 400
    assert "error" in await response.json()


async def test_export_csv(client: TestClient) -> None:  # type: ignore[type-arg]
    response = await client.get("/api/export.csv")
    assert response.status == 200
    assert "attachment" in response.headers["Content-Disposition"]
    lines = (await response.text()).strip().splitlines()
    assert lines[0] == (
        "time,sensor,temperature_c,humidity_percent,battery_percent,"
        "radiation_w_m2,wind_kmh,precipitation_mm_h"
    )
    assert len(lines) == 1 + 13


async def test_security_and_cache_headers(client: TestClient) -> None:  # type: ignore[type-arg]
    api = await client.get("/api/health")
    assert api.headers["Cache-Control"] == "no-store"
    assert "default-src 'self'" in api.headers["Content-Security-Policy"]
    assert api.headers["X-Content-Type-Options"] == "nosniff"

    asset = await client.get("/assets/app-1234.js")
    assert asset.status == 200
    assert "immutable" in asset.headers["Cache-Control"]

    page = await client.get("/")
    assert page.status == 200
    assert page.headers["Cache-Control"] == "no-cache"


@pytest.mark.parametrize("path", ["/.secret", "/index.html", "/missing.png", "/..%2Fh.db"])
async def test_root_files_are_restricted(client: TestClient, path: str) -> None:  # type: ignore[type-arg]
    assert (await client.get(path)).status == 404


async def test_root_file_is_served(client: TestClient) -> None:  # type: ignore[type-arg]
    assert (await client.get("/favicon.svg")).status == 200


async def test_missing_frontend_build(store: HistoryStore, tmp_path: Path) -> None:
    app = create_app(store, static_dir=tmp_path / "nothing", clock=lambda: NOW)
    async with TestClient(TestServer(app)) as test_client:
        response = await test_client.get("/")
        assert response.status == 503
        assert (await test_client.get("/api/health")).status == 200


async def test_precompressed_assets_are_preferred(client: TestClient) -> None:  # type: ignore[type-arg]
    response = await client.get(
        "/assets/app-1234.js", headers={"Accept-Encoding": "br, gzip"}, auto_decompress=False
    )
    assert response.headers["Content-Encoding"] == "br"
    assert await response.read() == b"brotli-bytes"


def _status(*, bluetooth: str = "running", reporting: bool = True) -> BridgeStatus:
    return BridgeStatus(
        version="1.2.3",
        started_at=NOW - 3600,
        bluetooth_state=bluetooth,
        bluetooth_since=NOW - 600,
        bluetooth_error=None if bluetooth == "running" else "InProgress",
        scanning_mode="passive",
        last_advertisement=NOW - 2,
        homekit_paired=True,
        homekit_controllers=2,
        sensors=(SensorStatus("A", "Living Room", reporting, not reporting, NOW - 5, -70),),
    )


async def _live_client(store: HistoryStore, static_dir: Path, status: BridgeStatus) -> TestClient:  # type: ignore[type-arg]
    app = create_app(store, static_dir=static_dir, clock=lambda: NOW, status=lambda: status)
    client: TestClient = TestClient(TestServer(app))  # type: ignore[type-arg]
    await client.start_server()
    return client


async def test_status_and_health_when_everything_works(
    store: HistoryStore, static_dir: Path
) -> None:
    client = await _live_client(store, static_dir, _status())
    try:
        data = await (await client.get("/api/status")).json()
        assert data["bluetooth"]["state"] == "running"
        assert data["sensors"][0] == {
            "id": "A",
            "name": "Living Room",
            "reporting": True,
            "problem": False,
            "last_seen": NOW - 5,
            "rssi": -70,
        }
        health = await client.get("/api/health")
        assert health.status == 200
        assert (await health.json())["problems"] == []
    finally:
        await client.close()


async def test_health_reports_problems(store: HistoryStore, static_dir: Path) -> None:
    client = await _live_client(store, static_dir, _status(bluetooth="failed", reporting=False))
    try:
        health = await client.get("/api/health")
        assert health.status == 503
        body = await health.json()
        assert body["status"] == "degraded"
        assert body["problems"] == ["bluetooth", "sensor:A"]
    finally:
        await client.close()


async def test_no_live_status_in_demo_mode(client: TestClient) -> None:  # type: ignore[type-arg]
    assert (await client.get("/api/status")).status == 404
    assert (await client.get("/api/health")).status == 200


async def test_events(client: TestClient, store: HistoryStore) -> None:  # type: ignore[type-arg]
    store.add_event(Event(NOW - 60, "sensor_lost", "A", {"minutes": 60}))
    data = await (await client.get("/api/events")).json()
    assert data["events"] == [
        {"ts": NOW - 60, "kind": "sensor_lost", "sensor_id": "A", "data": {"minutes": 60}}
    ]


async def test_overview_has_target_and_mould_share(
    client: TestClient,  # type: ignore[type-arg]
    store: HistoryStore,
) -> None:
    store.upsert_sensors([SensorInfo("A", "Living Room", "ble", 20.0, 0.8)])
    # Two hours earlier, without outdoor data: judged by the room humidity (> 70 %).
    store.add_samples([Sample("A", NOW - 7200 + i * 300, 21.0, 72.0) for i in range(6)])
    sensors = {s["id"]: s for s in (await (await client.get("/api/overview")).json())["sensors"]}
    assert sensors["A"]["target_temperature"] == 20.0
    assert sensors["A"]["surface_factor"] == 0.8
    mould = sensors["A"]["mould"]
    assert (mould["basis"], mould["threshold"]) == ("room", 70.0)
    assert mould["share"] == pytest.approx(6 / 18, abs=0.001)
    assert mould["hours"] == 3
    assert sensors["weather"]["mould"] is None


async def test_series_marks_gaps_and_airings(
    client: TestClient,  # type: ignore[type-arg]
    store: HistoryStore,
) -> None:
    # Window opened two hours ago: -3 K and much drier within ten minutes.
    base = NOW - 3 * 3600
    store.add_samples(
        [Sample("A", base + i * 300, 22.0, 55.0) for i in range(6)]
        + [Sample("A", base + 1800, 19.0, 45.0), Sample("A", base + 2100, 19.5, 47.0)]
        + [Sample("A", base + 2100 + i * 300, 20.0 + i * 0.3, 50.0) for i in range(1, 7)]
    )
    store.add_event(Event(base + 4500, "bluetooth_reset", data={"error": "x"}))
    data = await (await client.get("/api/series?range=24h")).json()
    [airing] = data["airings"]
    assert airing["sensor_id"] == "A"
    assert (airing["start"], airing["lowest"]) == (base + 1500, base + 1800)
    assert airing["drop"] == 3.0
    assert airing["recovery_minutes"] == 35  # back above 21.4 °C (within 20 % of the drop)
    # Nothing recorded between the last airing sample and the fixture (one hour ago).
    assert data["gaps"] == [[base + 3900, NOW - 3600, "bluetooth"]]


async def test_daily(client: TestClient, store: HistoryStore) -> None:  # type: ignore[type-arg]
    store.upsert_sensors([SensorInfo("A", "Living Room", "ble", 21.5)])
    data = await (await client.get("/api/daily?days=15")).json()
    assert data["days"] == 15
    sensors = {s["id"]: s for s in data["sensors"]}
    [today] = sensors["A"]["days"]
    assert today["samples"] == 12
    assert today["temperature_avg"] == pytest.approx(21.55)
    # 21.0 to 22.1 °C against 21.5 ± 0.5 °C: only 22.1 °C is too warm.
    assert (today["cold"], today["on_target"], today["warm"]) == (
        0,
        pytest.approx(11 / 12, abs=0.001),
        pytest.approx(1 / 12, abs=0.001),
    )
    [outdoor] = sensors["weather"]["days"]
    assert outdoor["heating_degrees"] == 16.0
    assert (await client.get("/api/daily?days=7")).status == 400

    # Past days are cached, today is recomputed.
    store.add_samples([Sample("A", NOW - 60, 30.0, 50.0)])
    again = await (await client.get("/api/daily?days=15")).json()
    assert next(s for s in again["sensors"] if s["id"] == "A")["days"][0]["samples"] == 13
