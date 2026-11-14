"""Shared helpers used by several specialist agents (never the whole model)."""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from shapely.geometry import box

from app.change_detection.log_ratio import component_geometries
from app.core.geo import area_km2, to_geojson


def confidence_score(
    *,
    magnitude_db: float,
    area_km2_: float,
    quality: float,
    persistent: bool,
    corroborating: int = 0,
    penalty: float = 0.0,
) -> float:
    """Heuristic **detection** score in [0, 1].

    This is an explicitly weighted heuristic used to rank candidates. It is not
    a calibrated probability and must never be reported as one.
    """
    mag = min(1.0, abs(magnitude_db) / 8.0)                 # 8 dB ≈ fully saturated
    area = min(1.0, math.log10(max(area_km2_, 0.01) + 1) / 2.0)
    pers = 1.0 if persistent else 0.6
    corrob = min(1.0, 0.15 * corroborating)
    raw = 0.34 * mag + 0.24 * area + 0.22 * max(0.0, quality) + 0.20 * pers + 0.10 * corrob
    return round(float(np.clip(raw - penalty, 0.0, 1.0)), 3)


def severity_from(area_km2_: float, magnitude_db: float, qualitative: Optional[str] = None) -> str:
    if qualitative in ("low", "moderate", "high"):
        return qualitative
    score = math.log10(max(area_km2_, 0.01) + 1) * 0.7 + min(abs(magnitude_db), 12) / 12.0
    if score < 1.2:
        return "low"
    if score < 2.2:
        return "moderate"
    return "high"


def regions(
    mask: np.ndarray,
    transform,
    *,
    region: Any = None,
    min_area_km2: float = 0.02,
    max_components: int = 6,
) -> List[Dict[str, Any]]:
    """Vectorised candidate regions, clipped to the analysis region."""
    out = component_geometries(mask, transform, min_area_km2=min_area_km2,
                               max_components=max_components)
    clipped: List[Dict[str, Any]] = []
    for item in out:
        geom = item["geometry"]
        if region is not None and not getattr(region, "is_empty", True):
            try:
                if not geom.intersects(region):
                    continue
                geom = geom.intersection(region)
            except Exception:
                pass
        from app.core.geo import parse_multi_polygon
        geom = parse_multi_polygon(geom)
        if geom.is_empty or area_km2(geom) < min_area_km2:
            continue
        clipped.append({**item, "geometry": geom, "geojson": to_geojson(geom),
                        "area_km2": area_km2(geom)})
    clipped.sort(key=lambda d: d["area_km2"], reverse=True)
    return clipped


def mean_in(arr: np.ndarray, mask: np.ndarray) -> Optional[float]:
    sel = arr[mask & np.isfinite(arr)]
    return float(np.mean(sel)) if sel.size else None


def pct_in(arr: np.ndarray, mask: np.ndarray, q: float) -> Optional[float]:
    sel = arr[mask & np.isfinite(arr)]
    return float(np.percentile(sel, q)) if sel.size else None


def persistence_note(ctx_dates: Sequence[str]) -> Dict[str, Any]:
    if len(ctx_dates) < 2:
        return {"dates_supporting": list(ctx_dates), "days_between": None, "persistent": False}
    from datetime import datetime

    def _p(s: str) -> datetime:
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return datetime.fromisoformat(s[:19])

    try:
        days = round(abs((_p(ctx_dates[-1]) - _p(ctx_dates[0])).total_seconds()) / 86400.0, 2)
    except Exception:
        days = None
    return {"dates_supporting": list(ctx_dates), "days_between": days,
            "persistent": bool(days and days >= 1)}


def bbox_of(region: Any) -> List[float]:
    if region is None or getattr(region, "is_empty", True):
        return []
    return [float(v) for v in region.bounds]


def frame_region(ctx) -> Any:
    """The analysis region (polygon) or its bbox polygon."""
    if ctx.region is not None and not getattr(ctx.region, "is_empty", True):
        return ctx.region
    w, s, e, n = ctx.bbox
    return box(w, s, e, n)


def days_between(dates: Sequence[str]) -> Optional[float]:
    if len(dates) < 2:
        return None
    from datetime import datetime

    def _p(s: str) -> datetime:
        try:
            return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        except Exception:
            return datetime.fromisoformat(str(s)[:19])

    try:
        return round(abs((_p(dates[-1]) - _p(dates[0])).total_seconds()) / 86400.0, 2)
    except Exception:
        return None
