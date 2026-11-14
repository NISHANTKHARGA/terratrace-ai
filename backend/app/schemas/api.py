"""Pydantic request/response schemas shared across the API."""
from __future__ import annotations

import time
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

from pydantic import BaseModel, Field, field_validator

MissionId = Literal["NISAR", "SENTINEL-1", "OPERA", "UAVSAR", "OTHER"]
JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
SourceStatusLiteral = Literal[
    "operational", "degraded", "requires_credentials", "unavailable", "unknown"
]
FindingCategory = Literal[
    "FLOOD_INUNDATION",
    "WETLAND_WATER",
    "FOREST_LOSS",
    "WILDFIRE_BURNED",
    "GROUND_DEFORMATION",
    "GLACIER_CRYOSPHERE",
    "LANDSLIDE_SLOPE",
    "AGRICULTURE",
    "URBAN_INFRASTRUCTURE",
    "MINING_DISTURBANCE",
    "COASTAL_SHORELINE",
    "UNCASSIFIED_CHANGE",
]
VerificationStatus = Literal[
    "candidate_detected",
    "under_investigation",
    "corroborated",
    "requires_verification",
    "insufficient_data",
    "rejected_poor_quality",
]
AgentStatusLiteral = Literal[
    "operational", "experimental", "not_configured", "insufficient_data", "failed"
]


class ErrorBody(BaseModel):
    code: str
    message: str
    detail: Optional[Any] = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class PageMeta(BaseModel):
    page: int = 1
    page_size: int = 50
    total: int = 0


class PagedItems(BaseModel):
    items: List[Any]
    page: int = 1
    page_size: int = 50
    total: int = 0


# ---------------------------------------------------------------- observations
class ObservationQuality(BaseModel):
    valid_coverage: Optional[float] = None
    notes: List[str] = Field(default_factory=list)


class ObservationOut(BaseModel):
    id: str
    provider_id: str
    mission: MissionId
    platform: str
    source: str
    product_type: str
    processing_level: str
    datetime: str
    datetime_end: Optional[str] = None
    polarizations: List[str] = Field(default_factory=list)
    orbit_direction: Optional[str] = None
    bbox: Optional[List[float]] = None
    footprint: Optional[Dict[str, Any]] = None
    url: Optional[str] = None
    browse_url: Optional[str] = None
    requires_credentials: bool = False
    size_mb: Optional[float] = None
    quality: ObservationQuality = Field(default_factory=ObservationQuality)
    context: Dict[str, Any] = Field(default_factory=dict)


class ObservationPage(BaseModel):
    items: List[ObservationOut]
    page: int = 1
    page_size: int = 50
    total: int = 0


# ------------------------------------------------------------------- sources
class DataSourceStatusOut(BaseModel):
    id: str
    name: str
    description: str
    provider: str
    status: SourceStatusLiteral
    detail: str
    checked_at: Optional[str] = None
    auth_required: bool = False


class SourceListOut(BaseModel):
    items: List[DataSourceStatusOut]


# ------------------------------------------------------------------- health
class HealthCounts(BaseModel):
    observations: int
    findings: int
    jobs: int
    agents: int


class HealthOut(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    time: str
    database: Literal["ok", "error"]
    sources: List[DataSourceStatusOut]
    counts: HealthCounts


# ------------------------------------------------------------------ analysis
class AnalysisRequest(BaseModel):
    bbox: Optional[List[float]] = None
    polygon: Optional[Dict[str, Any]] = None
    start: str
    end: str
    label: Optional[str] = None
    max_observations: Optional[int] = Field(default=None, ge=1, le=24)
    include_browse: bool = True
    source_preference: Optional[List[str]] = None

    @field_validator("start", "end")
    @classmethod
    def _iso(cls, v: str) -> str:
        if not v or len(v) < 8:
            raise ValueError("expected an ISO8601 date, e.g. 2024-01-01")
        return v


class AgentDecisionOut(BaseModel):
    agent_id: str
    agent_name: str
    selected: bool
    reason: str
    reason_code: str


class OrchestrationStepOut(BaseModel):
    step: int
    name: str
    status: Literal["pending", "running", "succeeded", "failed", "skipped"]
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    detail: Optional[str] = None


class AgentRunRecordOut(BaseModel):
    agent_id: str
    status: Literal["succeeded", "failed", "skipped", "timeout", "no_candidates"]
    duration_ms: int = 0
    model_version: str = ""
    datasets: List[str] = Field(default_factory=list)
    candidates: int = 0
    log: List[str] = Field(default_factory=list)
    error: Optional[str] = None
    reason: Optional[str] = None


class JobMetrics(BaseModel):
    change_pixels: Optional[int] = None
    changed_area_km2: Optional[float] = None
    overlap_ratio: Optional[float] = None
    processing_ms: Optional[int] = None


class AnalysisJobOut(BaseModel):
    id: str
    label: Optional[str] = None
    status: JobStatus
    created_at: str
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    request: Dict[str, Any] = Field(default_factory=dict)
    bbox: List[float] = Field(default_factory=list)
    progress: float = 0.0
    current_stage: Optional[str] = None
    steps: List[OrchestrationStepOut] = Field(default_factory=list)
    observations: List[ObservationOut] = Field(default_factory=list)
    agents_selected: List[AgentDecisionOut] = Field(default_factory=list)
    agent_runs: List[AgentRunRecordOut] = Field(default_factory=list)
    findings: List[str] = Field(default_factory=list)
    error: Optional[str] = None
    logs: List[str] = Field(default_factory=list)
    metrics: Optional[JobMetrics] = None


class JobListOut(BaseModel):
    items: List[AnalysisJobOut]
    page: int = 1
    page_size: int = 50
    total: int = 0


class CancelOut(BaseModel):
    status: JobStatus


# ------------------------------------------------------------------- agents
class DatasetRef(BaseModel):
    id: str
    name: str
    status: Literal["available", "registered", "interface_only", "not_configured"]
    note: str = ""


class EvaluationMetric(BaseModel):
    metric: str
    value: Optional[float] = None
    note: str = ""


class AgentSummaryOut(BaseModel):
    id: str
    name: str
    ordinal: int
    purpose: str
    status: AgentStatusLiteral
    status_reason: str
    model_version: str
    baseline_method: str
    capabilities: List[str] = Field(default_factory=list)
    datasets: List[DatasetRef] = Field(default_factory=list)
    evaluation: List[EvaluationMetric] = Field(default_factory=list)
    last_execution: Optional[Dict[str, Any]] = None
    supported_inputs: List[str] = Field(default_factory=list)


class AgentDetailOut(AgentSummaryOut):
    config: Dict[str, Any] = Field(default_factory=dict)
    output_schema: Dict[str, str] = Field(default_factory=dict)
    processing_logs_last_run: List[str] = Field(default_factory=list)
    known_limitations: List[str] = Field(default_factory=list)


class AgentListOut(BaseModel):
    items: List[AgentSummaryOut]


# ------------------------------------------------------------------ findings
class LocationOut(BaseModel):
    name: Optional[str] = None
    bbox: List[float] = Field(default_factory=list)
    centroid: Tuple[float, float] = (0.0, 0.0)


class SourceRef(BaseModel):
    mission: MissionId
    provider_id: str
    source: str
    product_type: str


class FindingAssets(BaseModel):
    before_png: Optional[str] = None
    after_png: Optional[str] = None
    change_png: Optional[str] = None


class FindingOut(BaseModel):
    id: str
    title: str
    category: FindingCategory
    agent_id: str
    job_id: Optional[str] = None
    location: LocationOut
    geometry: Optional[Dict[str, Any]] = None
    geometry_source: str = "raster_vectorize"
    observation_dates: List[str] = Field(default_factory=list)
    sources: List[SourceRef] = Field(default_factory=list)
    area_km2: float = 0.0
    detection_confidence: float = 0.0
    evidence_completeness: float = 0.0
    data_quality: float = 0.0
    severity: str = "unknown"
    verification_status: VerificationStatus = "candidate_detected"
    first_observed: Optional[str] = None
    method: str = ""
    model_version: str = ""
    created_at: str = ""
    updated_at: str = ""
    assets: FindingAssets = Field(default_factory=FindingAssets)
    explanation: str = ""


class FindingPage(BaseModel):
    items: List[FindingOut]
    page: int = 1
    page_size: int = 50
    total: int = 0


class EvidenceOut(BaseModel):
    summary: str = ""
    measurements: Dict[str, Any] = Field(default_factory=dict)
    supporting: List[str] = Field(default_factory=list)
    conflicting: List[str] = Field(default_factory=list)
    uncertainty: str = ""
    limitations: List[str] = Field(default_factory=list)
    method: Dict[str, Any] = Field(default_factory=dict)
    persistence: Dict[str, Any] = Field(default_factory=dict)
    context_datasets: List[Dict[str, Any]] = Field(default_factory=list)


class FindingDetailOut(FindingOut):
    evidence: Optional[EvidenceOut] = None
    agent: Dict[str, Any] = Field(default_factory=dict)
    job: Optional[Dict[str, Any]] = None
    source_observations: List[ObservationOut] = Field(default_factory=list)


class EvidenceResponse(BaseModel):
    finding_id: str
    evidence: EvidenceOut


# --------------------------------------------------------------- map/history
class MapLayerDef(BaseModel):
    id: str
    name: str
    type: Literal["vector", "raster", "geojson_url"]
    default_on: bool = True
    endpoint: Optional[str] = None


class MapLayersOut(BaseModel):
    layers: List[MapLayerDef]
    findings_geojson: Dict[str, Any]
    observations_geojson: Dict[str, Any]
    change_polygons_geojson: Dict[str, Any] = Field(
        default_factory=lambda: {"type": "FeatureCollection", "features": []}
    )
    analysis_regions_geojson: Dict[str, Any] = Field(
        default_factory=lambda: {"type": "FeatureCollection", "features": []}
    )
    basemap_attribution: str = "© OpenStreetMap contributors © CARTO"


class HistoryEntry(BaseModel):
    kind: Literal["analysis", "discovery"]
    id: str
    label: Optional[str] = None
    status: str
    created_at: str
    findings_count: int = 0
    bbox: List[float] = Field(default_factory=list)


class HistoryPage(BaseModel):
    items: List[HistoryEntry]
    page: int = 1
    page_size: int = 50
    total: int = 0


# ------------------------------------------------------------ datasets/models
class DatasetInfoOut(BaseModel):
    id: str
    name: str
    agent_ids: List[str] = Field(default_factory=list)
    status: Literal["available", "registered", "interface_only", "not_configured"]
    access: str = ""
    url: Optional[str] = None
    note: str = ""


class DatasetListOut(BaseModel):
    items: List[DatasetInfoOut]


class ModelInfoOut(BaseModel):
    id: str
    agent_id: str
    name: str
    kind: str
    version: str
    status: str
    dataset_ids: List[str] = Field(default_factory=list)
    metrics: List[Dict[str, Any]] = Field(default_factory=list)
    checkpoint_path: Optional[str] = None
    trained_at: Optional[str] = None
    sample_count: Optional[int] = None
    limitations: List[str] = Field(default_factory=list)


class ModelListOut(BaseModel):
    items: List[ModelInfoOut]


class TrainingRunOut(BaseModel):
    id: str
    agent_id: str
    model_id: str
    status: str
    started_at: str
    ended_at: Optional[str] = None
    dataset_ids: List[str] = Field(default_factory=list)
    config: Dict[str, Any] = Field(default_factory=dict)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    notes: str = ""


class TrainingRunListOut(BaseModel):
    items: List[TrainingRunOut]


class DiscoveryRequest(BaseModel):
    bbox: Optional[List[float]] = None
    start: Optional[str] = None
    end: Optional[str] = None
    limit: int = Field(default=25, ge=1, le=500)
    mission: Optional[str] = None


class DiscoveryOut(BaseModel):
    job_id: str
    observations: List[ObservationOut]
    sources_checked: List[Dict[str, Any]] = Field(default_factory=list)
