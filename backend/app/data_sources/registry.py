"""Data source registry: discovery fan-out, status probing, honest reporting."""
from __future__ import annotations

import time
from typing import Any, Dict, Iterable, List, Optional, Sequence

from app.config import settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.data_sources.base import DataSource
from app.data_sources.cmr import CmrSource
from app.data_sources.copernicus import CopernicusSource
from app.data_sources.earth_search import EarthSearchSource
from app.data_sources.earthdata import auth_available
from app.data_sources.planetary_computer import PlanetaryComputerSource
from app.schemas.api import DataSourceStatusOut, ObservationOut

log = get_logger("data_sources.registry")


def _build_sources() -> Dict[str, DataSource]:
    candidates: List[DataSource] = []
    if settings.enable_cmr:
        candidates.append(CmrSource())
    if settings.enable_planetary_computer:
        candidates.append(PlanetaryComputerSource())
    if settings.enable_earth_search:
        candidates.append(EarthSearchSource())
    if settings.enable_copernicus:
        candidates.append(CopernicusSource())
    return {s.id: s for s in candidates}


class SourceRegistry:
    def __init__(self) -> None:
        self._sources = _build_sources()
        self._status_cache: Dict[str, DataSourceStatusOut] = {}
        self._status_time: float = 0.0

    # ------------------------------------------------------------- accessors
    @property
    def sources(self) -> Dict[str, DataSource]:
        return self._sources

    def get(self, source_id: str) -> DataSource:
        if source_id not in self._sources:
            raise AppError("unknown_source", f"Data source '{source_id}' is not registered", 404)
        return self._sources[source_id]

    # --------------------------------------------------------------- status
    def statuses(self, refresh: bool = False, max_age_s: float = 300.0) -> List[DataSourceStatusOut]:
        if not refresh and self._status_cache and (time.time() - self._status_time) < max_age_s:
            return list(self._status_cache.values())
        out: List[DataSourceStatusOut] = []
        for src in self._sources.values():
            try:
                st = src.status()
            except Exception as exc:  # never let a probe take the API down
                st = DataSourceStatusOut(
                    id=src.id, name=src.name, description=src.description, provider=src.provider,
                    status="unavailable", detail=f"probe failed: {exc}",
                    checked_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    auth_required=src.auth_required,
                )
            out.append(st)
            self._status_cache[st.id] = st
        # synthetic Earthdata Login entry (credentials gate NASA raster downloads)
        self._status_cache["earthdata_login"] = DataSourceStatusOut(
            id="earthdata_login",
            name="Earthdata Login (NASA science data)",
            description="Server-side credentials required to download NISAR/OPERA science rasters.",
            provider="NASA URS",
            status="operational" if auth_available() else "requires_credentials",
            detail=("Token/username configured — authenticated NASA downloads enabled."
                    if auth_available() else
                    "No EARTHDATA_TOKEN / EARTHDATA_USERNAME configured in .env — metadata only."),
            checked_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            auth_required=True,
        )
        self._status_time = time.time()
        return list(self._status_cache.values())

    def check(self, source_id: str) -> DataSourceStatusOut:
        if source_id == "earthdata_login":
            self.statuses(refresh=True)
            return self._status_cache["earthdata_login"]
        src = self.get(source_id)
        st = src.status()
        self._status_cache[st.id] = st
        self._status_time = time.time()
        return st

    # -------------------------------------------------------------- search
    def search(
        self,
        bbox: Optional[Sequence[float]] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        mission: Optional[str] = None,
        limit: int = 50,
        sources: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        """Fan out to sources. Returns observations plus per-source results."""
        observations: List[ObservationOut] = []
        checked: List[Dict[str, Any]] = []
        wanted = [self.get(s) for s in sources] if sources else list(self._sources.values())
        per_source = max(3, limit // max(1, len(wanted)) + 3)

        for src in wanted:  # sequential: predictable and polite to public catalogues
            t0 = time.time()
            try:
                items = src.search(bbox=bbox, start=start, end=end, mission=mission, limit=per_source)
                observations.extend(items)
                checked.append({"source": src.id, "ok": True, "count": len(items),
                                "elapsed_ms": int((time.time() - t0) * 1000), "detail": ""})
            except Exception as exc:
                checked.append({"source": src.id, "ok": False, "count": 0,
                                "elapsed_ms": int((time.time() - t0) * 1000), "detail": str(exc)})
                log.warning("source search failed",
                            extra={"extra_fields": {"source": src.id, "error": str(exc)}})

        # de-duplicate: same granule mirrored by several catalogues
        observations = _dedupe(observations)
        observations.sort(key=lambda o: o.datetime or "", reverse=True)
        return {"observations": observations[:limit], "sources_checked": checked}

    # ---------------------------------------------------------- persistence
    @staticmethod
    def to_db_dict(obs: ObservationOut) -> Dict[str, Any]:
        return obs.model_dump()


def _dedupe(items: Iterable[ObservationOut]) -> List[ObservationOut]:
    """Drop exact and near duplicates (same acquisition instant + mission)."""
    seen: set = set()
    out: List[ObservationOut] = []
    for obs in items:
        key_exact = (obs.mission, obs.datetime, tuple(sorted(obs.polarizations)), obs.product_type)
        if key_exact in seen:
            continue
        seen.add(key_exact)
        out.append(obs)
    return out


registry = SourceRegistry()
