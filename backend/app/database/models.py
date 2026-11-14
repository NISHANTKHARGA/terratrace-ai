"""SQLAlchemy models.

JSON columns keep the schema flexible while remaining portable across SQLite
and PostgreSQL (use `sqlalchemy.JSON` / `JSONB` via type adaptation).
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Dict, Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class Base(DeclarativeBase):
    type_annotation_map = {Dict[str, Any]: JSON, list: JSON}


class Observation(Base):
    __tablename__ = "observations"
    __table_args__ = (UniqueConstraint("source", "provider_id", name="uq_obs_source_provider"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider_id: Mapped[str] = mapped_column(String(256), index=True)
    mission: Mapped[str] = mapped_column(String(32), index=True)  # NISAR|SENTINEL-1|OPERA|OTHER
    platform: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(64), index=True)
    product_type: Mapped[str] = mapped_column(String(64))
    processing_level: Mapped[str] = mapped_column(String(16))
    datetime: Mapped[str] = mapped_column(String(32), index=True)
    datetime_end: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    polarizations: Mapped[list] = mapped_column(JSON, default=list)
    orbit_direction: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    bbox: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    footprint: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    browse_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    requires_credentials: Mapped[bool] = mapped_column(Boolean, default=False)
    size_mb: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    quality: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    context: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)  # provider extras
    first_seen: Mapped[str] = mapped_column(String(32), default=now_iso)

    @property
    def readable(self) -> bool:
        return not self.requires_credentials


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    status: Mapped[str] = mapped_column(String(16), index=True, default="queued")
    request: Mapped[dict] = mapped_column(JSON, default=dict)
    bbox: Mapped[list] = mapped_column(JSON, default=list)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    current_stage: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    steps: Mapped[list] = mapped_column(JSON, default=list)
    observations: Mapped[list] = mapped_column(JSON, default=list)
    agents_selected: Mapped[list] = mapped_column(JSON, default=list)
    agent_runs: Mapped[list] = mapped_column(JSON, default=list)
    findings: Mapped[list] = mapped_column(JSON, default=list)
    logs: Mapped[list] = mapped_column(JSON, default=list)
    metrics: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[str] = mapped_column(String(32), default=now_iso, index=True)
    started_at: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    ended_at: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)


class Finding(Base):
    __tablename__ = "findings"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dedupe_key: Mapped[Optional[str]] = mapped_column(String(128), unique=True, nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(256))
    category: Mapped[str] = mapped_column(String(48), index=True)
    agent_id: Mapped[str] = mapped_column(String(48), index=True)
    job_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    location_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    bbox: Mapped[list] = mapped_column(JSON, default=list)
    centroid: Mapped[list] = mapped_column(JSON, default=list)
    geometry: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    geometry_source: Mapped[str] = mapped_column(String(32), default="raster_vectorize")
    observation_dates: Mapped[list] = mapped_column(JSON, default=list)
    sources: Mapped[list] = mapped_column(JSON, default=list)
    area_km2: Mapped[float] = mapped_column(Float, default=0.0)
    detection_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    evidence_completeness: Mapped[float] = mapped_column(Float, default=0.0)
    data_quality: Mapped[float] = mapped_column(Float, default=0.0)
    severity: Mapped[str] = mapped_column(String(16), default="unknown")
    verification_status: Mapped[str] = mapped_column(String(32), default="candidate_detected")
    first_observed: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    method: Mapped[str] = mapped_column(String(128), default="")
    model_version: Mapped[str] = mapped_column(String(64), default="")
    explanation: Mapped[str] = mapped_column(Text, default="")
    assets: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(String(32), default=now_iso, index=True)
    updated_at: Mapped[str] = mapped_column(String(32), default=now_iso)

    evidence: Mapped[Optional["Evidence"]] = relationship(
        back_populates="finding", uselist=False, cascade="all, delete-orphan"
    )


class Evidence(Base):
    __tablename__ = "evidence"

    finding_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("findings.id", ondelete="CASCADE"), primary_key=True
    )
    summary: Mapped[str] = mapped_column(Text, default="")
    measurements: Mapped[dict] = mapped_column(JSON, default=dict)
    supporting: Mapped[list] = mapped_column(JSON, default=list)
    conflicting: Mapped[list] = mapped_column(JSON, default=list)
    uncertainty: Mapped[str] = mapped_column(Text, default="")
    limitations: Mapped[list] = mapped_column(JSON, default=list)
    method: Mapped[dict] = mapped_column(JSON, default=dict)
    persistence: Mapped[dict] = mapped_column(JSON, default=dict)
    context_datasets: Mapped[list] = mapped_column(JSON, default=list)

    finding: Mapped["Finding"] = relationship(back_populates="evidence")


class DatasetRecord(Base):
    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    agent_ids: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="registered")
    access: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")


class AgentRecord(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(128))
    purpose: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="not_configured")
    status_reason: Mapped[str] = mapped_column(Text, default="")
    model_version: Mapped[str] = mapped_column(String(64), default="")
    baseline_method: Mapped[str] = mapped_column(String(256), default="")
    capabilities: Mapped[list] = mapped_column(JSON, default=list)
    supported_inputs: Mapped[list] = mapped_column(JSON, default=list)
    datasets: Mapped[list] = mapped_column(JSON, default=list)
    evaluation: Mapped[list] = mapped_column(JSON, default=list)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    output_schema: Mapped[dict] = mapped_column(JSON, default=dict)
    known_limitations: Mapped[list] = mapped_column(JSON, default=list)
    last_execution: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    last_logs: Mapped[list] = mapped_column(JSON, default=list)
    updated_at: Mapped[str] = mapped_column(String(32), default=now_iso)


class ModelVersion(Base):
    __tablename__ = "models"

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(48), index=True)
    name: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(32), default="baseline_algorithm")
    version: Mapped[str] = mapped_column(String(48))
    status: Mapped[str] = mapped_column(String(24), default="active")
    dataset_ids: Mapped[list] = mapped_column(JSON, default=list)
    metrics: Mapped[list] = mapped_column(JSON, default=list)
    checkpoint_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    trained_at: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    sample_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    limitations: Mapped[list] = mapped_column(JSON, default=list)
    config: Mapped[dict] = mapped_column(JSON, default=dict)


class TrainingRun(Base):
    __tablename__ = "training_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(48), index=True)
    model_id: Mapped[str] = mapped_column(String(96))
    status: Mapped[str] = mapped_column(String(24), default="registered_only")
    started_at: Mapped[str] = mapped_column(String(32), default=now_iso)
    ended_at: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    dataset_ids: Mapped[list] = mapped_column(JSON, default=list)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    notes: Mapped[str] = mapped_column(Text, default="")


class SourceStatusRecord(Base):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    provider: Mapped[str] = mapped_column(String(96))
    status: Mapped[str] = mapped_column(String(32), default="unknown")
    detail: Mapped[str] = mapped_column(Text, default="")
    auth_required: Mapped[bool] = mapped_column(Boolean, default=False)
    checked_at: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)


class DiscoveryRun(Base):
    """A metadata-only discovery sweep (no raster downloads)."""

    __tablename__ = "discovery_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    bbox: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    start: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    end: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    mission: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    limit: Mapped[int] = mapped_column(Integer, default=25)
    observations_count: Mapped[int] = mapped_column(Integer, default=0)
    sources_checked: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(24), default="completed")
    created_at: Mapped[str] = mapped_column(String(32), default=now_iso, index=True)


class ContextRecord(Base):
    """Key/value store for runtime state (source probe cache, counters...)."""

    __tablename__ = "context"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[str] = mapped_column(String(32), default=now_iso)
