"""Geospatial helpers: bbox/polygon conversions, areas, intersections."""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from pyproj import Geod
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, box, mapping, shape
from shapely.geometry.base import BaseGeometry

BBox = Tuple[float, float, float, float]  # west, south, east, north
_GEOD = Geod(ellps="WGS84")

MAX_AREA_KM2 = 4_000_000.0  # guard rail for a single analysis request


def validate_bbox(bbox: Sequence[float]) -> BBox:
    if bbox is None or len(bbox) != 4:
        raise ValueError("bbox must be [west, south, east, north]")
    w, s, e, n = (float(v) for v in bbox)
    if not (-180 <= w < e <= 180 and -90 <= s < n <= 90):
        raise ValueError("bbox out of range or inverted; expected W<=E, S<=N in EPSG:4326")
    return (w, s, e, n)


def bbox_to_polygon(bbox: BBox) -> Dict[str, Any]:
    w, s, e, n = bbox
    return {
        "type": "Polygon",
        "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]],
    }


def polygon_to_bbox(geom: BaseGeometry) -> BBox:
    minx, miny, maxx, maxy = geom.bounds
    return validate_bbox([minx, miny, maxx, maxy])


def geom_from_geojson(obj: Any) -> BaseGeometry:
    if isinstance(obj, BaseGeometry):
        return obj
    return shape(obj)


def to_geojson(geom: BaseGeometry) -> Dict[str, Any]:
    return mapping(geom)


def area_km2(geom: BaseGeometry) -> float:
    """Geodesic area in km^2 (WGS84)."""
    if geom.is_empty:
        return 0.0
    if geom.geom_type in ("Polygon", "MultiPolygon"):
        area, _ = _GEOD.geometry_area_perimeter(geom)
        return abs(area) / 1e6
    if geom.geom_type == "GeometryCollection":
        return sum(area_km2(g) for g in geom.geoms)
    return 0.0


def intersection_area_km2(a: BaseGeometry, b: BaseGeometry) -> float:
    try:
        inter = a.intersection(b)
    except Exception:  # pragma: no cover - topology robustness
        return 0.0
    return area_km2(inter)


def overlap_ratio(a: BaseGeometry, b: BaseGeometry) -> float:
    """Intersection area divided by the smaller area (0..1)."""
    aa, bb = area_km2(a), area_km2(b)
    denom = min(aa, bb)
    if denom <= 0:
        return 0.0
    return min(1.0, intersection_area_km2(a, b) / denom)


def parse_multi_polygon(geom: BaseGeometry) -> BaseGeometry:
    """Return a (Multi)Polygon geometry, dropping non-areal parts."""
    if geom.geom_type in ("Polygon", "MultiPolygon"):
        return geom
    if geom.geom_type == "GeometryCollection":
        polys = [g for g in geom.geoms if g.geom_type in ("Polygon", "MultiPolygon")]
        if not polys:
            return Polygon()
        flat: List[Polygon] = []
        for p in polys:
            if p.geom_type == "Polygon":
                flat.append(p)
            else:
                flat.extend(list(p.geoms))
        return flat[0] if len(flat) == 1 else MultiPolygon(flat)
    return Polygon()


def centroid_lonlat(geom: BaseGeometry) -> Tuple[float, float]:
    c = geom.representative_point()
    return (float(c.x), float(c.y))


def sanitize_ring(coords: Iterable[Sequence[float]]) -> List[List[float]]:
    out: List[List[float]] = []
    for c in coords:
        lon = max(-180.0, min(180.0, float(c[0])))
        lat = max(-90.0, min(90.0, float(c[1])))
        out.append([lon, lat])
    return out


def cmr_polygon_to_geojson(entries: Sequence[Dict[str, float]]) -> Optional[Dict[str, Any]]:
    """Build a GeoJSON polygon from normalised CMR points (lon lat pairs)."""
    if not entries:
        return None
    pts = entries[0].get("points") if isinstance(entries[0], dict) else None
    if not pts and entries and isinstance(entries[0], list):
        pts = entries[0]
    if not pts:
        return None
    ring = sanitize_ring([(p["lon"], p["lat"]) for p in pts])
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    if len(ring) < 4:
        return None
    return {"type": "Polygon", "coordinates": [ring]}


def geometry_to_bbox_geojson(geom: BaseGeometry) -> BBox:
    return polygon_to_bbox(geom)


def ensure_polygon(geom: BaseGeometry) -> BaseGeometry:
    return parse_multi_polygon(geom)


def describe_geometry(geom: BaseGeometry) -> Dict[str, Any]:
    return {
        "type": geom.geom_type,
        "bbox": list(polygon_to_bbox(geom)) if not geom.is_empty else None,
        "area_km2": round(area_km2(geom), 6),
    }


__all__ = [
    "BBox",
    "validate_bbox",
    "bbox_to_polygon",
    "polygon_to_bbox",
    "geom_from_geojson",
    "to_geojson",
    "area_km2",
    "intersection_area_km2",
    "overlap_ratio",
    "parse_multi_polygon",
    "centroid_lonlat",
    "cmr_polygon_to_geojson",
    "ensure_polygon",
    "describe_geometry",
    "MAX_AREA_KM2",
    "GeometryCollection",
    "MultiPolygon",
    "Polygon",
    "box",
    "shape",
    "mapping",
]
