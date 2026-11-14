"""Multi-temporal log-ratio change detection on calibrated backscatter (dB)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
from scipy import ndimage

from app.core.geo import area_km2
from app.preprocessing.raster import mask_to_polygons, robust_mad, robust_shift


@dataclass
class ChangeResult:
    mask: np.ndarray                 # any significant change
    decrease_mask: np.ndarray        # after < before (smoothing/wetting/clearing...)
    increase_mask: np.ndarray        # after > before (roughening/double bounce...)
    diff_db: np.ndarray              # centred difference (NaN where invalid)
    threshold_db: float
    shift_db: float
    method: str
    stats: Dict[str, Any] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)

    @property
    def changed_pixels(self) -> int:
        return int(self.mask.sum())


def detect_log_ratio(
    before_db: np.ndarray,
    after_db: np.ndarray,
    valid: np.ndarray,
    *,
    k: float = 3.5,
    min_db: float = 2.5,
    min_component_px: int = 24,
) -> ChangeResult:
    """Robust dB log-ratio detection.

    1. remove the global radiometric offset between dates (robust median),
    2. scale a threshold with the MAD of the difference distribution,
    3. require changes to exceed both a statistical and an absolute floor,
    4. drop isolated speckle-sized components (morphological clean-up).
    """
    valid = valid & np.isfinite(before_db) & np.isfinite(after_db)
    diff = np.full(before_db.shape, np.nan, dtype="float32")
    if valid.sum() < 100:
        empty = np.zeros(before_db.shape, dtype=bool)
        return ChangeResult(empty, empty, empty, diff, min_db, 0.0, "log_ratio_mad",
                            notes=["Insufficient co-valid pixels for log-ratio analysis."])

    diff[valid] = (after_db[valid] - before_db[valid]).astype("float32")
    shift = robust_shift(before_db, after_db, valid)
    mad = robust_mad(diff[valid] - shift)
    thr = float(max(min_db, k * mad))
    centered = diff - shift

    decr = valid & (centered < -thr)
    incr = valid & (centered > thr)
    mask = decr | incr

    decr = _drop_small(decr, min_component_px)
    incr = _drop_small(incr, min_component_px)
    mask = decr | incr

    changed = mask[valid]
    frac = float(changed.mean()) if changed.size else 0.0
    notes: List[str] = []
    notes.append(
        f"Global offset {shift:+.2f} dB removed; threshold ±{thr:.2f} dB "
        f"(MAD={mad:.2f} dB, k={k})."
    )
    if frac > 0.35:
        notes.append(
            "More than 35% of the region is flagged as changed — this usually means the "
            "threshold absorbed scene-wide differences (orbit, soil moisture, incidence). "
            "Interpret individual polygons with caution."
        )
    stats = {
        "changed_fraction": round(frac, 5),
        "decrease_fraction": round(float((decr[valid]).mean()), 5) if valid.sum() else 0.0,
        "increase_fraction": round(float((incr[valid]).mean()), 5) if valid.sum() else 0.0,
        "mean_change_db": float(np.nanmean(centered[mask])) if mask.any() else 0.0,
        "median_change_db": float(np.nanmedian(centered[mask])) if mask.any() else 0.0,
        "p95_abs_change_db": float(np.nanpercentile(np.abs(centered[mask]), 95)) if mask.any() else 0.0,
        "median_shift_db": shift,
        "threshold_db": thr,
        "mad_db": mad,
    }
    return ChangeResult(mask, decr, incr, centered, thr, shift, "log_ratio_mad", stats, notes)


def _drop_small(mask: np.ndarray, min_px: int) -> np.ndarray:
    if min_px <= 1 or not mask.any():
        return mask
    labeled, n = ndimage.label(mask)
    if n == 0:
        return mask
    sizes = np.bincount(labeled.ravel())
    keep = sizes >= min_px
    keep[0] = False
    return keep[labeled]


def component_geometries(
    mask: np.ndarray, transform, *, min_area_km2: float = 0.02, max_components: int = 8
):
    """Vectorise the change mask into individual candidate regions."""
    from shapely.geometry import MultiPolygon, Polygon

    if not mask.any():
        return []
    out: List[Dict[str, Any]] = []
    labeled, n = ndimage.label(mask)
    if n == 0:
        return []
    sizes = np.bincount(labeled.ravel())
    order = np.argsort(sizes[1:])[::-1][:max_components] + 1
    for idx in order:
        if sizes[idx] <= 4:
            continue
        sub = labeled == int(idx)
        geojson, geom, area = mask_to_polygons(sub, transform, min_area_km2=min_area_km2)
        if geom is None or geom.is_empty or area < min_area_km2:
            continue
        out.append({"geojson": geojson, "geometry": geom, "area_km2": area,
                    "pixels": int(sizes[idx]), "label": int(idx)})
    out.sort(key=lambda d: d["area_km2"], reverse=True)
    return out
