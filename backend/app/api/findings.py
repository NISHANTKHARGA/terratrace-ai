"""Finding query, evidence, GeoJSON export and HTML report endpoints."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.agents import get_agent
from app.api.deps import clamp_page, evidence_out, finding_detail_out, finding_out, paginate
from app.core.errors import AppError
from app.core.geo import geom_from_geojson, overlap_ratio, validate_bbox
from app.database.models import Evidence, Finding, Job, Observation
from app.database.session import session_scope
from app.reports.report import finding_geojson, render_report
from app.schemas.api import EvidenceResponse, FindingDetailOut, FindingPage

router = APIRouter(prefix="/findings", tags=["findings"])


def _query_filters(category: Optional[str], status: Optional[str], job_id: Optional[str]):
    conds = []
    if category:
        conds.append(Finding.category == category)
    if status:
        conds.append(Finding.verification_status == status)
    if job_id:
        conds.append(Finding.job_id == job_id)
    return conds


def _bbox_filter(rows: List[Finding], bbox_str: str) -> List[Finding]:
    try:
        w, s, e, n = validate_bbox([float(v) for v in bbox_str.split(",")])
    except Exception as exc:
        raise AppError("invalid_bbox", f"invalid bbox '{bbox_str}': {exc}", 422) from exc
    from shapely.geometry import box

    target = box(w, s, e, n)
    out: List[Finding] = []
    for row in rows:
        try:
            geom = geom_from_geojson(row.geometry) if row.geometry else (
                box(*row.bbox) if row.bbox and len(row.bbox) == 4 else None)
            if geom is None or geom.is_empty:
                continue
            if overlap_ratio(geom, target) > 0 or geom.intersects(target):
                out.append(row)
        except Exception:
            continue
    return out


@router.get("", response_model=FindingPage)
def list_findings(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    category: Optional[str] = Query(None),
    status: Optional[str] = Query(None, alias="status"),
    job_id: Optional[str] = Query(None),
    bbox: Optional[str] = Query(None, description="west,south,east,north filter"),
) -> FindingPage:
    page_no, size = clamp_page(page, page_size)
    with session_scope() as db:
        q = db.query(Finding)
        for cond in _query_filters(category, status, job_id):
            q = q.filter(cond)
        rows = q.order_by(Finding.created_at.desc(), Finding.id.desc()).all()
        if bbox:
            rows = _bbox_filter(rows, bbox)
        window = paginate([finding_out(r) for r in rows], page_no, size)
    return FindingPage(**window)  # type: ignore[arg-type]


def _load(finding_id: str):
    with session_scope() as db:
        finding = db.get(Finding, finding_id)
        if finding is None:
            raise AppError("not_found", f"Finding '{finding_id}' not found", 404)
        evidence = db.get(Evidence, finding_id)
        job = db.get(Job, finding.job_id) if finding.job_id else None
        source_observations: List[Observation] = []
        if job is not None and job.observations:
            wanted = {s.get("provider_id") for s in (finding.sources or []) if isinstance(s, dict)}
            for payload in job.observations:
                if isinstance(payload, dict) and payload.get("provider_id") in wanted:
                    obs = db.get(Observation, payload.get("id"))
                    if obs is not None:
                        source_observations.append(obs)
        for obj in (finding, evidence, job, *source_observations):
            if obj is not None:
                db.expunge(obj)
        return finding, evidence, job, source_observations


@router.get("/{finding_id}", response_model=FindingDetailOut)
def get_finding(finding_id: str) -> FindingDetailOut:
    finding, evidence, job, obs_rows = _load(finding_id)
    agent_obj = get_agent(finding.agent_id)
    agent_info = None
    if agent_obj is not None:
        from app.api.agents import _record

        rec = _record(finding.agent_id)
        agent_info = {"id": agent_obj.id, "name": agent_obj.name,
                      "status": rec.status if rec is not None else agent_obj.status}
    from app.api.deps import observations_from_rows

    return finding_detail_out(finding, evidence, agent_info, job,
                              observations_from_rows(obs_rows))


@router.get("/{finding_id}/evidence", response_model=EvidenceResponse)
def get_evidence(finding_id: str) -> EvidenceResponse:
    finding, evidence, _, _ = _load(finding_id)
    payload = evidence_out(evidence) or {
        "summary": "No evidence record was stored for this finding.",
        "measurements": {}, "supporting": [], "conflicting": [],
        "uncertainty": "Evidence row missing — treat this finding as unverified.",
        "limitations": ["Evidence record absent."], "method": {}, "persistence": {},
        "context_datasets": [],
    }
    return EvidenceResponse(finding_id=finding_id, evidence=payload)  # type: ignore[arg-type]


@router.get("/{finding_id}/export.geojson")
def export_finding(finding_id: str) -> JSONResponse:
    finding, evidence, _, _ = _load(finding_id)
    feature = finding_geojson(finding.__dict__, evidence_out(evidence))
    return JSONResponse(
        content={"type": "FeatureCollection", "features": [feature]},
        media_type="application/geo+json",
        headers={"Content-Disposition": f'attachment; filename="{finding_id}.geojson"'},
    )


@router.get("/{finding_id}/report", response_class=HTMLResponse)
def finding_report(finding_id: str, request: Request) -> HTMLResponse:
    finding, evidence, job, obs_rows = _load(finding_id)
    agent_obj = get_agent(finding.agent_id)
    agent_info = None
    if agent_obj is not None:
        from app.api.agents import _record

        rec = _record(finding.agent_id)
        agent_info = {"id": agent_obj.id, "name": agent_obj.name,
                      "status": rec.status if rec is not None else agent_obj.status}
    from app.api.deps import observations_from_rows

    base = str(request.base_url).rstrip("/")
    html = render_report(
        finding.__dict__, evidence_out(evidence), agent=agent_info,
        job=(job.__dict__ if job is not None else None),
        observations=[o.model_dump() for o in observations_from_rows(obs_rows)],
        base_url=base,
    )
    return HTMLResponse(html, headers={"Cache-Control": "private, max-age=60"})
