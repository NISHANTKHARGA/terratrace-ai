"""Serialisation helpers shared by the routers (ORM row -> contract shape)."""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from app.database.models import Evidence, Finding, Job, Observation
from app.schemas.api import (
    AnalysisJobOut,
    FindingDetailOut,
    FindingOut,
    LocationOut,
    ObservationOut,
)

MAX_PAGE_SIZE = 200


def clamp_page(page: Any, page_size: Any) -> Tuple[int, int]:
    try:
        p = max(1, int(page or 1))
    except (TypeError, ValueError):
        p = 1
    try:
        ps = int(page_size or 50)
    except (TypeError, ValueError):
        ps = 50
    return p, min(MAX_PAGE_SIZE, max(1, ps))


def paginate(items: Sequence[Any], page: int, page_size: int) -> Dict[str, Any]:
    total = len(items)
    start = (page - 1) * page_size
    return {"items": list(items[start:start + page_size]), "page": page,
            "page_size": page_size, "total": total}


# ------------------------------------------------------------------ observations
def observation_out(obs: Observation) -> ObservationOut:
    return ObservationOut(
        id=obs.id, provider_id=obs.provider_id, mission=obs.mission, platform=obs.platform,
        source=obs.source, product_type=obs.product_type, processing_level=obs.processing_level,
        datetime=obs.datetime, datetime_end=obs.datetime_end,
        polarizations=list(obs.polarizations or []), orbit_direction=obs.orbit_direction,
        bbox=list(obs.bbox) if obs.bbox else None, footprint=obs.footprint,
        url=obs.url, browse_url=obs.browse_url, requires_credentials=bool(obs.requires_credentials),
        size_mb=obs.size_mb, quality=obs.quality or {"valid_coverage": None, "notes": []},
        context=obs.context or {},
    )


def observations_from_rows(rows: Iterable[Observation]) -> List[ObservationOut]:
    return [observation_out(r) for r in rows]


# ------------------------------------------------------------------------ jobs
def job_out(job: Job) -> AnalysisJobOut:
    """Validate a stored job row against the response contract."""
    return AnalysisJobOut(
        id=job.id, label=job.label, status=job.status,  # type: ignore[arg-type]
        created_at=job.created_at, started_at=job.started_at, ended_at=job.ended_at,
        request=job.request or {}, bbox=list(job.bbox or []), progress=job.progress or 0.0,
        current_stage=job.current_stage, steps=job.steps or [],
        observations=job.observations or [], agents_selected=job.agents_selected or [],
        agent_runs=job.agent_runs or [], findings=list(job.findings or []),
        error=job.error, logs=list(job.logs or []), metrics=job.metrics,
    )


# -------------------------------------------------------------------- findings
def finding_out(finding: Finding) -> FindingOut:
    centroid = list(finding.centroid or [])
    return FindingOut(
        id=finding.id, title=finding.title, category=finding.category,  # type: ignore[arg-type]
        agent_id=finding.agent_id, job_id=finding.job_id,
        location=LocationOut(
            name=finding.location_name,
            bbox=list(finding.bbox or []),
            centroid=(centroid[0], centroid[1]) if len(centroid) == 2 else (0.0, 0.0),
        ),
        geometry=finding.geometry, geometry_source=finding.geometry_source,
        observation_dates=list(finding.observation_dates or []),
        sources=finding.sources or [], area_km2=finding.area_km2 or 0.0,
        detection_confidence=finding.detection_confidence or 0.0,
        evidence_completeness=finding.evidence_completeness or 0.0,
        data_quality=finding.data_quality or 0.0, severity=finding.severity,
        verification_status=finding.verification_status,  # type: ignore[arg-type]
        first_observed=finding.first_observed, method=finding.method,
        model_version=finding.model_version, created_at=finding.created_at,
        updated_at=finding.updated_at, assets=finding.assets or {},
        explanation=finding.explanation or "",
    )


def evidence_out(evidence: Optional[Evidence]) -> Optional[Dict[str, Any]]:
    if evidence is None:
        return None
    return {
        "summary": evidence.summary, "measurements": evidence.measurements or {},
        "supporting": evidence.supporting or [], "conflicting": evidence.conflicting or [],
        "uncertainty": evidence.uncertainty, "limitations": evidence.limitations or [],
        "method": evidence.method or {}, "persistence": evidence.persistence or {},
        "context_datasets": evidence.context_datasets or [],
    }


def finding_detail_out(finding: Finding, evidence: Optional[Evidence],
                       agent: Optional[Dict[str, Any]], job: Optional[Job],
                       source_observations: List[ObservationOut]) -> FindingDetailOut:
    base = finding_out(finding)
    return FindingDetailOut(
        **base.model_dump(),
        evidence=evidence_out(evidence),  # type: ignore[arg-type]
        agent=agent or {"id": finding.agent_id, "name": finding.agent_id, "status": "unknown"},
        job=({"id": job.id, "created_at": job.created_at, "status": job.status}
             if job is not None else None),
        source_observations=source_observations,
    )
