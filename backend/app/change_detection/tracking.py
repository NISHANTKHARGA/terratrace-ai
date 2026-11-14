"""Feature tracking (texture registration) between two SAR observations.

This is *image matching*, not interferometry: offsets are derived from the
correlation of radar texture between dates. Offsets are reported in pixels and
in ground metres using the local pixel size, always with an explicit caveat.

They must NOT be presented as InSAR phase displacement (that requires
interferometric processing — see Agent 05).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np
from skimage.registration import phase_cross_correlation
from skimage.restoration import denoise_tv_chambolle

from app.preprocessing.raster import robust_mad


def _local_pixel_m(transform, lat_mid: float) -> float:
    """Ground length (m) of one pixel along the x axis at a given latitude."""
    import math
    return abs(transform.a) * 111_320.0 * math.cos(math.radians(lat_mid))


def track_offsets(
    before_db: np.ndarray,
    after_db: np.ndarray,
    valid: np.ndarray,
    *,
    window: int = 128,
    step: int = 128,
    max_shift: int = 20,
    min_valid_frac: float = 0.7,
) -> Dict[str, Any]:
    """Per-window phase-correlation offsets with a confidence score."""
    h, w = before_db.shape
    offsets: List[Dict[str, Any]] = []
    used = 0
    for r0 in range(0, h - window + 1, step):
        for c0 in range(0, w - window + 1, step):
            sl = (slice(r0, r0 + window), slice(c0, c0 + window))
            v = valid[sl]
            if v.mean() < min_valid_frac:
                continue
            a = np.nan_to_num(before_db[sl], nan=np.nanmedian(before_db[sl]))
            b = np.nan_to_num(after_db[sl], nan=np.nanmedian(after_db[sl]))
            a = denoise_tv_chambolle(a.astype("float64"), weight=0.3)
            b = denoise_tv_chambolle(b.astype("float64"), weight=0.3)
            if np.std(a) < 0.5 or np.std(b) < 0.5:
                continue  # flat surfaces carry no trackable texture
            try:
                shift, error, _ = phase_cross_correlation(
                    a, b, upsample_factor=1, normalization=None,
                    reference_mask=v, moving_mask=v,
                )
            except Exception:
                continue
            dy, dx = float(shift[0]), float(shift[1])
            if abs(dy) > max_shift or abs(dx) > max_shift:
                continue
            conf = float(np.clip(1.0 - float(error), 0.0, 1.0)) if np.isfinite(error) else 0.0
            offsets.append({"row": r0, "col": c0, "dy_px": dy, "dx_px": dx, "confidence": conf,
                            "error": float(error) if np.isfinite(error) else None})
            used += 1

    if used == 0:
        return {"windows": 0, "offsets": [], "median_dx_px": None, "median_dy_px": None,
                "method": "phase_cross_correlation", "confidence": 0.0,
                "notes": ["No textured, co-valid window was trackable between these dates."]}

    dx = np.array([o["dx_px"] for o in offsets])
    dy = np.array([o["dy_px"] for o in offsets])
    conf = np.array([o["confidence"] for o in offsets])
    keep = conf >= np.percentile(conf, 50)
    med_dx = float(np.median(dx[keep])) if keep.any() else float(np.median(dx))
    med_dy = float(np.median(dy[keep])) if keep.any() else float(np.median(dy))
    spread = float(robust_mad(np.concatenate([dx, dy])))
    notes = [
        f"{used} textured windows registered; median offset "
        f"({med_dx:+.2f}, {med_dy:+.2f}) px, robust spread {spread:.2f} px.",
        "Offsets come from texture correlation (feature tracking), NOT from interferometric "
        "phase — do not read them as InSAR line-of-sight displacement.",
    ]
    return {
        "windows": used,
        "offsets": offsets,
        "median_dx_px": med_dx,
        "median_dy_px": med_dy,
        "spread_px": spread,
        "confidence": round(float(np.mean(conf[keep])) if keep.any() else float(np.mean(conf)), 3),
        "method": "phase_cross_correlation",
        "notes": notes,
    }


def offsets_to_ground(tracking: Dict[str, Any], transform, lat_mid: float) -> Dict[str, Any]:
    """Convert pixel offsets to metres using the local pixel size (approximate)."""
    if tracking.get("median_dx_px") is None:
        return {**tracking, "median_dx_m": None, "median_dy_m": None, "pixel_size_m": None}
    px_m = _local_pixel_m(transform, lat_mid)
    # y pixel size in degrees → metres
    import math
    py_m = abs(transform.e) * 110_570.0
    return {
        **tracking,
        "median_dx_m": round(tracking["median_dx_px"] * px_m, 2),
        "median_dy_m": round(tracking["median_dy_px"] * py_m, 2),
        "pixel_size_m": round(px_m, 2),
    }
