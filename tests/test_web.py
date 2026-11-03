from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from mi_homekit_bridge.history import HistoryStore, Sample, SensorInfo
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
    assert living["latest"]["battery"] == 90
    assert living["latest"]["dew_point"] is not None
    assert len(living["spark"]) >= 2
    assert sensors["weather"]["latest"]["temperature"] == 4.0
    assert data["first_ts"] == NOW - 3600


async def test_series(client: TestClient) -> None:  # type: ignore[type-arg]
    data = await (await client.get("/api/series?range=24h")).json()
    assert data["bucket"] == 300
    living = next(s for s in data["sensors"] if s["id"] == "A")
    assert len(living["points"]) == 12
    _ts, t_min, t_avg, t_max, _h_min, h_avg, _h_max = living["points"][0]
    assert (t_min, t_avg, t_max, h_avg) == (21.0, 21.0, 21.0, 50.0)

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
    assert all(len(cell) == 4 for cell in living["cells"])


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
    assert lines[0] == "time,sensor,temperature_c,humidity_percent,battery_percent"
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
