"""Model store: resolve registered models and load real checkpoints.

Agents fall back to their declared baseline algorithm whenever no trained
checkpoint exists — the store never fabricates a model.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.logging import get_logger
from app.database.models import ModelVersion
from app.database.session import session_scope

log = get_logger("inference.model_store")


class ModelStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._estimators: Dict[str, Any] = {}

    # ------------------------------------------------------------- registry
    def get(self, model_id: str) -> Optional[ModelVersion]:
        with session_scope() as db:
            rec = db.get(ModelVersion, model_id)
            if rec is None:
                return None
            db.expunge(rec)
            return rec

    def list(self, agent_id: Optional[str] = None) -> List[ModelVersion]:
        with session_scope() as db:
            q = db.query(ModelVersion)
            if agent_id:
                q = q.filter(ModelVersion.agent_id == agent_id)
            rows = q.order_by(ModelVersion.agent_id, ModelVersion.version).all()
            for r in rows:
                db.expunge(r)
            return rows

    def active_for(self, agent_id: str) -> List[ModelVersion]:
        return [m for m in self.list(agent_id) if m.status in ("active", "candidate")]

    # ------------------------------------------------------------ estimator
    def load_estimator(self, model_id: str) -> Optional[Any]:
        """Load a joblib checkpoint; returns None when no checkpoint exists."""
        with self._lock:
            if model_id in self._estimators:
                return self._estimators[model_id]
        rec = self.get(model_id)
        if rec is None or not rec.checkpoint_path:
            return None
        path = Path(rec.checkpoint_path)
        if not path.is_file():
            log.warning("checkpoint missing on disk", extra={"extra_fields": {
                "model_id": model_id, "path": str(path)}})
            return None
        try:
            import joblib

            payload = joblib.load(path)
            estimator = payload.get("estimator", payload) if isinstance(payload, dict) else payload
        except Exception as exc:
            log.warning("checkpoint unreadable", extra={"extra_fields": {
                "model_id": model_id, "error": str(exc)}})
            return None
        with self._lock:
            self._estimators[model_id] = estimator
        return estimator

    def predict(self, model_id: str, features: Any) -> Optional[Any]:
        """Run a real model when one exists; None means 'use the baseline'."""
        est = self.load_estimator(model_id)
        if est is None:
            return None
        try:
            return est.predict(features)
        except Exception as exc:
            log.warning("prediction failed", extra={"extra_fields": {
                "model_id": model_id, "error": str(exc)}})
            return None

    def invalidate(self) -> None:
        with self._lock:
            self._estimators.clear()


model_store = ModelStore()
