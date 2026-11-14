"""SAR water segmentation (Otsu on dB backscatter) + inundation differencing."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from scipy import ndimage
from skimage.filters import threshold_otsu
from skimage.morphology import binary_opening, disk, remove_small_objects


@dataclass
class WaterResult:
    mask: np.ndarray
    threshold_db: float
    used: bool
    method: str = "otsu_db_threshold"
    notes: List[str] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)


def segment_water(
    db: np.ndarray,
    valid: np.ndarray,
    *,
    hard_ceiling_db: float = -9.0,
    hard_floor_db: float = -34.0,
    min_component_px: int = 30,
) -> WaterResult:
    """Identify open surface water from calibrated backscatter.

    Water produces specular reflection away from the sensor, so it appears as a
    distinct *dark* population. We fit an Otsu threshold to the dB histogram but
    constrain it to a physically plausible range; when no such bimodal class is
    present we return an empty mask and say so rather than forcing a result.
    """
    vals = db[valid & np.isfinite(db)]
    notes: List[str] = []
    if vals.size < 500:
        return WaterResult(np.zeros(db.shape, dtype=bool), float("nan"), False,
                           notes=["Too few valid pixels for water segmentation."])
    try:
        t = float(threshold_otsu(vals))
    except Exception:
        return WaterResult(np.zeros(db.shape, dtype=bool), float("nan"), False,
                           notes=["Otsu thresholding failed on this histogram."])

    if not (hard_floor_db < t < hard_ceiling_db):
        notes.append(
            f"Otsu threshold {t:.1f} dB falls outside the physically plausible open-water "
            f"range ({hard_floor_db:.0f}…{hard_ceiling_db:.0f} dB): no distinct dark water "
            "population in this scene."
        )
        return WaterResult(np.zeros(db.shape, dtype=bool), t, False, notes=notes)

    mask = valid & np.isfinite(db) & (db <= t)

    # Otsu alone will happily split a uniform scene; require a genuinely distinct
    # dark population. This protects flat or unimodal backscatter scenes from being
    # labelled as water merely because every pixel lies inside the allowed range.
    low_vals = vals[vals <= t]
    high_vals = vals[vals > t]
    low_fraction = low_vals.size / vals.size if vals.size else 0.0
    separation = (
        float(np.median(high_vals) - np.median(low_vals))
        if low_vals.size and high_vals.size
        else 0.0
    )
    if low_vals.size == 0 or high_vals.size == 0 or low_fraction > 0.85 or separation < 4.0:
        notes.append(
            "No distinct dark water population is separated from the surrounding "
            f"backscatter distribution (separation {separation:.1f} dB); water "
            "segmentation is not asserted."
        )
        return WaterResult(np.zeros(db.shape, dtype=bool), t, False, notes=notes)

    mask = binary_opening(mask, disk(1))
    mask = remove_small_objects(mask, max_size=min_component_px)
    mask = ndimage.binary_closing(mask, disk(2))
    coverage = float(mask.mean())
    notes.append(f"Otsu threshold {t:.1f} dB; water-like pixels {coverage:.1%} of region.")
    if coverage > 0.85:
        notes.append(
            "Segmentation flagged most of the region as water — the threshold is probably "
            "absorbing terrain/speckle effects, treat the extent as unverified."
        )
    return WaterResult(mask, t, True, notes=notes,
                       stats={"coverage": round(coverage, 4), "threshold_db": round(t, 2)})


def inundation_masks(before: WaterResult, after: WaterResult) -> Dict[str, np.ndarray]:
    """Newly flooded, persistent, and receded water between two dates."""
    if not (before.used and after.used):
        z = np.zeros(before.mask.shape, dtype=bool)
        return {"new_water": z, "persistent_water": z, "receded_water": z}
    return {
        "new_water": after.mask & ~before.mask,
        "persistent_water": after.mask & before.mask,
        "receded_water": before.mask & ~after.mask,
    }


def connected_regions(mask: np.ndarray, min_px: int = 30) -> Tuple[np.ndarray, int]:
    labeled, n = ndimage.label(mask)
    if n == 0:
        return labeled, 0
    sizes = np.bincount(labeled.ravel())
    keep = np.where(sizes >= min_px)[0]
    keep = keep[keep > 0]
    remap = np.zeros(sizes.shape, dtype=np.int32)
    remap[keep] = np.arange(1, len(keep) + 1)
    return remap[labeled], len(keep)
