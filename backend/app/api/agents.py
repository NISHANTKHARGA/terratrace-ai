"""Agent catalogue: summaries, detail, configuration and honest status."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter

from app.agents import build_agents, get_agent
from app.core.errors import AppError
from app.database.models import AgentRecord
from app.database.session import session_scope
from app.schemas.api import AgentDetailOut, AgentListOut, AgentSummaryOut

router = APIRouter(prefix="/agents", tags=["agents"])


def _record(agent_id: str) -> Optional[AgentRecord]:
    with session_scope() as db:
        rec = db.get(AgentRecord, agent_id)
        if rec is not None:
            db.expunge(rec)
        return rec


@router.get("", response_model=AgentListOut)
def list_agents() -> AgentListOut:
    """All twelve specialists with their declared status and honest reason."""
    items = []
    for agent in build_agents():
        rec = _record(agent.id)
        last = rec.last_execution if rec is not None else None
        summary = agent.summary(last_execution=last)
        items.append(AgentSummaryOut(**summary))  # type: ignore[arg-type]
    return AgentListOut(items=items)


@router.get("/{agent_id}", response_model=AgentDetailOut)
def get_agent_detail(agent_id: str) -> AgentDetailOut:
    agent = get_agent(agent_id)
    if agent is None:
        raise AppError("not_found", f"Agent '{agent_id}' does not exist", 404)
    rec = _record(agent_id)
    last = rec.last_execution if rec is not None else None
    logs = list(rec.last_logs or []) if rec is not None else []
    detail = agent.detail(last_execution=last, logs=logs)
    return AgentDetailOut(**detail)  # type: ignore[arg-type]
