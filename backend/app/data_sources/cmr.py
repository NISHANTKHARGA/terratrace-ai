"""NASA Earthdata Common Metadata Repository (CMR) connector.

CMR is the official, anonymous, machine-readable catalogue behind NASA Earthdata
Search and the Alaska Satellite Facility. It indexes NISAR, OPERA and Sentinel-1
collections, so it is TerraTrace's primary *discovery* source.

Docs: https://cmr.earthdata.nasa.gov/search/site/docs/search_api.html
"""
from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Sequence

from app.config import settings
from app.core.errors import UpstreamError
from app.core.geo import bbox_to_polygon, cmr_polygon_to_geojson, validate_bbox
from app.core.logging import get_logger
from app.data_sources.base import DataSource, http_get_json, http_probe, stable_observation_id
from app.schemas.api import DataSourceStatusOut, ObservationOut, ObservationQuality

log = get_logger("data_sources.cmr")

CMR_GRANULE_URL = "https://cmr.earthdata.nasa.gov/search/granules.json"
CMR_COLLECTION_URL = "https://cmr.earthdata.nasa.gov/search/collections.json"

# Collection short_names grouped by the mission they belong to.
MISSION_COLLECTIONS: Dict[str, List[str]] = {
    "NISAR": [
        "NISAR_L1_RSLC_V1",
        "NISAR_L1_RSLC_BETA_V1",
        "NISAR_L2_GSLC_V1",
        "NISAR_L2_GSLC_BETA_V1",
        "NISAR_L2_GCOV_V1",
        "NISAR_L2_GCOV_BETA_V1",
        "NISAR_L2_GUNW_V1",
        "NISAR_L2_GUNW_BETA_V1",
        "NISAR_L1_RUNW_V1",
        "NISAR_L1_RIFG_V1",
        "NISAR_L1_ROFF_V1",
        "NISAR_L3_SME2_V1",
    ],
    "OPERA": [
        "OPERA_L2_RTC-S1_V1",
        "OPERA_L3_DSWX-S1_V1",
        "OPERA_L3_DISP-S1_V1",
        "OPERA_L3_DISP-S1-STATIC_V1",
        "OPERA_L2_CSLC-S1_V1",
        "OPERA_L3_DIST-ALERT-S1_V1",
        "OPERA_L3_DSWX-HLS_V1",
    ],
    "SENTINEL-1": [
        "SENTINEL-1A_SLC", "SENTINEL-1B_SLC", "SENTINEL-1C_SLC", "SENTINEL-1D_SLC",
        "SENTINEL-1A_DP_GRD_HIGH", "SENTINEL-1B_DP_GRD_HIGH",
        "SENTINEL-1C_DP_GRD_HIGH", "SENTINEL-1D_DP_GRD_HIGH",
        "SENTINEL-1A_DP_GRD_MEDIUM", "SENTINEL-1B_DP_GRD_MEDIUM",
        "SENTINEL-1C_DP_GRD_MEDIUM", "SENTINEL-1D_DP_GRD_MEDIUM",
        "SENTINEL-1A_SP_GRD_HIGH", "SENTINEL-1B_SP_GRD_HIGH",
        "SENTINEL-1C_SP_GRD_HIGH", "SENTINEL-1D_SP_GRD_HIGH",
        "S1_SLC", "S1_GRD",
    ],
    "UAVSAR": [
        "UAVSAR_RPI",
        "UAVSAR_POLSAR",
        "SV19MA_SAR",
    ],
}

# Patterns are matched against separator-normalised text ("NISAR L1 PR RSLC …"),
# so separators between tokens are matched with \s* rather than literal -/_.
PRODUCT_PATTERNS = [
    ("RSLC", re.compile(r"\bRSLC\b", re.I)),
    ("GSLC", re.compile(r"\bGSLC\b", re.I)),
    ("GCOV", re.compile(r"\bGCOV\b", re.I)),
    ("GUNW", re.compile(r"\bGUNW\b", re.I)),
    ("RUNW", re.compile(r"\bRUNW\b", re.I)),
    ("RIFG", re.compile(r"\bRIFG\b", re.I)),
    ("ROFF", re.compile(r"\bROFF\b", re.I)),
    ("SME2", re.compile(r"\bSME2\b", re.I)),
    ("RPI", re.compile(r"\bRPI\b|\bREPEAT\s*PASS\s*INTERFEROMETRIC\b", re.I)),
    ("POLSAR", re.compile(r"\bPOLSAR\b|\bPOLARIMETRIC\b", re.I)),
    ("RTC-S1", re.compile(r"\bRTC\s*S1\b|\bRTC\b", re.I)),
    ("DSWx-S1", re.compile(r"\bDSWX\s*S1\b", re.I)),
    ("DSWx-HLS", re.compile(r"\bDSWX\s*HLS\b", re.I)),
    ("DISP-S1", re.compile(r"\bDISP\s*S1\b", re.I)),
    ("CSLC", re.compile(r"\bCSLC\b", re.I)),
    ("DIST-ALERT", re.compile(r"\bDIST\s*ALERT\b", re.I)),
    ("GRD", re.compile(r"\bGRD\b|\bGRDH\b", re.I)),
    ("SLC", re.compile(r"\bSLC\b|\bIW\s*SL\b", re.I)),
]

POL_RE = re.compile(r"\b(HH|HV|VH|VV|HH|HR)\b", re.I)
ORBIT_RE = re.compile(r"\b(ascending|descending)\b", re.I)

CREDENTIALLED_HOSTS = (
    "urs.earthdata.nasa.gov",
    "e4ftl01.cr.usgs.gov",
    "s3://",
    "datapool.asf.alaska.edu",
    "n5eil01u.ecs.nsidc.org",
    # Earthdata Cloud / ASF / DAAC science buckets (EDL required for science data)
    "earthdatacloud.nasa.gov",
    "asf.alaska.edu",
    "nsidc.org",
    "ornl.gov",
    "usgs.gov",
    # PO.DAAC archive (OPERA DSWx and other DAAC products are protected)
    "podaac.earthdata.nasa.gov",
)


def _infer_product_type(text: str) -> str:
    for name, pat in PRODUCT_PATTERNS:
        if pat.search(text):
            return name
    return "UNKNOWN"


def _polygon_points(polys: Sequence[Any]) -> List[Dict[str, float]]:
    """Normalise CMR polygon payloads into ``[{"lon": .., "lat": ..}, ...]``.

    CMR's granule JSON returns each polygon as a string of alternating
    latitude/longitude values ("lat lon lat lon …", UMM-G ordering) — verified
    against UAVSAR_RPI, UAVSAR_POLSAR and SENTINEL-1A_DP_GRD_HIGH payloads.
    Real payloads wrap the string in an extra list, so both shapes are
    accepted. A pair whose first value cannot be a latitude (|v| > 90) is
    swapped defensively.
    """
    points: List[Dict[str, float]] = []

    def _pairs(nums: List[float]) -> None:
        for i in range(0, len(nums) - 1, 2):
            a, b = nums[i], nums[i + 1]
            if abs(a) <= 90.0:
                points.append({"lat": a, "lon": b})
            else:
                points.append({"lat": b, "lon": a})

    def _string_points(s: str) -> None:
        try:
            _pairs([float(v) for v in s.replace(",", " ").split() if v])
        except ValueError:
            pass

    for poly in polys or []:
        if isinstance(poly, str):
            _string_points(poly)
        elif isinstance(poly, dict):
            pts = poly.get("points") or []
            for p in pts:
                if isinstance(p, dict) and "lon" in p and "lat" in p:
                    points.append({"lon": float(p["lon"]), "lat": float(p["lat"])})
        elif isinstance(poly, (list, tuple)):
            nums: List[float] = []
            for p in poly:
                if isinstance(p, dict) and "lon" in p and "lat" in p:
                    points.append({"lon": float(p["lon"]), "lat": float(p["lat"])})
                elif isinstance(p, str):
                    _string_points(p)
                elif isinstance(p, (list, tuple)) and len(p) >= 2:
                    nums.extend([float(p[0]), float(p[1])])
                elif isinstance(p, (int, float)):
                    nums.append(float(p))
            if nums:
                _pairs(nums)
    return points


def _pol_from_identifier(title: str, mission: str) -> List[str]:
    """Fallback polarisation from the product identifier when CMR omits it.

    Sentinel-1 product ids encode polarisation in the acquisition quality tag
    (``1SDV`` = dual VV+VH, ``1SDH`` = dual HH+HV, ``1SSV``/``1SSH`` = single).
    NISAR L1/L2 SAR products are dual HH+HV. UAVSAR interferometric (RPI)
    products are single-pol HH; polarimetric (POLSAR) products are quad-pol.
    Only confident matches are returned.
    """
    u = (title or "").upper()
    if mission == "NISAR":
        return ["HH", "HV"]
    if mission == "UAVSAR":
        if "_CX_" in u or "POLSAR" in u or "POLARIMETRIC" in u:
            return ["HH", "HV", "VV", "VH"]
        return ["HH"]
    if "1SDV" in u or "_SDV" in u:
        return ["VV", "VH"]
    if "1SDH" in u or "_SDH" in u:
        return ["HH", "HV"]
    if "1SSV" in u or "_SSV" in u:
        return ["VV"]
    if "1SSH" in u or "_SSH" in u:
        return ["HH"]
    return []


def _link_by_rel(links: Sequence[Dict[str, Any]], suffix: str, https_only: bool = True) -> Optional[str]:
    fallback = None
    for ln in links or []:
        rel = ln.get("rel", "")
        href = ln.get("href") or ""
        if not rel.endswith(suffix):
            continue
        if href.startswith("s3://"):
            fallback = fallback or href
            continue
        if https_only and not href.startswith("http"):
            continue
        return href
    return fallback


class CmrSource(DataSource):
    id = "nasa_cmr"
    name = "NASA Earthdata CMR"
    provider = "NASA / ASF / PO.DAAC / JPL / CSA / CONAE"
    description = (
        "NASA Common Metadata Repository — the official anonymous catalogue behind "
        "NASA Earthdata Search and ASF Vertex. Discovers NISAR, OPERA, Sentinel-1 "
        "and UAVSAR collections (metadata + footprint + browse links)."
    )
    auth_required = False

    def status(self) -> DataSourceStatusOut:
        probe = http_probe(CMR_GRANULE_URL, params={"short_name": "OPERA_L3_DSWX-S1_V1", "page_size": 1})
        if probe["ok"]:
            st, detail = "operational", f"Anonymous CMR search OK ({probe['detail']})"
        else:
            st, detail = "unavailable", probe["detail"]
        return DataSourceStatusOut(
            id=self.id, name=self.name, description=self.description, provider=self.provider,
            status=st, detail=detail,  # type: ignore[arg-type]
            checked_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            auth_required=self.auth_required,
        )

    # ------------------------------------------------------------------ search
    def search(
        self,
        bbox: Optional[Sequence[float]] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        mission: Optional[str] = None,
        limit: int = 50,
    ) -> List[ObservationOut]:
        missions = [mission] if mission else list(MISSION_COLLECTIONS)
        results: List[ObservationOut] = []
        errors: List[str] = []
        per_mission = max(3, limit // max(1, len(missions)) + 3)

        def _query(m: str) -> List[ObservationOut]:
            return self._search_mission(m, bbox, start, end, per_mission)

        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {pool.submit(_query, m): m for m in missions if m in MISSION_COLLECTIONS}
            for fut in as_completed(futures, timeout=45):
                m = futures[fut]
                try:
                    results.extend(fut.result())
                except Exception as exc:  # tolerate one failing group
                    errors.append(f"{m}: {exc}")
                    log.warning("CMR group failed", extra={"extra_fields": {"mission": m, "error": str(exc)}})

        results.sort(key=lambda o: o.datetime, reverse=True)
        wanted = [m for m in missions if m in MISSION_COLLECTIONS]
        if errors:
            log.warning("CMR partial failure", extra={"extra_fields": {"errors": errors}})
        if errors and len(errors) >= len(wanted) and not results:
            raise UpstreamError(self.id, "all CMR queries failed", errors)
        return results[:limit]

    def _search_mission(
        self,
        mission: str,
        bbox: Optional[Sequence[float]],
        start: Optional[str],
        end: Optional[str],
        limit: int,
    ) -> List[ObservationOut]:
        params: List[tuple] = [("page_size", str(min(limit, 100))), ("sort_key", "-start_date")]
        for sn in MISSION_COLLECTIONS[mission]:
            params.append(("short_name", sn))
        if bbox:
            w, s, e, n = validate_bbox(bbox)
            params.append(("bounding_box", f"{w},{s},{e},{n}"))
        if start or end:
            params.append(("temporal", f"{start or ''},{end or ''}"))
        data = http_get_json(
            CMR_GRANULE_URL, params=params,
            # include the collection set so switching short_names never serves a
            # stale empty result from the disk cache
            cache_key=f"cmr|{mission}|{','.join(MISSION_COLLECTIONS[mission])}|"
                      f"{bbox}|{start}|{end}|{limit}",
        )
        entries = (data.get("feed") or {}).get("entry") or []
        return [self._parse_entry(entry, mission) for entry in entries]

    # ------------------------------------------------------------------ parse
    def _parse_entry(self, entry: Dict[str, Any], mission: str) -> ObservationOut:
        title = entry.get("title") or entry.get("producer_granule_id") or "unknown"
        dataset_id = entry.get("dataset_id") or ""
        links = entry.get("links") or []

        footprint: Optional[Dict[str, Any]] = None
        bbox: Optional[List[float]] = None
        polys = entry.get("polygons") or []
        points = _polygon_points(polys)
        if points:
            footprint = cmr_polygon_to_geojson([{"points": points}])
        if footprint is None:
            bboxes = entry.get("bboxes") or []
            if bboxes:
                w, s, e, n = bboxes[0]
                footprint = bbox_to_polygon((w, s, e, n))
        if footprint is not None:
            xs = [c[0] for ring in footprint["coordinates"] for c in ring]
            ys = [c[1] for ring in footprint["coordinates"] for c in ring]
            bbox = [min(xs), min(ys), max(xs), max(ys)]

        data_url = _link_by_rel(links, "data#")
        s3_url = next((l.get("href") for l in links if str(l.get("href", "")).startswith("s3://")), None)
        browse = _link_by_rel(links, "browse#")
        metadata = _link_by_rel(links, "metadata#")

        requires_creds = False
        if data_url:
            requires_creds = any(h in data_url for h in CREDENTIALLED_HOSTS) or data_url.startswith("s3://")
        elif s3_url:
            requires_creds = True
        if mission == "UAVSAR":
            # The UAVSAR archive on cumulus.asf.earthdatacloud.nasa.gov is an
            # open NASA/JPL airborne dataset (verified anonymous access to both
            # browse and product files).
            requires_creds = False
        if mission == "OPERA":
            # OPERA products are served from protected DAAC/ASF buckets and
            # require Earthdata Login credentials for science-data access.
            requires_creds = True

        summary_text = re.sub(r"<[^>]+>", " ", entry.get("summary") or "")
        text = f"{title} {dataset_id} {summary_text}"
        # CMR identifiers are underscore-separated ("NISAR_L1_PR_RSLC_…"), which
        # defeats \b word boundaries — normalise separators before pattern work.
        norm = re.sub(r"[^A-Za-z0-9]+", " ", text).upper()
        polarizations = sorted({m.upper() for m in POL_RE.findall(norm)})
        if not polarizations:
            polarizations = _pol_from_identifier(title, mission)
        orbit = None
        m = ORBIT_RE.search(summary_text) or ORBIT_RE.search(title)
        if m:
            orbit = m.group(1).upper()

        platforms = entry.get("platforms") or []
        platform = "unknown"
        if platforms:
            platform = (
                platforms[0].get("short_name")
                or platforms[0].get("long_name")
                or "unknown"
            )
        if platform == "unknown" and title.startswith("NISAR"):
            platform = "NISAR"
        elif title.startswith(("S1A", "S1B")):
            platform = "Sentinel-1A" if title.startswith("S1A") else "Sentinel-1B"
        elif platform == "unknown" and mission == "UAVSAR":
            platform = "UAVSAR (NASA/JPL airborne)"

        product_type = _infer_product_type(norm)
        level_m = re.search(r"\b(L1|L2|L3)\b", norm)
        if level_m:
            level = level_m.group(1)
        elif mission == "UAVSAR":
            level = "L090"
        elif re.search(r"\b(RSLC|GRD|RIFG|RUNW|ROFF|SLC)\b", norm):
            level = "L1"
        elif re.search(r"\b(SME2|DSWX|DIST)\b", norm):
            level = "L3"
        else:
            level = "L2"
        notes: List[str] = []
        if requires_creds:
            notes.append("Science data download requires Earthdata Login credentials (server side .env).")
        if mission == "UAVSAR":
            notes.append("Open NASA/JPL airborne SAR: browse images and products are publicly accessible.")
        if browse:
            notes.append("Official quicklook/browse image available anonymously.")
        metadata_only = data_url is None and s3_url is None
        if metadata_only:
            notes.append("Metadata-only record: no anonymous science data link is exposed "
                         "by the provider for this granule.")

        provider_id = entry.get("id") or entry.get("producer_granule_id") or title
        return ObservationOut(
            id=stable_observation_id(self.id, str(provider_id)),
            provider_id=str(provider_id),
            mission=mission,  # type: ignore[arg-type]
            platform=platform,
            source=self.id,
            product_type=product_type,
            processing_level=level,
            datetime=entry.get("time_start") or entry.get("time_end") or "",
            datetime_end=entry.get("time_end"),
            polarizations=polarizations,
            orbit_direction=orbit,
            bbox=bbox,
            footprint=footprint,
            url=data_url or s3_url or metadata,
            browse_url=browse,
            requires_credentials=requires_creds,
            size_mb=None,
            quality=ObservationQuality(valid_coverage=None, notes=notes),
            context={
                "dataset_id": dataset_id,
                "producer_granule_id": entry.get("producer_granule_id"),
                "concept_id": entry.get("id"),
                "s3_url": s3_url,
                "metadata_url": metadata,
                "metadata_only": metadata_only,
                "summary_url": f"https://cmr.earthdata.nasa.gov/search/granules.json?concept_id={entry.get('id')}",
            },
        )
