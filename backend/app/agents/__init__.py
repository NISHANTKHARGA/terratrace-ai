"""Agent registry: the twelve specialist agents in ordinal order."""
from __future__ import annotations

from typing import Dict, List, Optional

from app.agents.agriculture_agent.agent import AgricultureAgent
from app.agents.base import AgentCandidate, AgentContext, AgentResult, BaseAgent
from app.agents.coastal_agent.agent import CoastalAgent
from app.agents.deformation_agent.agent import DeformationAgent
from app.agents.flood_agent.agent import FloodAgent
from app.agents.forest_agent.agent import ForestAgent
from app.agents.glacier_agent.agent import GlacierAgent
from app.agents.landslide_agent.agent import LandslideAgent
from app.agents.mining_agent.agent import MiningAgent
from app.agents.unknown_change_agent.agent import UnknownChangeAgent
from app.agents.urban_agent.agent import UrbanAgent
from app.agents.wetlands_agent.agent import WetlandsAgent
from app.agents.wildfire_agent.agent import WildfireAgent

AGENT_CLASSES = [
    FloodAgent, WetlandsAgent, ForestAgent, WildfireAgent, DeformationAgent,
    GlacierAgent, LandslideAgent, AgricultureAgent, UrbanAgent, MiningAgent,
    CoastalAgent, UnknownChangeAgent,
]

# agents that must run after all others (they screen what is left over)
LATE_AGENTS = {"unknown_change"}


def build_agents() -> List[BaseAgent]:
    return [cls() for cls in AGENT_CLASSES]


def get_agent(agent_id: str) -> Optional[BaseAgent]:
    for cls in AGENT_CLASSES:
        inst = cls()
        if inst.id == agent_id:
            return inst
    return None


def agent_index() -> Dict[str, BaseAgent]:
    return {inst.id: inst for inst in build_agents()}


__all__ = [
    "BaseAgent", "AgentContext", "AgentResult", "AgentCandidate",
    "AGENT_CLASSES", "LATE_AGENTS", "build_agents", "get_agent", "agent_index",
]
