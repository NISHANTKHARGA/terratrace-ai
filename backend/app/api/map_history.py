"""Map layer definitions and the combined activity history feed."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.api.deps import clamp_page, paginate
from app.config import settings
from app.core.geo import bbox_to_polygon, geom_from_geojson
from app.database.models import DiscoveryRun, Finding, Job, Observation
from app.database.session import session_scope
from app.schemas.api import HistoryEntry, HistoryPage, MapLayerDef, MapLayersOut

router = APIRouter(tags=["map"])

FINDINGS_GEOJSON_ENDPOINT = "/api/map-layers/findings.geojson"
CHANGE_GEOJSON_ENDPOINT = "/api/map-layers/change.geojson"
ANALYSIS_GEOJSON_ENDPOINT = "/api/map-layers/analysis.geojson"
MAX_FOOTPRINTS = 500
MAX_CHANGE_ARTIFACTS = 100
MAX_ANALYSIS_REGIONS = 200


def _finding_feature(row: Finding) -> Dict[str, Any]:
    centroid = list(row.centroid or [])
    geometry = row.geometry
    if not geometry:
        geometry = bbox_to_polygon(row.bbox) if row.bbox and len(row.bbox) == 4 else None
    if not geometry and len(centroid) == 2:
        geometry = {"type": "Point", "coordinates": centroid}
    return {
        "type": "Feature",
        "id": row.id,
        "properties": {
            "id": row.id, "title": row.title, "category": row.category,
            "agent_id": row.agent_id, "job_id": row.job_id,
            "verification_status": row.verification_status, "severity": row.severity,
            "detection_confidence_heuristic": row.detection_confidence,
            "evidence_completeness": row.evidence_completeness,
            "data_quality": row.data_quality, "area_km2": row.area_km2,
            "observation_dates": row.observation_dates or [],
            "created_at": row.created_at,
        },
        "geometry": geometry,
    }


def _observation_feature(row: Observation) -> Dict[str, Any]:
    geometry = row.footprint
    if not geometry and row.bbox and len(row.bbox) == 4:
        geometry = bbox_to_polygon(row.bbox)
    return {
        "type": "Feature",
        "id": row.id,
        "properties": {
            "id": row.id, "mission": row.mission, "platform": row.platform,
            "source": row.source, "product_type": row.product_type,
            "datetime": row.datetime, "orbit_direction": row.orbit_direction,
            "requires_credentials": bool(row.requires_credentials),
            "browse_url": row.browse_url,
        },
        "geometry": geometry,
    }


def _collections() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    with session_scope() as db:
        findings = db.query(Finding).order_by(Finding.created_at.desc()).limit(1000).all()
        observations = (db.query(Observation)
                        .order_by(Observation.datetime.desc())
                        .limit(MAX_FOOTPRINTS).all())
        f_geo = {"type": "FeatureCollection", "features": [_finding_feature(r) for r in findings]}
        o_geo = {"type": "FeatureCollection",
                 "features": [_observation_feature(r) for r in observations]}
    return f_geo, o_geo


def _empty_fc() -> Dict[str, Any]:
    return {"type": "FeatureCollection", "features": []}


def _change_polygons_geojson() -> Dict[str, Any]:
    """Merge real change-mask artifact GeoJSON files into one collection.

    These are the vectorised rasters produced by the change-detection engine,
    not rounded finding summaries. Invalid or missing artifacts are skipped.
    """
    features: List[Dict[str, Any]] = []
    root = settings.artifacts_dir
    if not root.is_dir():
        return _empty_fc()

    for change_file in sorted(root.glob("*/change.geojson"))[-MAX_CHANGE_ARTIFACTS:]:
        job_id = change_file.parent.name
        try:
            payload = json.loads(change_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        candidates: List[Dict[str, Any]] = []
        if isinstance(payload, dict) and payload.get("type") == "FeatureCollection":
            candidates = list(payload.get("features") or [])
        elif isinstance(payload, dict) and payload.get("type") == "Feature":
            candidates = [payload]

        for feature in candidates:
            if not isinstance(feature, dict):
                continue
            geometry = feature.get("geometry")
            if not geometry:
                continue
            props = dict(feature.get("properties") or {})
            props.update({
                "source": "change_detection_artifact",
                "artifact": f"/api/jobs/{job_id}/assets/change.geojson",
                "job_id": props.get("job_id") or job_id,
            })
            features.append({
                "type": "Feature",
                "id": str(feature.get("id") or f"{job_id}:change"),
                "properties": props,
                "geometry": geometry,
            })

    return {"type": "FeatureCollection", "features": features}


def _analysis_regions_geojson() -> Dict[str, Any]:
    """Expose actual analysis footprints for the map (jobs and discovery runs)."""
    features: List[Dict[str, Any]] = []
    with session_scope() as db:
        jobs = (db.query(Job)
                .order_by(Job.created_at.desc(), Job.id.desc())
                .limit(MAX_ANALYSIS_REGIONS).all())
        for job in jobs:
            polygon = (job.request or {}).get("polygon")
            geometry = None
            if polygon:
                try:
                    geom = geom_from_geojson(polygon)
                    if not geom.is_empty:
                        from app.core.geo import to_geojson

                        geometry = to_geojson(geom)
                except Exception:
                    geometry = None
            if not geometry and job.bbox and len(job.bbox) == 4:
                geometry = bbox_to_polygon(job.bbox)
            if not geometry:
                continue
            features.append({
                "type": "Feature",
                "id": job.id,
                "properties": {
                    "kind": "analysis",
                    "id": job.id,
                    "label": job.label,
                    "status": job.status,
                    "created_at": job.created_at,
                    "findings_count": len(job.findings or []),
                    "bbox": list(job.bbox or []),
                },
                "geometry": geometry,
            })

        runs = (db.query(DiscoveryRun)
                .order_by(DiscoveryRun.created_at.desc(), DiscoveryRun.id.desc())
                .limit(50).all())
        for run in runs:
            if not run.bbox or len(run.bbox) != 4:
                continue
            features.append({
                "type": "Feature",
                "id": run.id,
                "properties": {
                    "kind": "discovery",
                    "id": run.id,
                    "label": run.label,
                    "status": run.status,
                    "created_at": run.created_at,
                    "observations_count": run.observations_count,
                    "bbox": list(run.bbox or []),
                },
                "geometry": bbox_to_polygon(run.bbox),
            })

    return {"type": "FeatureCollection", "features": features}


@router.get("/map-layers", response_model=MapLayersOut)
def map_layers() -> MapLayersOut:
    f_geo, o_geo = _collections()
    layers = [
        MapLayerDef(id="findings", name="Published findings", type="vector", default_on=True),
        MapLayerDef(id="observation_footprints", name="Observation footprints",
                    type="vector", default_on=True),
        MapLayerDef(id="change_polygons", name="Change polygons",
                    type="vector", default_on=True, endpoint=CHANGE_GEOJSON_ENDPOINT),
        MapLayerDef(id="analysis_regions", name="Analysis regions",
                    type="vector", default_on=False, endpoint=ANALYSIS_GEOJSON_ENDPOINT),
    ]
    return MapLayersOut(
        layers=layers,
        findings_geojson=f_geo,
        observations_geojson=o_geo,
        change_polygons_geojson=_change_polygons_geojson(),
        analysis_regions_geojson=_analysis_regions_geojson(),
    )


@router.get("/map-layers/findings.geojson")
def findings_geojson() -> JSONResponse:
    f_geo, _ = _collections()
    return JSONResponse(content=f_geo, media_type="application/geo+json")


@router.get("/map-layers/change.geojson")
def change_geojson() -> JSONResponse:
    return JSONResponse(content=_change_polygons_geojson(), media_type="application/geo+json")


@router.get("/map-layers/analysis.geojson")
def analysis_geojson() -> JSONResponse:
    return JSONResponse(content=_analysis_regions_geojson(), media_type="application/geo+json")


@router.get("/history", response_model=HistoryPage)
def history(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> HistoryPage:
    """Analyses and discovery sweeps, newest first."""
    page_no, size = clamp_page(page, page_size)
    entries: List[HistoryEntry] = []
    with session_scope() as db:
        for job in db.query(Job).order_by(Job.created_at.desc(), Job.id.desc()).limit(500).all():
            entries.append(HistoryEntry(
                kind="analysis", id=job.id, label=job.label, status=job.status,
                created_at=job.created_at, findings_count=len(job.findings or []),
                bbox=list(job.bbox or []),
            ))
        for run in (db.query(DiscoveryRun)
                    .order_by(DiscoveryRun.created_at.desc(), DiscoveryRun.id.desc())
                    .limit(500).all()):
            entries.append(HistoryEntry(
                kind="discovery", id=run.id, label=run.label,
                status=run.status, created_at=run.created_at,
                findings_count=0, bbox=list(run.bbox or []),
            ))
    entries.sort(key=lambda e: e.created_at, reverse=True)
    window = paginate(entries, page_no, size)
    return HistoryPage(**window)  # type: ignore[arg-type]
