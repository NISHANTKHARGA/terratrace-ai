"""Data-source status endpoints plus the metadata-only discovery sweep."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter

from app.api.discovery import discover, persist_observations, record_discovery_run
from app.core.errors import AppError
from app.database.seed import seed_sources
from app.data_sources.registry import registry
from app.schemas.api import DataSourceStatusOut, DiscoveryOut, DiscoveryRequest, SourceListOut

router = APIRouter(tags=["sources"])


@router.get("/sources", response_model=SourceListOut)
def list_sources() -> SourceListOut:
    """Live status of every configured connector (cached for 5 minutes)."""
    return SourceListOut(items=registry.statuses(refresh=False))


@router.post("/sources/{source_id}/check", response_model=DataSourceStatusOut)
def check_source(source_id: str) -> DataSourceStatusOut:
    """Re-probe a single source right now and persist the result."""
    status = registry.check(source_id)
    seed_sources([status])
    return status


@router.post("/discovery/run", response_model=DiscoveryOut)
def run_discovery(req: DiscoveryRequest) -> DiscoveryOut:
    """Global discovery: metadata only, never downloads a raster."""
    if req.bbox is not None and len(req.bbox) != 4:
        raise AppError("invalid_bbox", "bbox must be [west, south, east, north]", 422)
    result = discover(
        bbox=req.bbox, start=req.start, end=req.end, mission=req.mission,
        limit=req.limit, use_cache=False,
    )
    observations = result["observations"]
    persist_observations(observations)
    run_id = record_discovery_run(
        bbox=req.bbox, start=req.start, end=req.end, mission=req.mission,
        limit=req.limit, observations=observations,
        sources_checked=result["sources_checked"],
    )
    return DiscoveryOut(job_id=run_id, observations=observations,
                        sources_checked=result["sources_checked"])
