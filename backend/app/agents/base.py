"""Agent contracts: typed context, results, and the abstract base agent."""
from __future__ import annotations

import abc
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from shapely.geometry import Polygon

from app.core.geo import area_km2, centroid_lonlat, to_geojson
from app.preprocessing.io import RasterScene

LOG = Callable[..., None]


@dataclass
class ContextDatasets:
    """Optional contextual datasets resolved for this run (may be absent)."""

    dem_url: Optional[str] = None
    dem_array: Optional[Any] = None
    dem_transform: Optional[Any] = None
    sentinel2: Optional[Any] = None
    dswx_product_found: bool = False
    fired_products: List[str] = field(default_factory=list)

    def describe(self) -> List[Dict[str, Any]]:
        return [
            {"id": "copernicus_dem_glo30", "note": "Copernicus DEM 30 m for slope context",
             "status": "available" if self.dem_array is not None else "unavailable"},
            {"id": "sentinel2_l2a", "note": "Optical scene for corroboration",
             "status": "available" if self.sentinel2 is not None else "unavailable"},
            {"id": "opera_dswx_s1", "note": "OPERA dynamic surface water product",
             "status": "available" if self.dswx_product_found else "unavailable"},
            {"id": "nasa_firms", "note": "Active fire detections (API key required)",
             "status": "not_configured"},
        ]


@dataclass
class AgentContext:
    """Everything a specialist agent may use for one analysis run."""

    job_id: str
    bbox: Tuple[float, float, float, float]
    region: Any                      # shapely (Multi)Polygon in EPSG:4326
    size: int
    observations: List[Any] = field(default_factory=list)
    before: Optional[RasterScene] = None
    after: Optional[RasterScene] = None
    quality: Dict[str, Any] = field(default_factory=dict)
    change: Optional[Any] = None     # ChangeResult (set by preprocessing stage)
    water_before: Optional[Any] = None
    water_after: Optional[Any] = None
    datasets: ContextDatasets = field(default_factory=ContextDatasets)
    claimed_geometries: List[Any] = field(default_factory=list)
    config: Dict[str, Any] = field(default_factory=dict)
    log: LOG = lambda *a, **k: None
    model_versions: Dict[str, str] = field(default_factory=dict)

    @property
    def dates(self) -> List[str]:
        return [o.datetime for o in self.observations if o.datetime]

    @property
    def has_pair(self) -> bool:
        return self.before is not None and self.after is not None

    @property
    def days_between(self) -> Optional[float]:
        return self.quality.get("days_between")

    @property
    def valid(self) -> Optional[Any]:
        return self.quality.get("common_mask")

    def secondary_pols(self) -> List[str]:
        if self.before is None:
            return []
        return list(self.before.arrays.keys())


@dataclass
class AgentCandidate:
    title: str
    geometry: Any
    area_km2: float
    confidence: float                 # heuristic detection score, 0..1, NOT a probability
    severity: str = "moderate"
    measurements: Dict[str, Any] = field(default_factory=dict)
    supporting: List[str] = field(default_factory=list)
    conflicting: List[str] = field(default_factory=list)
    uncertainty: str = ""
    explanation: str = ""
    first_observed: Optional[str] = None
    tags: List[str] = field(default_factory=list)

    @property
    def geojson(self) -> Optional[Dict[str, Any]]:
        if self.geometry is None or getattr(self.geometry, "is_empty", True):
            return None
        return to_geojson(self.geometry)

    @property
    def centroid(self) -> Tuple[float, float]:
        if self.geometry is None or getattr(self.geometry, "is_empty", True):
            return (0.0, 0.0)
        return centroid_lonlat(self.geometry)


@dataclass
class AgentResult:
    agent_id: str
    status: str                       # succeeded | skipped | failed | no_candidates
    reason_code: str = ""
    reason: str = ""
    candidates: List[AgentCandidate] = field(default_factory=list)
    model_version: str = ""
    datasets: List[str] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    logs: List[str] = field(default_factory=list)
    error: Optional[str] = None
    duration_ms: int = 0


class BaseAgent(abc.ABC):
    """Specialist analysis agent.

    Each agent owns its configuration, datasets, baseline algorithm, output
    schema, evaluation records and limitations, and must declare *when* it can
    usefully run (`select`) so the orchestrator can skip it with a reason.
    """

    id: str = "base"
    name: str = "Base"
    ordinal: int = 0
    category: str = "UNCASSIFIED_CHANGE"
    purpose: str = ""
    status: str = "experimental"
    status_reason: str = ""
    baseline_method: str = ""
    capabilities: List[str] = []
    supported_inputs: List[str] = []
    datasets: List[Dict[str, Any]] = []
    evaluation: List[Dict[str, Any]] = []
    config: Dict[str, Any] = {}
    output_schema: Dict[str, str] = {}
    known_limitations: List[str] = []
    model_version: str = "baseline-1.0"

    # ----------------------------------------------------------- selection
    def select(self, ctx: AgentContext) -> Tuple[bool, str, str]:
        """Return (selected, reason_code, human explanation)."""
        if not ctx.has_pair:
            return False, "SINGLE_DATE_ONLY", (
                "Fewer than two comparable observations in the requested period; "
                "multi-temporal comparison is not possible."
            )
        if ctx.quality.get("errors"):
            return False, "INSUFFICIENT_VALID_PIXELS", ctx.quality["errors"][0]
        if ctx.quality.get("quality_score", 0) < 0.3:
            return False, "INSUFFICIENT_VALID_PIXELS", (
                f"Co-valid coverage {ctx.quality.get('common_fraction', 0):.0%} is below the "
                "0.30 threshold for reliable comparison."
            )
        return self._select_specific(ctx)

    def _select_specific(self, ctx: AgentContext) -> Tuple[bool, str, str]:
        return True, "MULTI_DATE_OVERLAP", (
            "Two or more compatible observations overlap this region with sufficient "
            "co-valid pixels for this agent's baseline method."
        )

    # --------------------------------------------------------------- run
    @abc.abstractmethod
    def run(self, ctx: AgentContext) -> AgentResult:
        raise NotImplementedError

    def _result(self, **kwargs) -> AgentResult:
        return AgentResult(agent_id=self.id, model_version=self.model_version,
                           datasets=[d["id"] for d in self.datasets], **kwargs)

    def _fail(self, exc: Exception, logs: List[str], started: float) -> AgentResult:
        return self._result(
            status="failed", error=str(exc), logs=logs,
            reason_code="AGENT_ERROR", reason=f"{type(exc).__name__}: {exc}",
            duration_ms=int((time.time() - started) * 1000),
        )

    # ------------------------------------------------------- introspection
    def summary(self, last_execution: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "ordinal": self.ordinal, "purpose": self.purpose,
            "status": self.status, "status_reason": self.status_reason,
            "model_version": self.model_version, "baseline_method": self.baseline_method,
            "capabilities": list(self.capabilities), "datasets": list(self.datasets),
            "evaluation": list(self.evaluation), "last_execution": last_execution,
            "supported_inputs": list(self.supported_inputs),
        }

    def detail(self, last_execution: Optional[Dict[str, Any]] = None,
               logs: Optional[List[str]] = None) -> Dict[str, Any]:
        return {
            **self.summary(last_execution),
            "config": dict(self.config),
            "output_schema": dict(self.output_schema),
            "processing_logs_last_run": logs or [],
            "known_limitations": list(self.known_limitations),
        }


def unclaimed(geom: Any, claimed: Sequence[Any], min_overlap: float = 0.5) -> bool:
    """True when a candidate does not substantially overlap an already claimed region."""
    if geom is None or getattr(geom, "is_empty", True) or not claimed:
        return True
    best = 0.0
    for c in claimed:
        try:
            if c.is_empty:
                continue
            inter = geom.intersection(c).area
            denom = min(geom.area, c.area) or 1e-12
            best = max(best, inter / denom)
        except Exception:
            continue
    return best < min_overlap
