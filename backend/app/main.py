"""TerraTrace AI — FastAPI application entry point.

Run with:  uvicorn app.main:app --reload --port 8000   (from backend/)
"""
from __future__ import annotations

import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import api_router
from app.config import BASE_DIR, settings
from app.core.errors import error_body, install_error_handlers
from app.core.logging import get_logger, setup_logging

log = get_logger("main")

FRONTEND_DIST = BASE_DIR.parent / "frontend" / "dist"


# --------------------------------------------------------------- lifespan
def _warm_sources() -> None:
    """Probe the catalogues in the background so the first UI call is fast."""
    try:
        from app.data_sources.registry import registry
        from app.database.seed import seed_sources

        statuses = registry.statuses(refresh=True)
        seed_sources(statuses)
        log.info("source probe complete",
                 extra={"extra_fields": {"sources": [s.id for s in statuses]}})
    except Exception as exc:  # never let a probe crash the service
        log.warning("source probe failed", extra={"extra_fields": {"error": str(exc)}})


@asynccontextmanager
async def lifespan(_: FastAPI):
    setup_logging(settings.log_level)
    from app.database.seed import seed_all
    from app.database.session import init_db

    init_db()
    seed_all(probe_sources=False)
    threading.Thread(target=_warm_sources, name="source-probe", daemon=True).start()
    log.info("TerraTrace AI started", extra={"extra_fields": {
        "version": settings.version, "database": settings.database_url}})
    yield
    from app.workers.jobs import runner

    runner.shutdown()


# --------------------------------------------------------------- app
app = FastAPI(
    title="TerraTrace AI",
    version=settings.version,
    description=(
        "Global multi-agent Earth-observation platform: discovers NISAR / Sentinel-1 / "
        "OPERA observations, runs real SAR change detection, and publishes "
        "evidence-backed candidate findings."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.api_prefix)
install_error_handlers(app)


@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=error_body("validation_error", "Request validation failed.",
                           detail=exc.errors()),
    )


@app.exception_handler(StarletteHTTPException)
async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = {404: "not_found", 405: "method_not_allowed"}.get(
        exc.status_code, "http_error")
    detail = exc.detail if isinstance(exc.detail, str) else None
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(code, detail or f"HTTP {exc.status_code}"),
        headers=getattr(exc, "headers", None),
    )


@app.get("/api", include_in_schema=False)
def api_root() -> dict:
    return {
        "name": settings.app_name,
        "version": settings.version,
        "docs": "/docs",
        "endpoints": [
            "/api/health", "/api/sources", "/api/observations", "/api/analysis",
            "/api/agents", "/api/findings", "/api/map-layers", "/api/history",
            "/api/datasets", "/api/models", "/api/training/runs", "/api/discovery/run",
        ],
    }


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
               include_in_schema=False)
def api_not_found(path: str) -> JSONResponse:
    """Guarantee the documented JSON error shape for unknown API routes."""
    return JSONResponse(status_code=404,
                        content=error_body("not_found", f"Unknown API route '/api/{path}'"))


# --------------------------------------------------------------- frontend
def _serve_frontend(path: str) -> FileResponse:
    """Serve the built React app (deep links fall back to index.html)."""
    if not FRONTEND_DIST.is_dir():
        raise FileNotFoundError(FRONTEND_DIST)
    target = (FRONTEND_DIST / path).resolve() if path else (FRONTEND_DIST / "index.html")
    if path and target.is_file() and FRONTEND_DIST.resolve() in target.parents:
        return FileResponse(target)
    index = FRONTEND_DIST / "index.html"
    if not index.is_file():
        raise FileNotFoundError(index)
    return FileResponse(index, media_type="text/html")


@app.get("/{full_path:path}", include_in_schema=False)
def spa(full_path: str):
    if not FRONTEND_DIST.is_dir():
        return JSONResponse({
            "name": settings.app_name,
            "message": "Frontend bundle not built. Run `npm install && npm run build` in "
                       "frontend/, or use the dev server on http://localhost:5173.",
            "api": "/api",
            "docs": "/docs",
        })
    try:
        return _serve_frontend(full_path)
    except FileNotFoundError:
        return JSONResponse({"error": {"code": "not_found",
                                       "message": "Frontend bundle is incomplete."}},
                            status_code=404)
