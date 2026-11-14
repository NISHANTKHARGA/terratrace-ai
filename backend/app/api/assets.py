"""Derived artifact serving (PNG quicklooks, change GeoJSON) for analysis jobs."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.config import settings
from app.core.errors import AppError
from app.database.models import Job
from app.database.session import session_scope

router = APIRouter(prefix="/jobs", tags=["assets"])

MEDIA_TYPES = {
    ".png": "image/png",
    ".geojson": "application/geo+json",
    ".json": "application/json",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}


@router.get("/{job_id}/assets/{asset_name}")
def get_asset(job_id: str, asset_name: str) -> FileResponse:
    if Path(asset_name).name != asset_name or ".." in asset_name:
        raise AppError("invalid_asset", "Asset names must be plain file names.", 422)
    with session_scope() as db:
        if db.get(Job, job_id) is None:
            raise AppError("not_found", f"Analysis job '{job_id}' not found", 404)
    path = (settings.artifacts_dir / job_id / asset_name).resolve()
    root = settings.artifacts_dir.resolve()
    if root not in path.parents or not path.is_file():
        raise AppError("not_found", f"Asset '{asset_name}' was not produced by this job.",
                       404)
    media = MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media,
                        headers={"Cache-Control": "public, max-age=3600"})
