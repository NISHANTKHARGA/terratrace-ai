"""Copernicus Data Space Ecosystem connector (catalogue + optional token).

Anonymous OData catalogue search is used for metadata discovery of Sentinel-1
observations. Downloading science products requires a free API key which is
read server-side from the environment (see `.env.example`).
Docs: https://documentation.dataspace.copernicus.eu/
"""
from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import quote

import requests

from app.config import settings
from app.core.geo import bbox_to_polygon, validate_bbox
from app.core.logging import get_logger
from app.data_sources.base import DataSource, stable_observation_id
from app.schemas.api import DataSourceStatusOut, ObservationOut, ObservationQuality

log = get_logger("data_sources.copernicus")

ODATA = "https://catalogue.dataspace.copernicus.eu/odata/v1/Items"
TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"


class CopernicusSource(DataSource):
    id = "copernicus_dataspace"
    name = "Copernicus Data Space"
    provider = "ESA / Copernicus"
    description = (
        "Sentinel-1 OData catalogue search (anonymous metadata). Product downloads "
        "require a Copernicus Data Space key configured server-side."
    )
    auth_required = False

    def __init__(self) -> None:
        self._token: Optional[str] = None
        self._token_expiry: float = 0.0

    def status(self) -> DataSourceStatusOut:
        try:
            resp = requests.get(
                ODATA,
                params={"$top": 1, "$filter": "Collection/Name eq 'SENTINEL-1'"},
                headers={"User-Agent": settings.user_agent},
                timeout=settings.http_timeout_s,
            )
            ok = resp.status_code == 200
            detail = f"OData catalogue HTTP {resp.status_code} (anonymous)"
        except requests.RequestException as exc:
            ok, detail = False, f"network error: {exc}"
        if settings.copernicus_client_id and settings.copernicus_client_secret:
            detail += " · download key configured"
        else:
            detail += " · download key NOT configured (metadata only)"
        return DataSourceStatusOut(
            id=self.id, name=self.name, description=self.description, provider=self.provider,
            status="operational" if ok else "unavailable", detail=detail,  # type: ignore[arg-type]
            checked_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            auth_required=bool(settings.copernicus_client_id),
        )

    def search(
        self,
        bbox: Optional[Sequence[float]] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        mission: Optional[str] = None,
        limit: int = 50,
    ) -> List[ObservationOut]:
        clauses = ["Collection/Name eq 'SENTINEL-1'"]
        if bbox:
            w, s, e, n = validate_bbox(bbox)
            poly = f"({w} {s}, {e} {s}, {e} {n}, {w} {n}, {w} {s})"
            clauses.append(
                "OData.CSC.Intersects(area=geography'SRID=4326;" + poly + "')"
            )
        if start:
            clauses.append(f"ContentDate/Start gt {start}T00:00:00.000Z")
        if end:
            clauses.append(f"ContentDate/Start lt {end}T23:59:59.999Z")
        params = {
            "$filter": " and ".join(clauses),
            "$top": str(min(limit, 1000)),
            "$orderby": "ContentDate/Start desc",
            "$expand": "Attributes",
        }
        try:
            resp = requests.get(
                ODATA, params=params, headers={"User-Agent": settings.user_agent},
                timeout=settings.http_timeout_s,
            )
            resp.raise_for_status()
            payload = resp.json()
        except (requests.RequestException, ValueError) as exc:
            log.warning("Copernicus catalogue search failed", extra={"extra_fields": {"error": str(exc)}})
            return []
        return [self._parse(v) for v in payload.get("value", [])]

    def _parse(self, item: Dict[str, Any]) -> ObservationOut:
        attrs = {a.get("Name"): a.get("Value") for a in item.get("Attributes") or []}
        name = item.get("Name") or ""
        start = (item.get("ContentDate") or {}).get("Start")
        stop = (item.get("ContentDate") or {}).get("End")
        s1_name = (attrs.get("S1Name") or name)
        product_type = "GRD" if "GRD" in str(s1_name).upper() or "GRD" in name.upper() else (
            "SLC" if "SLC" in name.upper() else "L1")
        pols: List[str] = []
        pols_str = str(attrs.get("Polarisation") or "")
        for p in ("VV", "VH", "HH", "HV"):
            if p in pols_str.upper():
                pols.append(p)
        orbit = str(attrs.get("OrbitDirection") or "") or None
        notes = ["Copernicus catalogue entry (metadata). Download requires a Data Space key."]
        return ObservationOut(
            id=stable_observation_id(self.id, str(item.get("Id") or name)),
            provider_id=str(item.get("Id") or name),
            mission="SENTINEL-1",
            platform=str(attrs.get("Satellite") or "Sentinel-1"),
            source=self.id,
            product_type=product_type,
            processing_level="L1",
            datetime=start or "",
            datetime_end=stop,
            polarizations=pols,
            orbit_direction=orbit.upper() if orbit else None,
            bbox=list(attrs["bbox"]) if isinstance(attrs.get("bbox"), list) else None,
            footprint=bbox_to_polygon(attrs["bbox"]) if isinstance(attrs.get("bbox"), list) else None,
            url=item.get("@odata.id"),
            browse_url=None,
            requires_credentials=True,
            size_mb=float(attrs["CloudCover"]) if str(attrs.get("CloudCover", "")).isdigit() else None,
            quality=ObservationQuality(valid_coverage=None, notes=notes),
            context={"attributes": {k: v for k, v in attrs.items() if k in (
                "ProductType", "OrbitDirection", "Polarisation", "SwathIdentifier", "SliceNumber")}},
        )

    # ------------------------------------------------------------ credentials
    def download_token(self) -> Optional[str]:
        if self._token and time.time() < self._token_expiry - 60:
            return self._token
        if not (settings.copernicus_client_id and settings.copernicus_client_secret):
            return None
        try:
            resp = requests.post(
                TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": settings.copernicus_client_id,
                    "client_secret": settings.copernicus_client_secret,
                },
                timeout=30,
            )
            resp.raise_for_status()
            payload = resp.json()
            self._token = payload.get("access_token")
            self._token_expiry = time.time() + float(payload.get("expires_in", 600))
            return self._token
        except (requests.RequestException, ValueError) as exc:
            log.warning("Copernicus token failed", extra={"extra_fields": {"error": str(exc)}})
            return None
