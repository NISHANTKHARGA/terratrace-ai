"""Raster maths, geospatial vectorisation and honest SAR image rendering."""
from __future__ import annotations

import io as _io
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from affine import Affine
from rasterio import features
from shapely.geometry import MultiPolygon, Polygon, mapping, shape
from shapely.ops import unary_union

from app.core.geo import area_km2, centroid_lonlat, parse_multi_polygon


def to_db(linear: np.ndarray) -> np.ndarray:
    out = np.full(linear.shape, np.nan, dtype="float32")
    ok = np.isfinite(linear) & (linear > 0)
    out[ok] = (10.0 * np.log10(linear[ok])).astype("float32")
    return out


def valid_mask(arr: np.ndarray) -> np.ndarray:
    return np.isfinite(arr) & (arr != 0)


def robust_shift(before: np.ndarray, after: np.ndarray, valid: np.ndarray) -> float:
    """Median (after − before) over co-valid pixels: global radiometric offset."""
    both = valid & np.isfinite(before) & np.isfinite(after)
    if both.sum() < 100:
        return 0.0
    diff = after[both] - before[both]
    return float(np.median(diff))


def robust_mad(values: np.ndarray) -> float:
    v = values[np.isfinite(values)]
    if v.size == 0:
        return 0.0
    med = np.median(v)
    return float(np.median(np.abs(v - med)) * 1.4826)


def percentile_stretch(db: np.ndarray, lo: float = 2.0, hi: float = 98.0) -> Tuple[np.ndarray, float, float]:
    v = db[np.isfinite(db)]
    if v.size == 0:
        return np.zeros_like(db), 0.0, 0.0
    vmin = float(np.percentile(v, lo))
    vmax = float(np.percentile(v, hi))
    if vmax - vmin < 1e-6:
        vmax = vmin + 1e-6
    stretched = np.clip((db - vmin) / (vmax - vmin), 0, 1)
    stretched[~np.isfinite(db)] = np.nan
    return stretched.astype("float32"), vmin, vmax


def render_backscatter_png(db: np.ndarray, lo: float = 2.0, hi: float = 98.0) -> bytes:
    """Grayscale SAR backscatter (dB) quicklook — linear-in-dB ramp, no false colour."""
    from PIL import Image

    stretched, vmin, vmax = percentile_stretch(db, lo, hi)
    gray = (np.nan_to_num(stretched, nan=0.0) * 255.0).astype("uint8")
    img = np.repeat(gray[:, :, np.newaxis], 3, axis=2)
    # mark nodata as midnight navy so gaps are obvious
    nodata = ~np.isfinite(db)
    img[nodata] = (11, 18, 32)
    buf = _io.BytesIO()
    Image.fromarray(img).save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def render_change_png(
    before_db: np.ndarray,
    after_db: np.ndarray,
    mask: np.ndarray,
    *,
    overlay_alpha: float = 0.55,
) -> bytes:
    """Side-by-side(ish) derived layer: after image with the change mask in amber."""
    from PIL import Image

    stretched, _, _ = percentile_stretch(after_db)
    gray = (np.nan_to_num(stretched, nan=0.0) * 255.0).astype("float32")
    img = np.repeat(gray[:, :, np.newaxis], 3, axis=2)
    nodata = ~np.isfinite(after_db)
    img[nodata] = [11, 18, 32]
    colour = np.array([224, 164, 88], dtype="float32")  # amber = "review"
    m = mask & np.isfinite(after_db)
    img[m] = img[m] * (1 - overlay_alpha) + colour * overlay_alpha
    buf = _io.BytesIO()
    Image.fromarray(img.astype("uint8")).save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def mask_to_polygons(
    mask: np.ndarray,
    transform: Affine,
    *,
    min_area_km2: float = 0.01,
    simplify_tolerance: float = 0.0,
) -> Tuple[Optional[Dict[str, Any]], Any, float]:
    """Vectorise a boolean mask on the lon/lat analysis grid.

    Returns (geojson, shapely geometry, area_km2).
    """
    if mask is None or not mask.any():
        return None, Polygon(), 0.0
    mask_u8 = mask.astype(np.uint8)
    geoms: List[Polygon] = []
    for geom_val, val in features.shapes(mask_u8, mask=mask_u8.astype(bool), transform=transform):
        if int(val) != 1:
            continue
        g = shape(geom_val)
        if not g.is_valid:
            g = g.buffer(0)
        if g.is_empty:
            continue
        geoms.append(g)  # type: ignore[arg-type]
    if not geoms:
        return None, Polygon(), 0.0
    merged = unary_union(geoms)
    merged = parse_multi_polygon(merged)
    if simplify_tolerance > 0:
        merged = merged.simplify(simplify_tolerance, preserve_topology=True)
    area = area_km2(merged)
    if area < min_area_km2:
        return None, Polygon(), area
    return mapping(merged), merged, area


def pixel_area_km2(transform: Affine, shape_: Tuple[int, int]) -> float:
    """Approximate area of one pixel in km² at the grid's latitude."""
    lon_per_px = abs(transform.a)
    lat_per_px = abs(transform.e)
    lat0 = transform.f
    mid_lat = lat0 - lat_per_px * shape_[0] / 2.0
    km_x = lon_per_px * 111.32 * np.cos(np.radians(mid_lat))
    km_y = lat_per_px * 110.57
    return km_x * km_y


def describe(arr: np.ndarray, mask: Optional[np.ndarray] = None) -> Dict[str, Optional[float]]:
    v = arr[mask] if mask is not None else arr
    v = v[np.isfinite(v)]
    if v.size == 0:
        return {"count": 0, "mean": None, "median": None, "p05": None, "p95": None}
    return {
        "count": int(v.size),
        "mean": float(np.mean(v)),
        "median": float(np.median(v)),
        "p05": float(np.percentile(v, 5)),
        "p95": float(np.percentile(v, 95)),
    }


def geometry_summary(geom: Any) -> Dict[str, Any]:
    if geom is None or geom.is_empty:
        return {"area_km2": 0.0, "bbox": None, "centroid": None}
    c = centroid_lonlat(geom)
    return {"area_km2": round(area_km2(geom), 6), "bbox": list(geom.bounds), "centroid": [c[0], c[1]]}
