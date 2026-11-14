# Supabase Storage integration for TerraTrace AI artifacts.
# When SUPABASE_URL and SUPABASE_KEY are set, artifacts are stored in
# Supabase Storage. Otherwise, falls back to local filesystem.

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from app.config import settings
from app.core.logging import get_logger

log = get_logger("storage.supabase")

_supabase_client = None


def _get_client():
    global _supabase_client
    if _supabase_client is not None:
        return _supabase_client
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_KEY", "")
    if not url or not key:
        return None
    try:
        from supabase import create_client
        _supabase_client = create_client(url, key)
        return _supabase_client
    except Exception as exc:
        log.warning("Supabase client init failed: %s", exc)
        return None


def is_supabase_enabled() -> bool:
    return _get_client() is not None


def upload_artifact(job_id: str, filename: str, data: bytes) -> Optional[str]:
    """Upload an artifact file. Returns a public URL or None (falls back to local)."""
    client = _get_client()
    if client is None:
        return None
    bucket = os.getenv("SUPABASE_STORAGE_BUCKET", "terratrace-artifacts")
    path = f"{job_id}/{filename}"
    try:
        client.storage.from_(bucket).upload(path, data, {"content-type": _mime(filename)})
        url = client.storage.from_(bucket).get_public_url(path)
        return url
    except Exception as exc:
        log.warning("Supabase upload failed for %s/%s: %s", job_id, filename, exc)
        return None


def download_artifact(job_id: str, filename: str) -> Optional[bytes]:
    """Download an artifact file from Supabase Storage."""
    client = _get_client()
    if client is None:
        return None
    bucket = os.getenv("SUPABASE_STORAGE_BUCKET", "terratrace-artifacts")
    path = f"{job_id}/{filename}"
    try:
        return client.storage.from_(bucket).download(path)
    except Exception as exc:
        log.warning("Supabase download failed for %s/%s: %s", job_id, filename, exc)
        return None


def _mime(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".geojson": "application/geo+json",
        ".json": "application/json",
        ".tif": "image/tiff",
        ".tiff": "image/tiff",
    }.get(ext, "application/octet-stream")
