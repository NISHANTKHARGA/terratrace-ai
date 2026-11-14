"""Analysis job submission, polling and cancellation."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query, Response

from app.api.deps import clamp_page, job_out, paginate
from app.core.errors import AppError
from app.database.models import Job
from app.database.session import session_scope
from app.orchestrator.engine import submit_analysis
from app.schemas.api import AnalysisJobOut, AnalysisRequest, CancelOut, JobListOut
from app.workers.jobs import runner

router = APIRouter(prefix="/analysis", tags=["analysis"])


@router.post("", response_model=AnalysisJobOut, status_code=202)
def create_analysis(req: AnalysisRequest, response: Response) -> AnalysisJobOut:
    """Queue a new multi-agent analysis (runs in the background)."""
    if not req.bbox and not req.polygon:
        raise AppError("missing_region", "Provide either 'bbox' [w,s,e,n] or a GeoJSON "
                                         "'polygon' to analyse.", 422)
    if req.start > req.end:
        raise AppError("invalid_period", "'start' must be on or before 'end'.", 422)
    job_id = submit_analysis(req)
    with session_scope() as db:
        job = db.get(Job, job_id)
        if job is None:  # pragma: no cover
            raise AppError("not_found", f"job {job_id} vanished", 500)
        return job_out(job)


@router.get("", response_model=JobListOut)
def list_analysis(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    status: Optional[str] = Query(None),
) -> JobListOut:
    """Analysis history, newest first."""
    page_no, size = clamp_page(page, page_size)
    with session_scope() as db:
        q = db.query(Job)
        if status:
            q = q.filter(Job.status == status)
        rows = q.order_by(Job.created_at.desc(), Job.id.desc()).all()
        window = paginate([job_out(r) for r in rows], page_no, size)
    return JobListOut(**window)  # type: ignore[arg-type]


@router.get("/{job_id}", response_model=AnalysisJobOut)
def get_analysis(job_id: str) -> AnalysisJobOut:
    """Poll this endpoint for progress (progress, current_stage, logs, steps)."""
    with session_scope() as db:
        job = db.get(Job, job_id)
        if job is None:
            raise AppError("not_found", f"Analysis job '{job_id}' not found", 404)
        return job_out(job)


@router.post("/{job_id}/cancel", response_model=CancelOut)
def cancel_analysis(job_id: str) -> CancelOut:
    """Request cooperative cancellation of a queued/running job."""
    with session_scope() as db:
        job = db.get(Job, job_id)
        if job is None:
            raise AppError("not_found", f"Analysis job '{job_id}' not found", 404)
        if job.status in ("succeeded", "failed", "cancelled"):
            return CancelOut(status=job.status)  # type: ignore[arg-type]
        job.cancel_requested = True
        status = job.status
    runner.cancel(job_id)
    return CancelOut(status=status)  # type: ignore[arg-type]
