"""Idempotent database seeding: agents, datasets, baseline models, sources.

Seeding never invents evaluation numbers — baseline models carry the metrics the
agent modules declare, which are ``null`` (never measured) until a real labelled
dataset is trained against.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from app.agents import build_agents
from app.core.logging import get_logger
from app.database.models import AgentRecord, DatasetRecord, ModelVersion, SourceStatusRecord, now_iso
from app.database.session import session_scope
from app.training.registry import dataset_catalog

log = get_logger("database.seed")


def seed_agents() -> int:
    count = 0
    with session_scope() as db:
        for agent in build_agents():
            rec = db.get(AgentRecord, agent.id)
            payload = dict(
                ordinal=agent.ordinal, name=agent.name, purpose=agent.purpose,
                status=agent.status, status_reason=agent.status_reason,
                model_version=agent.model_version, baseline_method=agent.baseline_method,
                capabilities=list(agent.capabilities), supported_inputs=list(agent.supported_inputs),
                datasets=list(agent.datasets), evaluation=list(agent.evaluation),
                config=dict(agent.config), output_schema=dict(agent.output_schema),
                known_limitations=list(agent.known_limitations), updated_at=now_iso(),
            )
            if rec is None:
                db.add(AgentRecord(id=agent.id, **payload))
                count += 1
            else:
                for k, v in payload.items():
                    setattr(rec, k, v)
    return count


def seed_datasets() -> int:
    count = 0
    with session_scope() as db:
        for entry in dataset_catalog().values():
            rec = db.get(DatasetRecord, entry["id"])
            payload = dict(
                name=entry["name"], agent_ids=list(entry["agent_ids"]),
                status=entry["status"], access=entry.get("access", ""),
                url=entry.get("url"), note=entry.get("note", ""),
            )
            if rec is None:
                db.add(DatasetRecord(id=entry["id"], **payload))
                count += 1
            else:
                for k, v in payload.items():
                    setattr(rec, k, v)
    return count


def seed_models() -> int:
    """Register one baseline model per agent (no metrics unless measured)."""
    count = 0
    with session_scope() as db:
        for agent in build_agents():
            model_id = f"{agent.id}:baseline"
            rec = db.get(ModelVersion, model_id)
            metrics = [
                {"name": m.get("metric", "metric"), "value": m.get("value"),
                 "split": None, "note": m.get("note", "")}
                for m in agent.evaluation
            ]
            payload = dict(
                agent_id=agent.id, name=f"{agent.name} baseline", kind="baseline_algorithm",
                version=agent.model_version, status="active",
                dataset_ids=[d["id"] for d in agent.datasets], metrics=metrics,
                checkpoint_path=None, trained_at=None, sample_count=None,
                limitations=list(agent.known_limitations),
                config={"baseline_method": agent.baseline_method},
            )
            if rec is None:
                db.add(ModelVersion(id=model_id, **payload))
                count += 1
            else:
                for k, v in payload.items():
                    setattr(rec, k, v)
    return count


def seed_sources(statuses: Optional[List[Any]] = None) -> int:
    """Persist data-source status rows (probe results may be supplied later)."""
    count = 0
    rows = statuses or []
    with session_scope() as db:
        for st in rows:
            rec = db.get(SourceStatusRecord, st.id)
            payload = dict(
                name=st.name, description=st.description, provider=st.provider,
                status=st.status, detail=st.detail, auth_required=st.auth_required,
                checked_at=st.checked_at or now_iso(),
            )
            if rec is None:
                db.add(SourceStatusRecord(id=st.id, **payload))
                count += 1
            else:
                for k, v in payload.items():
                    setattr(rec, k, v)
    return count


def seed_all(probe_sources: bool = False) -> Dict[str, int]:
    """Create/refresh every catalog row. Safe to call on every startup."""
    result = {
        "agents": seed_agents(),
        "datasets": seed_datasets(),
        "models": seed_models(),
        "sources": 0,
    }
    if probe_sources:
        try:
            from app.data_sources.registry import registry

            result["sources"] = seed_sources(registry.statuses(refresh=True))
        except Exception as exc:  # never block startup on a network probe
            log.warning("source probe during seed failed", extra={"extra_fields": {"error": str(exc)}})
    log.info("seed complete", extra={"extra_fields": result})
    return result
