"""Shared fixtures.

The environment is isolated *before* any application module is imported: a
temporary SQLite database, cache and artifact directory are configured through
the same environment variables the application reads in production. Network
access is stubbed out so the suite is deterministic and offline.

The synthetic raster pair used below is a **unit-test fixture** — it exists to
exercise agent logic on controlled numbers. It is never stored in the database,
never published as a finding, and never presented as an observation.
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="terratrace_tests_")
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(_TMP, "test.db")
os.environ["CACHE_DIR"] = os.path.join(_TMP, "cache")
os.environ["ARTIFACTS_DIR"] = os.path.join(_TMP, "artifacts")
os.environ["LOG_LEVEL"] = "WARNING"
os.environ.setdefault("ENABLE_COPERNICUS", "false")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from affine import Affine  # noqa: E402
from shapely.geometry import box  # noqa: E402

from app.agents.base import AgentContext  # noqa: E402
from app.change_detection.log_ratio import detect_log_ratio  # noqa: E402
from app.change_detection.segmentation import segment_water  # noqa: E402
from app.preprocessing.io import RasterScene  # noqa: E402
from app.preprocessing.quality import assess_pair  # noqa: E402

from app.database.seed import seed_all  # noqa: E402
from app.database.session import init_db  # noqa: E402

init_db()
seed_all(probe_sources=False)

BBOX = (85.2, 27.55, 85.5, 27.75)
SIZE = 256


def _scene(datetime_: str, lake: slice, bright: bool) -> RasterScene:
    rng = np.random.default_rng(7 if bright else 3)
    land = 0.012
    speckle = rng.lognormal(mean=0.0, sigma=0.35, size=(SIZE, SIZE)).astype("float32")
    linear = (land * speckle).astype("float32")
    linear[lake] = 0.0015  # open water: specular, radar-dark
    if bright:
        linear[180:225, 180:225] *= 9.0  # roughened/brightened surface
    transform = Affine(0.3 / SIZE, 0.0, BBOX[0], 0.0, -0.2 / SIZE, BBOX[3])
    return RasterScene(
        observation_id=f"test_{datetime_}", source="planetary_computer",
        mission="SENTINEL-1", product_type="RTC-S1", datetime=datetime_,
        polarizations=["VV", "VH"], url="https://example.invalid/scene.tif",
        platform="Sentinel-1A", orbit_direction="DESCENDING",
        arrays={"VV": linear, "VH": (linear * 0.35).astype("float32")},
        valid=np.ones((SIZE, SIZE), dtype=bool), transform=transform,
    )


@pytest.fixture(scope="session")
def pair_ctx() -> AgentContext:
    """A controlled before/after pair shaped exactly like a production run."""
    before = _scene("2024-06-01T02:00:00Z", slice(60, 110), bright=False)
    after = _scene("2024-06-25T02:00:00Z", slice(50, 132), bright=True)
    quality = assess_pair(before, after)
    valid = quality["common_mask"]
    change = detect_log_ratio(before.db("VV"), after.db("VV"), valid)
    water_before = segment_water(before.db("VV"), valid, hard_ceiling_db=-9.0,
                                 hard_floor_db=-34.0, min_component_px=30)
    water_after = segment_water(after.db("VV"), valid, hard_ceiling_db=-9.0,
                                hard_floor_db=-34.0, min_component_px=30)
    return AgentContext(
        job_id="job_test_fixture", bbox=BBOX, region=box(*BBOX), size=SIZE,
        observations=[before, after], before=before, after=after,
        quality=quality, change=change, water_before=water_before,
        water_after=water_after, config={},
    )


@pytest.fixture(scope="session")
def client():
    """Offline TestClient: no source probes, no background network work."""
    import app.main as main_mod

    original_warm = main_mod._warm_sources
    main_mod._warm_sources = lambda: None
    try:
        from fastapi.testclient import TestClient

        with TestClient(main_mod.app) as c:
            from app.data_sources.registry import registry
            from app.schemas.api import DataSourceStatusOut
            import time as _time

            now = _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime())
            registry._status_cache = {
                "nasa_cmr": DataSourceStatusOut(
                    id="nasa_cmr", name="NASA Earthdata CMR", description="test",
                    provider="NASA", status="operational", detail="stubbed for tests",
                    checked_at=now, auth_required=False,
                ),
                "earthdata_login": DataSourceStatusOut(
                    id="earthdata_login", name="Earthdata Login", description="test",
                    provider="NASA", status="requires_credentials", detail="stubbed",
                    checked_at=now, auth_required=True,
                ),
            }
            registry._status_time = _time.time()
            yield c
    finally:
        main_mod._warm_sources = original_warm


@pytest.fixture()
def offline_discovery(monkeypatch):
    """Replace the live catalogue fan-out with a small fixed observation set."""
    from app.api import observations as obs_module
    from app.schemas.api import ObservationOut, ObservationQuality

    items = [
        ObservationOut(
            id="obs_test_1", provider_id="G1000000001-TEST", mission="SENTINEL-1",
            platform="Sentinel-1A", source="planetary_computer", product_type="RTC-S1",
            processing_level="L2", datetime="2024-06-25T02:00:00Z",
            polarizations=["VV", "VH"], orbit_direction="DESCENDING",
            bbox=list(BBOX), url="https://example.invalid/a.tif",
            requires_credentials=False, quality=ObservationQuality(),
        ),
        ObservationOut(
            id="obs_test_2", provider_id="G1000000002-TEST", mission="NISAR",
            platform="NISAR", source="nasa_cmr", product_type="RSLC",
            processing_level="L1", datetime="2026-06-25T02:00:00Z",
            polarizations=["HH", "HV"], bbox=list(BBOX),
            url="https://example.invalid/b.h5", requires_credentials=True,
            quality=ObservationQuality(),
        ),
    ]
    monkeypatch.setattr(obs_module, "discover",
                        lambda **kwargs: {"observations": items, "sources_checked": []})
    return items
