"""AWS Open Data / Element84 Earth Search connector.

Provides anonymous access to:
- Sentinel-1 GRD metadata and preview assets (measurement COGs live in radar
  geometry without embedded georeferencing — TerraTrace records this honestly),
- Sentinel-2 L2A optical imagery (context / corroboration),
- Copernicus DEM GLO-30 tiles (terrain context for the landslide agent).

Catalogue: https://earth-search.aws.element84.com/v1
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Sequence

from app.config import settings
from app.core.geo import bbox_to_polygon, validate_bbox
from app.data_sources.base import DataSource, http_get_json, http_probe, stable_observation_id
from app.schemas.api import DataSourceStatusOut, ObservationOut, ObservationQuality

CATALOGUE = "https://earth-search.aws.element84.com/v1"
SEARCH = f"{CATALOGUE}/search"


def s3_to_https(href: str) -> str:
    """Convert `s3://bucket/key` to an anonymous HTTPS URL."""
    if not href.startswith("s3://"):
        return href
    rest = href[5:]
    bucket, _, key = rest.partition("/")
    return f"https://{bucket}.s3.amazonaws.com/{key}"


class EarthSearchSource(DataSource):
    id = "earth_search"
    name = "AWS Open Data — Earth Search"
    provider = "Element84 / AWS (Sentinel-1, Sentinel-2, Copernicus DEM)"
    description = (
        "Anonymous STAC catalogue over AWS open buckets: Sentinel-1 GRD, Sentinel-2 L2A "
        "and Copernicus DEM GLO-30 (used as terrain/context layers)."
    )
    auth_required = False

    def status(self) -> DataSourceStatusOut:
        probe = http_probe(f"{CATALOGUE}/collections")
        return DataSourceStatusOut(
            id=self.id, name=self.name, description=self.description, provider=self.provider,
            status="operational" if probe["ok"] else "unavailable",
            detail=probe["detail"],  # type: ignore[arg-type]
            checked_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            auth_required=False,
        )

    def search(
        self,
        bbox: Optional[Sequence[float]] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        mission: Optional[str] = None,
        limit: int = 50,
    ) -> List[ObservationOut]:
        collection = "sentinel-1-grd"
        params: Dict[str, Any] = {"collections": collection, "limit": min(limit, 200)}
        if bbox:
            w, s, e, n = validate_bbox(bbox)
            params["bbox"] = f"{w},{s},{e},{n}"
        if start or end:
            params["datetime"] = f"{start or '..'}T00:00:00Z/{end or '..'}T23:59:59Z"
        data = http_get_json(SEARCH, params=params)
        feats = data.get("features") or []
        return [self._parse(f) for f in feats]

    def _parse(self, feat: Dict[str, Any]) -> ObservationOut:
        props = feat.get("properties") or {}
        assets = feat.get("assets") or {}
        item_id = feat.get("id") or ""
        geom = feat.get("geometry")
        bbox = props.get("proj:bounds")
        # STAC `bbox` field
        bbox = feat.get("bbox") or bbox
        pols = sorted({k.upper() for k in assets if k.lower() in ("vv", "vh", "hh", "hv")})
        notes = [
            "AWS-hosted Sentinel-1 GRD: measurement GeoTIFFs carry no embedded CRS "
            "(radar geometry). Metadata and previews only — geospatial processing uses "
            "the Planetary Computer RTC or NASA products instead."
        ]
        return ObservationOut(
            id=stable_observation_id(self.id, item_id),
            provider_id=item_id,
            mission="SENTINEL-1",
            platform="Sentinel-1A" if item_id.startswith("S1A") else (
                "Sentinel-1B" if item_id.startswith("S1B") else "Sentinel-1"),
            source=self.id,
            product_type="GRD",
            processing_level="L1",
            datetime=props.get("datetime") or "",
            datetime_end=props.get("datetime"),
            polarizations=pols,
            orbit_direction=(props.get("sat:orbit_state") or "").upper() or None,
            bbox=list(bbox) if bbox else None,
            footprint=geom if geom and geom.get("type") == "Polygon" else (
                bbox_to_polygon(bbox) if bbox else None),
            url=s3_to_https((assets.get("vv") or {}).get("href", "")) or None,
            browse_url=(assets.get("thumbnail") or {}).get("href") or None,
            requires_credentials=False,
            size_mb=None,
            quality=ObservationQuality(valid_coverage=None, notes=notes),
            context={
                "stac_collection": "sentinel-1-grd",
                "georeferenced": False,
                "assets": {k: s3_to_https(v.get("href", "")) for k, v in assets.items()
                           if k in ("vv", "vh", "thumbnail", "safe-manifest")},
            },
        )

    # ------------------------------------------------------- context datasets
    def copernicus_dem_href(self, bbox: Sequence[float]) -> Optional[str]:
        """Return an anonymous GeoTIFF/terrarium URL overlapping `bbox`, if any."""
        w, s, e, n = validate_bbox(bbox)
        try:
            data = http_get_json(
                SEARCH,
                params={"collections": "cop-dem-glo-30", "bbox": f"{w},{s},{e},{n}", "limit": 3},
            )
        except Exception:
            return None
        for feat in data.get("features") or []:
            assets = feat.get("assets") or {}
            for key in ("data", "terrain", "dem"):
                href = (assets.get(key) or {}).get("href")
                if href:
                    return s3_to_https(href)
        return None

    def sentinel2_scene(
        self, bbox: Sequence[float], start: Optional[str], end: Optional[str], cloudy_max: float = 40.0
    ) -> Optional[ObservationOut]:
        """Least-cloudy Sentinel-2 L2A scene (optical context, may not exist)."""
        w, s, e, n = validate_bbox(bbox)
        try:
            data = http_get_json(SEARCH, params={
                "collections": "sentinel-2-l2a",
                "bbox": f"{w},{s},{e},{n}",
                "datetime": f"{start or '..'}T00:00:00Z/{end or '..'}T23:59:59Z",
                "limit": 20,
                "query": {"eo:cloud_cover": {"lt": cloudy_max}},
            })
        except Exception:
            return None
        feats = data.get("features") or []
        if not feats:
            return None
        feats.sort(key=lambda f: (f.get("properties") or {}).get("eo:cloud_cover", 100))
        return self._parse_s2(feats[0])

    def _parse_s2(self, feat: Dict[str, Any]) -> ObservationOut:
        props = feat.get("properties") or {}
        assets = feat.get("assets") or {}
        item_id = feat.get("id") or ""
        geom = feat.get("geometry")
        bbox = feat.get("bbox")
        return ObservationOut(
            id=stable_observation_id(self.id, item_id),
            provider_id=item_id,
            mission="OTHER",
            platform="Sentinel-2A/2B",
            source=self.id,
            product_type="S2L2A",
            processing_level="L2",
            datetime=props.get("datetime") or "",
            datetime_end=props.get("datetime"),
            polarizations=["OPTICAL"],
            orbit_direction=None,
            bbox=list(bbox) if bbox else None,
            footprint=geom if geom else None,
            url=(assets.get("visual") or assets.get("B04") or {}).get("href"),
            browse_url=(assets.get("preview") or assets.get("thumbnail") or {}).get("href"),
            requires_credentials=False,
            size_mb=None,
            quality=ObservationQuality(valid_coverage=None, notes=[
                f"Optical context scene, cloud cover {props.get('eo:cloud_cover')}%."]),
            context={"stac_collection": "sentinel-2-l2a",
                     "cloud_cover": props.get("eo:cloud_cover")},
        )
