"""Data-source connector interface and shared HTTP helpers."""
from __future__ import annotations

import abc
import hashlib
import json
import time
from typing import Any, Dict, List, Optional, Sequence

import requests

from app.config import settings
from app.core.cache import DiskCache
from app.core.errors import UpstreamError
from app.schemas.api import DataSourceStatusOut, ObservationOut, ObservationQuality

http_cache = DiskCache(ttl_s=settings.cache_ttl_s)


def stable_observation_id(source: str, provider_id: str) -> str:
    return hashlib.sha1(f"{source}::{provider_id}".encode("utf-8")).hexdigest()[:24]


def http_get_json(
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: Optional[float] = None,
    use_cache: bool = True,
    session: Optional[requests.Session] = None,
    cache_key: Optional[str] = None,
) -> Any:
    key = cache_key or ("GET|" + url + "|" + json.dumps(params or {}, sort_keys=True, default=str))
    if use_cache:
        cached = http_cache.get_json(key)
        if cached is not None:
            return cached
    hdrs = {"User-Agent": settings.user_agent, "Client-Id": settings.client_id}
    if headers:
        hdrs.update(headers)
    getter = session.get if session is not None else requests.get
    try:
        resp = getter(url, params=params, headers=hdrs, timeout=timeout or settings.http_timeout_s)
    except requests.RequestException as exc:
        raise UpstreamError(url, f"network error: {exc}") from exc
    if resp.status_code >= 400:
        raise UpstreamError(url, f"HTTP {resp.status_code}", resp.text[:500])
    try:
        data = resp.json()
    except ValueError as exc:
        raise UpstreamError(url, "response was not JSON", resp.text[:300]) from exc
    if use_cache:
        http_cache.set_json(key, data)
    return data


def http_post_json(url: str, payload: Dict[str, Any], *, timeout: Optional[float] = None,
                   use_cache: bool = True) -> Any:
    key = "POST|" + url + "|" + json.dumps(payload, sort_keys=True, default=str)
    if use_cache:
        cached = http_cache.get_json(key)
        if cached is not None:
            return cached
    try:
        resp = requests.post(
            url,
            json=payload,
            headers={"User-Agent": settings.user_agent, "Client-Id": settings.client_id},
            timeout=timeout or settings.http_timeout_s,
        )
    except requests.RequestException as exc:
        raise UpstreamError(url, f"network error: {exc}") from exc
    if resp.status_code >= 400:
        raise UpstreamError(url, f"HTTP {resp.status_code}", resp.text[:500])
    data = resp.json()
    if use_cache:
        http_cache.set_json(key, data)
    return data


def http_probe(url: str, *, timeout: float = 12.0, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Cheap reachability probe used for the /api/sources panel."""
    started = time.time()
    try:
        resp = requests.get(
            url,
            params=params,
            headers={"User-Agent": settings.user_agent, "Client-Id": settings.client_id},
            timeout=timeout,
        )
        return {
            "ok": resp.status_code < 400,
            "status_code": resp.status_code,
            "elapsed_ms": int((time.time() - started) * 1000),
            "detail": f"HTTP {resp.status_code} in {int((time.time() - started) * 1000)} ms",
        }
    except requests.RequestException as exc:
        return {
            "ok": False,
            "status_code": None,
            "elapsed_ms": int((time.time() - started) * 1000),
            "detail": f"network error: {exc}",
        }


class DataSource(abc.ABC):
    """A provider of satellite observation metadata (and possibly rasters)."""

    id: str = "base"
    name: str = "Base"
    provider: str = "-"
    description: str = ""
    auth_required: bool = False

    @abc.abstractmethod
    def status(self) -> DataSourceStatusOut:
        raise NotImplementedError

    @abc.abstractmethod
    def search(
        self,
        bbox: Optional[Sequence[float]] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        mission: Optional[str] = None,
        limit: int = 50,
    ) -> List[ObservationOut]:
        raise NotImplementedError

    # helpers -------------------------------------------------------------
    @staticmethod
    def _quality(valid: Optional[float], notes: List[str]) -> ObservationQuality:
        return ObservationQuality(valid_coverage=valid, notes=notes)

    @staticmethod
    def _status(
        status: str, detail: str, checked_at: Optional[str] = None
    ) -> DataSourceStatusOut:
        return DataSourceStatusOut(
            id="",
            name="",
            description="",
            provider="",
            status=status,  # type: ignore[arg-type]
            detail=detail,
            checked_at=checked_at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            auth_required=False,
        )
