"""Observation search, detail and quicklook proxying."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import requests
from fastapi import APIRouter, Query
from fastapi.responses import Response

from app.api.deps import clamp_page, observation_out, paginate
from app.api.discovery import discover, persist_observations
from app.config import settings
from app.core.errors import AppError
from app.core.geo import validate_bbox
from app.database.models import Observation
from app.database.session import session_scope
from app.schemas.api import ObservationOut, ObservationPage

router = APIRouter(tags=["observations"])


def _parse_bbox(bbox: Optional[str]):
    if not bbox:
        return None
    parts = [p for p in bbox.replace(";", ",").split(",") if p.strip() != ""]
    if len(parts) != 4:
        raise AppError("invalid_bbox", "bbox must be four comma-separated numbers "
                                       "(west,south,east,north)", 422)
    try:
        return validate_bbox([float(p) for p in parts])
    except ValueError as exc:
        raise AppError("invalid_bbox", str(exc), 422) from exc


@router.get("/observations", response_model=ObservationPage)
def list_observations(
    bbox: Optional[str] = Query(None, description="west,south,east,north"),
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    mission: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> ObservationPage:
    """Live catalogue search across the configured sources (metadata only)."""
    box = _parse_bbox(bbox)
    result = discover(bbox=box, start=start, end=end, mission=mission,
                      limit=max(50, page * page_size))
    items = result["observations"]
    if source:
        items = [o for o in items if o.source == source]
    persist_observations(items)
    page_no, size = clamp_page(page, page_size)
    window = paginate(items, page_no, size)
    return ObservationPage(**window)  # type: ignore[arg-type]


@router.get("/observations/{observation_id}", response_model=ObservationOut)
def get_observation(observation_id: str) -> ObservationOut:
    with session_scope() as db:
        row = db.get(Observation, observation_id)
        if row is None:
            raise AppError("not_found", f"Observation '{observation_id}' not found", 404)
        return observation_out(row)


@router.get("/observations/{observation_id}/browse")
def get_browse(observation_id: str) -> Response:
    """Proxy the provider's quicklook PNG (cached on disk, never re-encoded)."""
    with session_scope() as db:
        row = db.get(Observation, observation_id)
        if row is None:
            raise AppError("not_found", f"Observation '{observation_id}' not found", 404)
        browse_url = row.browse_url
        if not browse_url:
            raise AppError("no_browse_image",
                           "This observation has no browse/quicklook image.", 404)

    cache_dir = settings.cache_dir / "browse"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{observation_id}.png"
    if cache_path.is_file() and (time.time() - cache_path.stat().st_mtime) < 7 * 86400:
        return Response(content=cache_path.read_bytes(), media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})
    try:
        resp = requests.get(
            browse_url, timeout=settings.http_timeout_s,
            headers={"User-Agent": settings.user_agent}, stream=True,
        )
        if resp.status_code >= 400:
            raise AppError("upstream_error",
                           f"Provider returned HTTP {resp.status_code} for the quicklook.",
                           502)
        data = resp.content
        if not data:
            raise AppError("upstream_error", "Provider returned an empty quicklook.", 502)
        cache_path.write_bytes(data)
    except AppError:
        raise
    except Exception as exc:
        raise AppError("upstream_error", f"Could not fetch quicklook: {exc}", 502) from exc
    return Response(content=data, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=86400"})
