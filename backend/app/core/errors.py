"""Application errors with stable machine-readable codes."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        detail: Optional[Any] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.detail = detail


class NotFoundError(AppError):
    def __init__(self, resource: str, identifier: str) -> None:
        super().__init__("not_found", f"{resource} '{identifier}' not found", 404)


class UpstreamError(AppError):
    def __init__(self, source: str, message: str, detail: Any = None) -> None:
        super().__init__("upstream_error", f"{source}: {message}", 502, detail)


class UnsupportedAnalysisError(AppError):
    """Raised when the available products cannot support the requested analysis."""

    def __init__(self, reason: str) -> None:
        super().__init__("unsupported_analysis", reason, 422)


def error_body(code: str, message: str, detail: Any = None) -> Dict[str, Any]:
    body: Dict[str, Any] = {"error": {"code": code, "message": message}}
    if detail is not None:
        body["error"]["detail"] = detail
    return body


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(exc.code, exc.message, exc.detail),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content=error_body("internal_error", f"Unexpected server error: {exc}"),
        )
