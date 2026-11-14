"""Dataset, model and training-run endpoints."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.errors import AppError
from app.database.models import ModelVersion, TrainingRun
from app.database.session import session_scope
from app.schemas.api import (
    DatasetInfoOut,
    DatasetListOut,
    ModelInfoOut,
    ModelListOut,
    TrainingRunListOut,
    TrainingRunOut,
)
from app.training.pipeline import run_training
from app.training.registry import dataset_infos

router = APIRouter(tags=["catalog"])


@router.get("/datasets", response_model=DatasetListOut)
def list_datasets() -> DatasetListOut:
    """Every dataset this deployment knows about, with an honest access status."""
    return DatasetListOut(items=dataset_infos())


def _model_out(row: ModelVersion) -> ModelInfoOut:
    return ModelInfoOut(
        id=row.id, agent_id=row.agent_id, name=row.name, kind=row.kind,
        version=row.version, status=row.status, dataset_ids=list(row.dataset_ids or []),
        metrics=list(row.metrics or []), checkpoint_path=row.checkpoint_path,
        trained_at=row.trained_at, sample_count=row.sample_count,
        limitations=list(row.limitations or []),
    )


@router.get("/models", response_model=ModelListOut)
def list_models() -> ModelListOut:
    with session_scope() as db:
        rows = db.query(ModelVersion).order_by(ModelVersion.agent_id, ModelVersion.id).all()
        return ModelListOut(items=[_model_out(r) for r in rows])


@router.get("/models/{model_id:path}", response_model=ModelInfoOut)
def get_model(model_id: str) -> ModelInfoOut:
    with session_scope() as db:
        row = db.get(ModelVersion, model_id)
        if row is None:
            raise AppError("not_found", f"Model '{model_id}' not found", 404)
        return _model_out(row)


@router.get("/training/runs", response_model=TrainingRunListOut)
def list_training_runs() -> TrainingRunListOut:
    with session_scope() as db:
        rows = db.query(TrainingRun).order_by(TrainingRun.started_at.desc()).limit(200).all()
        items = [TrainingRunOut(
            id=r.id, agent_id=r.agent_id, model_id=r.model_id, status=r.status,
            started_at=r.started_at, ended_at=r.ended_at,
            dataset_ids=list(r.dataset_ids or []), config=r.config or {},
            metrics=r.metrics or {}, notes=r.notes,
        ) for r in rows]
    return TrainingRunListOut(items=items)


class TrainingRequest(BaseModel):
    agent_id: str
    dataset_id: Optional[str] = None
    config: Dict[str, Any] = Field(default_factory=dict)


@router.post("/training/runs", response_model=TrainingRunOut, status_code=201)
def start_training(req: TrainingRequest) -> TrainingRunOut:
    """Fit a model against a *real* labelled dataset, or report why it cannot."""
    run = run_training(req.agent_id, req.dataset_id, req.config)
    return TrainingRunOut(**run)  # type: ignore[arg-type]
