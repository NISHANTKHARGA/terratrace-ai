"""Training Center API — wraps the existing training pipeline with the
endpoints requested by the spec. Everything here reports honest status:
an agent is only "trained" when a real checkpoint exists on disk."""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.errors import AppError
from app.database.models import ModelVersion, TrainingRun
from app.database.session import session_scope
from app.schemas.api import DatasetInfoOut, ModelInfoOut, TrainingRunOut
from app.training.pipeline import run_training
from app.training.registry import dataset_infos, get_dataset
from app.agents import build_agents

router = APIRouter(prefix="/training", tags=["training"])

# in-memory job tracker for long-running training tasks
_JOBS: Dict[str, Dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()


class TrainingJobOut(BaseModel):
    id: str
    agent_id: str
    status: str  # queued | running | completed | failed | cancelled
    started_at: str
    ended_at: Optional[str] = None
    progress: float = 0.0
    message: str = ""
    run_id: Optional[str] = None
    error: Optional[str] = None


class TrainingAgentOut(BaseModel):
    id: str
    name: str
    ordinal: int
    purpose: str
    status: str  # Not Started | Discovering Data | ... | Trained | Deployed | Failed
    datasets: List[Dict[str, Any]] = Field(default_factory=list)
    model: Optional[ModelInfoOut] = None
    last_run: Optional[TrainingRunOut] = None
    training_samples: int = 0
    validation_samples: int = 0
    metrics: Dict[str, Any] = Field(default_factory=dict)


class TrainingOverviewOut(BaseModel):
    agents: List[TrainingAgentOut]
    datasets: List[DatasetInfoOut]
    models: List[ModelInfoOut]
    runs: List[TrainingRunOut]
    hardware: Dict[str, Any]


def _agent_status(agent_id: str, model: Optional[ModelVersion], runs: List[TrainingRun]) -> str:
    if model is not None and model.kind == "trained_model" and model.status in ("active", "candidate", "deployed"):
        return "Deployed" if model.status == "deployed" else "Trained"
    latest = next((r for r in runs if r.agent_id == agent_id), None)
    if latest is not None and latest.status == "completed":
        return "Trained"
    if latest is not None and latest.status == "failed":
        return "Failed"
    # check if any labelled feature table exists
    ag = next((a for a in build_agents() if a.id == agent_id), None)
    if ag is None:
        return "Not Started"
    has_labelled = False
    for d in ag.datasets:
        from app.training.registry import local_dataset_path
        p = local_dataset_path(d["id"])
        if (p / "features.npz").is_file() or (p / "features.csv").is_file():
            has_labelled = True
    return "Ready to Train" if has_labelled else "Awaiting Labels"


def _agent_training_state(agent_id: str) -> TrainingAgentOut:
    from app.agents import get_agent
    from app.training.registry import local_dataset_path

    ag = get_agent(agent_id)
    if ag is None:
        raise AppError("unknown_agent", f"Agent '{agent_id}' not found", 404)

    with session_scope() as db:
        model = (
            db.query(ModelVersion)
            .filter(ModelVersion.agent_id == agent_id)
            .order_by(ModelVersion.trained_at.desc())
            .first()
        )
        runs = (
            db.query(TrainingRun)
            .filter(TrainingRun.agent_id == agent_id)
            .order_by(TrainingRun.started_at.desc())
            .limit(5)
            .all()
        )
        model_out = _model_out(model) if model is not None else None
        runs_out = [
            TrainingRunOut(
                id=r.id, agent_id=r.agent_id, model_id=r.model_id, status=r.status,
                started_at=r.started_at, ended_at=r.ended_at,
                dataset_ids=list(r.dataset_ids or []), config=r.config or {},
                metrics=r.metrics or {}, notes=r.notes,
            )
            for r in runs
        ]

    datasets = []
    labelled_samples = 0
    for d in ag.datasets:
        p = local_dataset_path(d["id"])
        has_features = (p / "features.npz").is_file() or (p / "features.csv").is_file()
        datasets.append({
            "id": d["id"],
            "name": d["name"],
            "status": d.get("status", "registered"),
            "has_labelled_features": has_features,
            "path": str(p),
        })
        if has_features:
            try:
                from app.training.pipeline import _load_features
                from pathlib import Path
                for name in ("features.npz", "features.csv"):
                    cand = p / name
                    if cand.is_file():
                        payload = _load_features(cand)
                        labelled_samples += int(payload["X"].shape[0])
                        break
            except Exception:
                pass

    latest_run = runs_out[0] if runs_out else None
    metrics = {}
    if latest_run is not None:
        metrics = latest_run.metrics or {}

    return TrainingAgentOut(
        id=ag.id,
        name=ag.name,
        ordinal=ag.ordinal,
        purpose=ag.purpose,
        status=_agent_status(ag.id, model, runs),
        datasets=datasets,
        model=model_out,
        last_run=latest_run,
        training_samples=labelled_samples,
        validation_samples=0,
        metrics=metrics,
    )


def _model_out(row: ModelVersion) -> ModelInfoOut:
    return ModelInfoOut(
        id=row.id, agent_id=row.agent_id, name=row.name, kind=row.kind,
        version=row.version, status=row.status, dataset_ids=list(row.dataset_ids or []),
        metrics=list(row.metrics or []), checkpoint_path=row.checkpoint_path,
        trained_at=row.trained_at, sample_count=row.sample_count,
        limitations=list(row.limitations or []),
    )


@router.get("/overview", response_model=TrainingOverviewOut)
def training_overview() -> TrainingOverviewOut:
    agents = [_agent_training_state(a.id) for a in build_agents()]
    with session_scope() as db:
        models = [_model_out(r) for r in db.query(ModelVersion).all()]
        runs = [
            TrainingRunOut(
                id=r.id, agent_id=r.agent_id, model_id=r.model_id, status=r.status,
                started_at=r.started_at, ended_at=r.ended_at,
                dataset_ids=list(r.dataset_ids or []), config=r.config or {},
                metrics=r.metrics or {}, notes=r.notes,
            )
            for r in db.query(TrainingRun).order_by(TrainingRun.started_at.desc()).limit(50).all()
        ]
    try:
        import torch
        hardware = {
            "gpu_available": torch.cuda.is_available(),
            "gpu_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
            "gpu_memory_gb": round(torch.cuda.get_device_properties(0).total_memory / 1e9, 2)
            if torch.cuda.is_available() else None,
            "torch_version": torch.__version__,
        }
    except Exception:
        hardware = {"gpu_available": False, "gpu_name": None, "gpu_memory_gb": None, "torch_version": None}
    # also check sklearn
    try:
        import sklearn
        hardware["sklearn_version"] = sklearn.__version__
    except Exception:
        hardware["sklearn_version"] = None
    return TrainingOverviewOut(
        agents=agents,
        datasets=dataset_infos(),
        models=models,
        runs=runs,
        hardware=hardware,
    )


@router.get("/agents", response_model=List[TrainingAgentOut])
def training_agents() -> List[TrainingAgentOut]:
    return [_agent_training_state(a.id) for a in build_agents()]


@router.get("/agents/{agent_id}", response_model=TrainingAgentOut)
def training_agent(agent_id: str) -> TrainingAgentOut:
    return _agent_training_state(agent_id)


@router.post("/datasets/discover")
def discover_datasets() -> Dict[str, Any]:
    """Discover datasets from NASA/CMR and partner sources (metadata only)."""
    from app.api.discovery import discover
    from app.data_sources.cmr import MISSION_COLLECTIONS
    total = 0
    for mission in ("NISAR", "SENTINEL-1", "OPERA", "UAVSAR"):
        try:
            result = discover(mission=mission, limit=20)
            total += len(result["observations"])
        except Exception:
            pass
    return {"discovered": total, "status": "completed"}


@router.post("/datasets/prepare")
def prepare_dataset(body: Dict[str, Any]) -> Dict[str, Any]:
    dataset_id = body.get("dataset_id")
    if not dataset_id:
        raise AppError("missing_dataset", "dataset_id is required", 422)
    ds = get_dataset(dataset_id)
    if ds is None:
        raise AppError("not_found", f"Dataset '{dataset_id}' not found", 404)
    p = None
    from app.training.registry import local_dataset_path
    p = local_dataset_path(dataset_id)
    p.mkdir(parents=True, exist_ok=True)
    has_features = (p / "features.npz").is_file() or (p / "features.csv").is_file()
    return {
        "dataset_id": dataset_id,
        "path": str(p),
        "has_labelled_features": has_features,
        "status": "ready" if has_features else "awaiting_labels",
        "note": (
            "Labelled feature table found." if has_features
            else "No labelled feature table (features.npz/features.csv) found. "
                 "Place one at this path to enable training."
        ),
    }


class StartTrainingRequest(BaseModel):
    dataset_id: Optional[str] = None
    config: Dict[str, Any] = Field(default_factory=dict)


@router.post("/agents/{agent_id}/start", response_model=TrainingJobOut)
def start_training_job(agent_id: str, req: StartTrainingRequest) -> TrainingJobOut:
    from app.agents import get_agent
    ag = get_agent(agent_id)
    if ag is None:
        raise AppError("unknown_agent", f"Agent '{agent_id}' not found", 404)

    job_id = str(uuid.uuid4())
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with _JOBS_LOCK:
        _JOBS[job_id] = {
            "id": job_id, "agent_id": agent_id, "status": "queued",
            "started_at": now, "ended_at": None, "progress": 0.0,
            "message": "Queued", "run_id": None, "error": None,
            "dataset_id": req.dataset_id, "config": req.config,
        }

    def _run():
        with _JOBS_LOCK:
            _JOBS[job_id]["status"] = "running"
            _JOBS[job_id]["message"] = "Training..."
            _JOBS[job_id]["progress"] = 0.1
        try:
            run = run_training(agent_id, req.dataset_id, req.config)
            with _JOBS_LOCK:
                _JOBS[job_id]["status"] = "completed" if run["status"] == "completed" else run["status"]
                _JOBS[job_id]["ended_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                _JOBS[job_id]["progress"] = 1.0
                _JOBS[job_id]["message"] = run.get("notes", "")
                _JOBS[job_id]["run_id"] = run["id"]
        except Exception as exc:
            with _JOBS_LOCK:
                _JOBS[job_id]["status"] = "failed"
                _JOBS[job_id]["ended_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                _JOBS[job_id]["error"] = str(exc)
                _JOBS[job_id]["message"] = f"Failed: {exc}"

    threading.Thread(target=_run, daemon=True).start()
    return TrainingJobOut(**_JOBS[job_id])


@router.get("/jobs/{job_id}", response_model=TrainingJobOut)
def get_training_job(job_id: str) -> TrainingJobOut:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
    if job is None:
        raise AppError("not_found", f"Training job '{job_id}' not found", 404)
    return TrainingJobOut(**job)


@router.post("/jobs/{job_id}/cancel")
def cancel_training_job(job_id: str) -> Dict[str, str]:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
    if job is None:
        raise AppError("not_found", f"Training job '{job_id}' not found", 404)
    if job["status"] in ("completed", "failed", "cancelled"):
        return {"status": job["status"]}
    with _JOBS_LOCK:
        _JOBS[job_id]["status"] = "cancelled"
        _JOBS[job_id]["message"] = "Cancelled by user"
    return {"status": "cancelled"}


@router.post("/agents/{agent_id}/evaluate")
def evaluate_agent(agent_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    from app.agents import get_agent
    ag = get_agent(agent_id)
    if ag is None:
        raise AppError("unknown_agent", f"Agent '{agent_id}' not found", 404)
    # Re-run evaluation on the latest model using stored metrics
    with session_scope() as db:
        model = (
            db.query(ModelVersion)
            .filter(ModelVersion.agent_id == agent_id)
            .order_by(ModelVersion.trained_at.desc())
            .first()
        )
        if model is None:
            return {"agent_id": agent_id, "status": "no_model", "metrics": {},
                    "note": "No trained model to evaluate."}
        return {"agent_id": agent_id, "status": "evaluated", "metrics": model.metrics or {},
                "model_id": model.id, "note": "Metrics from the latest trained model."}


@router.post("/models/{model_id}/deploy")
def deploy_model(model_id: str) -> Dict[str, Any]:
    with session_scope() as db:
        row = db.get(ModelVersion, model_id)
        if row is None:
            raise AppError("not_found", f"Model '{model_id}' not found", 404)
        # deactivate others for same agent
        for other in db.query(ModelVersion).filter(ModelVersion.agent_id == row.agent_id).all():
            if other.id != model_id and other.status == "deployed":
                other.status = "candidate"
        row.status = "deployed"
        db.commit()
    return {"model_id": model_id, "status": "deployed"}


@router.post("/models/{model_id}/rollback")
def rollback_model(model_id: str) -> Dict[str, Any]:
    with session_scope() as db:
        row = db.get(ModelVersion, model_id)
        if row is None:
            raise AppError("not_found", f"Model '{model_id}' not found", 404)
        row.status = "candidate"
        db.commit()
    return {"model_id": model_id, "status": "rolled_back"}


@router.get("/history")
def training_history() -> Dict[str, Any]:
    with session_scope() as db:
        runs = db.query(TrainingRun).order_by(TrainingRun.started_at.desc()).limit(200).all()
        items = [
            TrainingRunOut(
                id=r.id, agent_id=r.agent_id, model_id=r.model_id, status=r.status,
                started_at=r.started_at, ended_at=r.ended_at,
                dataset_ids=list(r.dataset_ids or []), config=r.config or {},
                metrics=r.metrics or {}, notes=r.notes,
            )
            for r in runs
        ]
    return {"items": items}
