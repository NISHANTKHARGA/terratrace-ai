"""Change detection on a controlled pair with a known answer."""
from __future__ import annotations

import numpy as np
import pytest

from app.change_detection.log_ratio import component_geometries, detect_log_ratio
from app.change_detection.segmentation import segment_water
from app.preprocessing.raster import render_backscatter_png, render_change_png


def _pair(shape=(160, 160)):
    """Uniform scene plus one block that drops by 10 dB between dates."""
    before = np.full(shape, -18.0, dtype="float32")
    after = before.copy()
    after[40:90, 40:90] -= 10.0
    valid = np.ones(shape, dtype=bool)
    return before, after, valid


def test_detects_known_block_and_reports_threshold():
    before, after, valid = _pair()
    res = detect_log_ratio(before, after, valid)
    block = res.mask[40:90, 40:90]
    assert block.mean() > 0.95, "the changed block must be flagged"
    assert res.mask[:30, :30].mean() < 0.05, "unchanged area must stay quiet"
    assert res.threshold_db >= 2.5
    assert res.changed_pixels == int(res.mask.sum())
    assert res.stats["changed_fraction"] == pytest.approx(
        res.changed_pixels / valid.sum(), rel=1e-4
    )


def test_no_change_yields_no_or_tiny_mask():
    before = np.full((160, 160), -18.0, dtype="float32")
    valid = np.ones_like(before, dtype=bool)
    res = detect_log_ratio(before, before + 0.05, valid)
    assert res.changed_pixels <= 0.01 * valid.sum()


def test_insufficient_valid_pixels_is_reported_not_guessed():
    before = np.full((50, 50), -18.0, dtype="float32")
    valid = np.zeros((50, 50), dtype=bool)
    res = detect_log_ratio(before, before, valid)
    assert res.changed_pixels == 0
    assert any("Insufficient" in n for n in res.notes)


def test_removed_global_offset_is_recorded_in_notes():
    before, after, valid = _pair()
    res = detect_log_ratio(before, after + 2.0, valid)  # scene-wide +2 dB step
    assert any("offset" in n.lower() for n in res.notes)
    # the known -8 dB relative block must still be detected after de-biasing
    assert res.mask[45:85, 45:85].mean() > 0.9


def test_component_geometries_vectorises_to_real_polygons():
    before, after, valid = _pair()
    res = detect_log_ratio(before, after, valid)
    from affine import Affine

    transform = Affine(0.001, 0.0, 85.0, 0.0, -0.001, 28.0)
    comps = component_geometries(res.mask, transform, min_area_km2=0.001)
    assert comps, "the changed block must vectorise into at least one polygon"
    assert comps[0]["geometry"].is_valid
    assert comps[0]["area_km2"] > 0
    assert comps[0]["geojson"]["type"] in ("Polygon", "MultiPolygon")


def test_water_segmentation_finds_dark_population():
    db = np.full((200, 200), -19.0, dtype="float32")
    db[20:80, 20:80] = -30.0
    valid = np.ones_like(db, dtype=bool)
    seg = segment_water(db, valid, hard_ceiling_db=-9.0, hard_floor_db=-34.0,
                        min_component_px=20)
    assert seg.used
    assert -34.0 <= seg.threshold_db <= -9.0
    assert seg.mask[20:80, 20:80].mean() > 0.9
    assert seg.mask[:10, :10].mean() < 0.1


def test_water_segmentation_reports_absence_honestly():
    db = np.full((200, 200), -14.0, dtype="float32")  # no dark population at all
    valid = np.ones_like(db, dtype=bool)
    seg = segment_water(db, valid, hard_ceiling_db=-9.0, hard_floor_db=-34.0,
                        min_component_px=20)
    if seg.used:
        assert seg.mask.sum() == 0 or seg.threshold_db < -25.0
    else:
        assert seg.notes, "an unused segmentation must say why"
