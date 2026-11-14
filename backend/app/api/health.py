"""Liveness, version and honest data-source reporting."""
from __future__ import annotations

import time
from typing import Any, Dict

from fastapi import APIRouter
from sqlalchemy import text

from app.agents import build_agents
from app.config import settings
from app.core.logging import get_logger
from app.database.models import Finding, Job, Observation
from app.database.session import SessionLocal
from app.data_sources.registry import registry
from app.schemas.api import HealthCounts, HealthOut

log = get_logger("api.health")
router = APIRouter(tags=["health"])


def _database_status() -> str:
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return "ok"
    except Exception as exc:  # pragma: no cover
        log.warning("database check failed", extra={"extra_fields": {"error": str(exc)}})
        return "error"


@router.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    """Service health plus a live count of what has actually been ingested."""
    sources = registry.statuses(refresh=False)
    db_state = _database_status()
    counts = HealthCounts(observations=0, findings=0, jobs=0, agents=len(build_agents()))
    if db_state == "ok":
        try:
            with SessionLocal() as db:
                counts.observations = db.query(Observation).count()
                counts.findings = db.query(Finding).count()
                counts.jobs = db.query(Job).count()
        except Exception as exc:  # pragma: no cover
            log.warning("count query failed", extra={"extra_fields": {"error": str(exc)}})
            db_state = "error"

    degraded = db_state != "ok" or any(
        s.status in ("unavailable",) for s in sources
    )
    return HealthOut(
        status="degraded" if degraded else "ok",
        version=settings.version,
        time=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        database=db_state,  # type: ignore[arg-type]
        sources=sources, counts=counts,
    )
