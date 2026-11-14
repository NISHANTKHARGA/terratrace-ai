"""Microsoft Planetary Computer STAC connector.

Used for **real, calibrated Sentinel-1 backscatter rasters** (the
`sentinel-1-rtc` collection: radiometrically terrain corrected sigma0, 10 m,
GeoTIFF COGs). Access is anonymous: asset URLs are signed client-side through
the public SAS endpoint, so no credentials are needed for raster processing.

Honesty note: this is a Sentinel-1 mirror hosted by Microsoft, not a NASA
archive — TerraTrace labels it as `SENTINEL-1` mission, source
`planetary_computer`. NASA-sourced observations come from the CMR connector.
"""
from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional, Sequence

import requests

from app.config import settings
from app.core.errors import UpstreamError
from app.core.geo import bbox_to_polygon, validate_bbox
from app.data_sources.base import DataSource, http_post_json, http_probe, stable_observation_id
from app.schemas.api import DataSourceStatusOut, ObservationOut, ObservationQuality

STAC_SEARCH = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
SAS_SIGN = "https://planetarycomputer.microsoft.com/api/sas/v1/sign"

COLLECTIONS = ["sentinel-1-rtc", "sentinel-1-grd"]

POLARIZATION_RE = re.compile(r"^(vv|vh|hh|hv)$", re.I)


def sign_href(href: str, timeout: float = 60.0) -> str:
    """Return an anonymously signed URL for a Planetary Computer asset."""
    try:
        resp = requests.get(
            SAS_SIGN, params={"href": href},
            headers={"User-Agent": settings.user_agent}, timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()["href"]
    except (requests.RequestException, ValueError, KeyError) as exc:
        raise UpstreamError("planetary_computer", f"asset signing failed: {exc}") from exc


class PlanetaryComputerSource(DataSource):
    id = "planetary_computer"
    name = "Planetary Computer (Sentinel-1 RTC)"
    provider = "Microsoft Planetary Computer / ESA Sentinel-1"
    description = (
        "Anonymous STAC access to radiometrically terrain corrected Sentinel-1 (10 m) "
        "and Sentinel-1 GRD GeoTIFFs — the raster backbone for SAR change detection."
    )
    auth_required = False

    def status(self) -> DataSourceStatusOut:
        probe = http_probe(STAC_SEARCH.replace("/search", "/collections/sentinel-1-rtc"))
        if not probe["ok"]:
            return DataSourceStatusOut(
                id=self.id, name=self.name, description=self.description, provider=self.provider,
                status="unavailable", detail=probe["detail"],  # type: ignore[arg-type]
                checked_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), auth_required=False,
            )
        # verify the anonymous SAS signing path still works (one tiny HEAD-ish read)
        try:
            feats = self.search(bbox=[85.2, 27.55, 85.5, 27.75], start="2024-01-01", end="2024-12-31", limit=1)
            if feats:
                signed = sign_href(feats[0].url or "")
                detail = f"STAC search + anonymous asset signing OK ({len(feats)} scene(s) in probe area)"
                st = "operational"
            else:
                detail = "STAC reachable but no scenes returned for probe area"
                st = "degraded"
                signed = ""
        except Exception as exc:
            detail, st, signed = f"signing probe failed: {exc}", "degraded", ""
        return DataSourceStatusOut(
            id=self.id, name=self.name, description=self.description, provider=self.provider,
            status=st, detail=detail,  # type: ignore[arg-type]
            checked_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), auth_required=False,
        )

    def search(
        self,
        bbox: Optional[Sequence[float]] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        mission: Optional[str] = None,
        limit: int = 50,
    ) -> List[ObservationOut]:
        payload: Dict[str, Any] = {"limit": min(limit, 200), "collections": COLLECTIONS}
        if bbox:
            payload["bbox"] = list(validate_bbox(bbox))
        if start or end:
            s = f"{start}T00:00:00Z" if start else ".."
            e = f"{end}T23:59:59Z" if end else ".."
            payload["datetime"] = f"{s}/{e}"
        data = http_post_json(STAC_SEARCH, payload)
        feats = data.get("features") or []
        return [self._parse(f) for f in feats]

    def _parse(self, feat: Dict[str, Any]) -> ObservationOut:
        props = feat.get("properties") or {}
        assets = feat.get("assets") or {}
        item_id = feat.get("id") or ""
        coll = feat.get("collection") or ""
        is_rtc = coll == "sentinel-1-rtc"

        pols = sorted({k.upper() for k in assets if POLARIZATION_RE.match(k)})
        geom = feat.get("geometry")
        bbox = feat.get("bbox")
        if bbox is None and geom:
            xs = [c[0] for ring in geom["coordinates"] for c in ring]
            ys = [c[1] for ring in geom["coordinates"] for c in ring]
            bbox = [min(xs), min(ys), max(xs), max(ys)]

        orbit = props.get("sat:orbit_state")
        platform = "Sentinel-1A" if item_id.startswith("S1A") else (
            "Sentinel-1B" if item_id.startswith("S1B") else "Sentinel-1"
        )
        primary = assets.get("vv") or next(iter(assets.values()), {})
        notes: List[str] = []
        if is_rtc:
            notes.append("Radiometrically terrain corrected sigma0 (calibrated), 10 m grid.")
        else:
            notes.append(
                "GRD mirror: measurement assets are stored in radar geometry without embedded "
                "georeferencing — usable for metadata, not for direct geospatial output."
            )
        return ObservationOut(
            id=stable_observation_id(self.id, item_id),
            provider_id=item_id,
            mission="SENTINEL-1",
            platform=platform,
            source=self.id,
            product_type="RTC-S1" if is_rtc else "GRD",
            processing_level="L2",
            datetime=props.get("datetime") or "",
            datetime_end=props.get("datetime"),
            polarizations=pols,
            orbit_direction=(orbit or "").upper() or None,
            bbox=list(bbox) if bbox else None,
            footprint=geom if geom and geom.get("type") == "Polygon" else (bbox_to_polygon(bbox) if bbox else None),
            url=primary.get("href"),
            browse_url=(assets.get("rendered_preview") or {}).get("href"),
            requires_credentials=False,
            size_mb=None,
            quality=ObservationQuality(valid_coverage=None, notes=notes),
            context={
                "stac_collection": coll,
                "stac_self": (feat.get("links") or [{}])[0].get("href"),
                "needs_sas_signing": True,
                "assets": {k: v.get("href") for k, v in assets.items()
                           if k in ("vv", "vh", "hh", "hv", "thumbnail", "rendered_preview")},
                "proj_epsg": props.get("proj:epsg"),
                "resolution_m": 10.0 if is_rtc else None,
                "georeferenced": bool(is_rtc),
            },
        )
