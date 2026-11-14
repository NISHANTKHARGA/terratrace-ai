"""Data-quality assessment for observation pairs / stacks.

All values are reported separately from detection confidence: quality describes
*the inputs*, never the strength of a claim.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from app.preprocessing.io import RasterScene
from app.preprocessing.raster import robust_shift


def overlap_ratio(a: np.ndarray, b: np.ndarray) -> float:
    """Fraction of pixels where both masks are True, relative to their union."""
    inter = np.logical_and(a, b).sum()
    union = np.logical_or(a, b).sum()
    return float(inter / union) if union else 0.0


def assess_pair(before: RasterScene, after: RasterScene) -> Dict[str, Any]:
    """Compatibility + quality assessment for a before/after pair."""
    notes: List[str] = []
    warnings: List[str] = []
    errors: List[str] = []

    if before.valid is None or after.valid is None:
        errors.append("Missing validity masks.")
        valid_before = valid_after = np.zeros((1, 1), dtype=bool)
    else:
        valid_before, valid_after = before.valid, after.valid

    if valid_before.shape != valid_after.shape:
        errors.append("Analysis grids differ between observations.")
        common = None
    else:
        common = np.logical_and(valid_before, valid_after)

    cov_b = float(valid_before.mean()) if valid_before.size else 0.0
    cov_a = float(valid_after.mean()) if valid_after.size else 0.0
    ov = overlap_ratio(valid_before, valid_after) if common is not None else 0.0
    common_frac = float(common.mean()) if common is not None and common.size else 0.0

    pols_b, pols_a = set(before.polarizations), set(after.polarizations)
    shared_pols = sorted(pols_b & pols_a)
    if not shared_pols:
        # scenes only store the single polarization actually read
        shared_pols = sorted({before.primary_pol} & {after.primary_pol}) or [before.primary_pol]
        notes.append("Only one polarization channel is available in both observations.")
    if before.orbit_mismatch_hint(after):
        warnings.append(
            "Observations come from different orbit directions/geometry; radiometric "
            "comparison is less reliable and thresholds are widened."
        )
    if before.mission != after.mission:
        warnings.append(
            f"Cross-mission comparison ({before.mission} → {after.mission}): radiometric "
            "calibration differs, so absolute backscatter levels are not comparable."
        )
    if common_frac < 0.5:
        errors.append(
            f"Co-valid coverage is only {common_frac:.0%} — the two observations do not "
            "overlap sufficiently for a quantitative change statement."
        )

    b_db, a_db = before.db(before.primary_pol), after.db(after.primary_pol)
    shift = robust_shift(b_db, a_db, common) if common is not None else 0.0
    if abs(shift) > 1.5:
        warnings.append(
            f"Median backscatter offset between dates is {shift:+.2f} dB (orbit/soil-moisture/"
            "incidence differences). The detector removes this global offset; changes smaller "
            "than it cannot be separated from calibration drift."
        )

    # simple quality score (0..1) — data quality only, not confidence
    quality = float(
        np.clip(
            0.45 * common_frac
            + 0.25 * min(1.0, cov_b)
            + 0.25 * min(1.0, cov_a)
            + 0.05 * (1.0 if len(shared_pols) >= 1 else 0.0)
            - 0.15 * min(1.0, len(warnings) / 3.0),
            0.0,
            1.0,
        )
    )
    days = None
    try:
        from datetime import datetime

        t0 = datetime.fromisoformat(before.datetime.replace("Z", "+00:00"))
        t1 = datetime.fromisoformat(after.datetime.replace("Z", "+00:00"))
        days = round(abs((t1 - t0).total_seconds()) / 86400.0, 2)
    except Exception:
        pass

    if quality < 0.3 or errors:
        status = "rejected_poor_quality"
    elif days is None or days < 1:
        status = "insufficient_data"
    else:
        status = "candidate_detected"

    return {
        "common_fraction": round(common_frac, 4),
        "coverage_before": round(cov_b, 4),
        "coverage_after": round(cov_a, 4),
        "overlap": round(ov, 4),
        "shared_polarizations": shared_pols,
        "median_shift_db": round(shift, 3),
        "days_between": days,
        "quality_score": round(quality, 3),
        "status": status,
        "notes": notes,
        "warnings": warnings,
        "errors": errors,
        "common_mask": common,
    }
