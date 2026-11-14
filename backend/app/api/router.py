"""Single router aggregating every documented API endpoint."""
from fastapi import APIRouter

from app.api import (
    agents,
    analysis,
    assets,
    catalog,
    findings,
    health,
    map_history,
    observations,
    sources,
    training,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(sources.router)
api_router.include_router(observations.router)
api_router.include_router(analysis.router)
api_router.include_router(agents.router)
api_router.include_router(findings.router)
api_router.include_router(map_history.router)
api_router.include_router(catalog.router)
api_router.include_router(assets.router)
api_router.include_router(training.router)
