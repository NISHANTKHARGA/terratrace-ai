"""Renderer tests: PNG generation must not depend on removed Matplotlib APIs."""
from __future__ import annotations

import numpy as np


def test_backscatter_and_change_images_are_pngs():
    from app.preprocessing.raster import render_backscatter_png, render_change_png

    db = np.linspace(-35, -5, 10000, dtype=np.float32).reshape(100, 100)
    mask = np.zeros((100, 100), dtype=bool)
    mask[40:60, 40:60] = True

    before = render_backscatter_png(db)
    after = render_backscatter_png(db + 0.4)
    change = render_change_png(db, db + 0.4, mask)

    for payload in (before, after, change):
        assert payload.startswith(b"\x89PNG")
        assert len(payload) > 100
