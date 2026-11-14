"""Metadata-only discovery helpers shared by the observations/discovery routes."""
from __future__ import annotations

import json
import threading
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.core.logging import get_logger
from app.database.models import Observation, now_iso, new_id
from app.database.session import session_scope
from app.data_sources.registry import registry
from app.schemas.api import ObservationOut

log = get_logger("api.discovery")

CACHE_TTL_S = 90.0
_cache: Dict[str, Tuple] = {}
_cache_lock = threading.Lock()


def _cache_get(key: str):
    with _cache_lock:
        hit = _cache.get(key)
        if hit and (time.time() - hit[0]) < CACHE_TTL_S:
            return hit[1]
    return None


def _cache_set(key: str, value) -> None:
    with _cache_lock:
        if len(_cache) > 64:  # bounded
            _cache.clear()
        _cache[key] = (time.time(), value)


def discover(
    *,
    bbox: Optional[Sequence[float]] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    mission: Optional[str] = None,
    limit: int = 50,
    sources: Optional[Sequence[str]] = None,
    use_cache: bool = True,
) -> Dict[str, Any]:
    """Fan out to the configured catalogues (metadata only, no raster reads)."""
    key = json.dumps({
        "bbox": list(bbox) if bbox else None, "start": start, "end": end,
        "mission": mission, "limit": limit, "sources": list(sources) if sources else None,
    }, sort_keys=True, default=str)
    if use_cache:
        cached = _cache_get(key)
        if cached is not None:
            return cached
    result = registry.search(bbox=bbox, start=start, end=end, mission=mission,
                             limit=limit, sources=sources)
    if mission:
        result["observations"] = [o for o in result["observations"]
                                  if (o.mission or "").upper() == mission.upper()]
    _cache_set(key, result)
    return result


def persist_observations(items: Sequence[ObservationOut]) -> int:
    """Upsert discovered observations so they are queryable later."""
    stored = 0
    with session_scope() as db:
        for obs in items:
            payload = obs.model_dump()
            obs_id = payload.pop("id", obs.id)
            row = db.get(Observation, obs_id)
            if row is None:
                db.add(Observation(id=obs_id, **payload, first_seen=now_iso()))
                stored += 1
            else:
                for k, v in payload.items():
                    setattr(row, k, v)
    return stored


def record_discovery_run(
    *,
    bbox: Optional[Sequence[float]],
    start: Optional[str],
    end: Optional[str],
    mission: Optional[str],
    limit: int,
    observations: Sequence[ObservationOut],
    sources_checked: Sequence[Dict[str, Any]],
) -> str:
    run_id = new_id("dis")
    with session_scope() as db:
        from app.database.models import DiscoveryRun

        db.add(DiscoveryRun(
            id=run_id, label=None, bbox=list(bbox) if bbox else None,
            start=start, end=end, mission=mission, limit=limit,
            observations_count=len(observations),
            sources_checked=[dict(s) for s in sources_checked],
            status="completed", created_at=now_iso(),
        ))
    return run_id
