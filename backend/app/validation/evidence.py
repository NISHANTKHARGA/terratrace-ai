"""Shared evidence validation for every candidate finding.

Keeps five different concepts separate and never converts a heuristic score
into a probability:

1. detection_confidence    – heuristic signal ranking from the agent
2. evidence_completeness   – how much of the expected evidence is present
3. data_quality            – input raster quality (from preprocessing)
4. severity                – scale/impact class
5. verification_status     – workflow state of the claim
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from app.agents.base import AgentCandidate, AgentContext, AgentResult
from app.core.geo import area_km2, overlap_ratio

STATUS_ORDER = [
    "candidate_detected", "under_investigation", "requires_verification",
    "corroborated", "insufficient_data", "rejected_poor_quality",
]

CORROBORATING_HINTS = {
    "opera_dswx_s1": "OPERA DSWx-S1 dynamic surface water product covers the same dates/area",
    "sentinel2_l2a": "A Sentinel-2 optical scene is available for independent visual check",
    "copernicus_dem_glo30": "Copernicus DEM confirms the terrain context",
}


@dataclass
class ValidatedEvidence:
    summary: str
    measurements: Dict[str, Any]
    supporting: List[str]
    conflicting: List[str]
    uncertainty: str
    limitations: List[str]
    method: Dict[str, Any]
    persistence: Dict[str, Any]
    context_datasets: List[Dict[str, Any]]
    detection_confidence: float
    evidence_completeness: float
    data_quality: float
    severity: str
    verification_status: str
    first_observed: Optional[str]


def _parse(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        try:
            return datetime.fromisoformat(str(s)[:19])
        except Exception:
            return None


def compute_persistence(dates: Sequence[str]) -> Dict[str, Any]:
    ds = [d for d in dates if d]
    if len(ds) < 2:
        return {"dates_supporting": list(ds), "days_between": None, "persistent": False}
    t0, t1 = _parse(ds[0]), _parse(ds[-1])
    days = round(abs((t1 - t0).total_seconds()) / 86400.0, 2) if t0 and t1 else None
    return {"dates_supporting": list(ds), "days_between": days,
            "persistent": bool(days and days >= 1.0)}


def evidence_completeness(
    *,
    candidate: AgentCandidate,
    ctx: AgentContext,
    result: AgentResult,
    persistence: Dict[str, Any],
) -> float:
    """0..1 — how much of the *expected* evidence is actually present."""
    score = 0.0
    # two dates, well separated
    if persistence.get("persistent"):
        score += 0.25
    elif len([d for d in (candidate.first_observed,) if d]):
        score += 0.10
    # quantitative measurements present
    if candidate.measurements:
        score += 0.20
    # agent-specific dataset corroboration available
    available = [d for d in ctx.datasets.describe() if d["status"] == "available"]
    score += min(0.25, 0.12 * len(available))
    # explicit supporting statements (>=2)
    score += min(0.15, 0.05 * len(candidate.supporting))
    # context products actually discovered for this run
    if ctx.observations and len(ctx.observations) >= 2:
        score += 0.10
    # conflicting evidence documented (honest reporting counts as completeness)
    score += min(0.10, 0.05 * len(candidate.conflicting))
    return round(min(1.0, score), 3)


def verification_status_for(
    *,
    agent_id: str,
    quality: float,
    candidate: AgentCandidate,
    completeness: float,
) -> str:
    if quality < 0.25:
        return "rejected_poor_quality"
    if completeness < 0.35:
        return "insufficient_data"
    hard_required = {"wildfire", "forest", "urban", "mining", "agriculture", "landslide"}
    corroborating = any(d["status"] == "available" for d in [])  # placeholder, set by caller
    if agent_id in hard_required or "unverified" in " ".join(candidate.tags):
        return "requires_verification"
    if quality > 0.6 and completeness > 0.6:
        return "under_investigation"
    return "candidate_detected"


def validate(
    *,
    agent_id: str,
    agent_name: str,
    method: str,
    model_version: str,
    candidate: AgentCandidate,
    ctx: AgentContext,
    result: AgentResult,
    quality: float,
    corroborated: bool = False,
) -> ValidatedEvidence:
    persistence = compute_persistence([d for d in ctx.dates if d])
    completeness = evidence_completeness(
        candidate=candidate, ctx=ctx, result=result, persistence=persistence
    )

    supporting = list(candidate.supporting)
    conflicting = list(candidate.conflicting)
    limitations = [
        f"Produced by {agent_name} using {method} ({model_version}).",
        "Detection confidence is a heuristic ranking score between 0 and 1; it is not a "
        "calibrated probability that the interpretation is correct.",
        "Evidence completeness, data quality and severity are reported separately and must "
        "not be combined into a single 'accuracy' number.",
    ]

    # context dataset status (honest: available vs interface-only vs not configured)
    context_datasets = ctx.datasets.describe()
    for d in context_datasets:
        if d["status"] == "available":
            supporting.append(f"Context dataset available: {d['note']}")
        elif d["status"] == "not_configured":
            limitations.append(f"{d['id']}: {d['note']}")

    # multi-date corroboration
    n_dates = len({d for d in ctx.dates if d})
    if n_dates >= 3:
        supporting.append(
            f"{n_dates} observations are attached to this run, so the change can be checked "
            "for persistence across more than one pair."
        )
    elif n_dates == 2:
        supporting.append("Two observations support a single before/after comparison only — "
                          "persistence beyond that pair is untested.")
        conflicting.append("Only one before/after pair supports this finding.")
    else:
        conflicting.append("Fewer than two dated observations support this finding.")

    # quality-driven conflict
    q = ctx.quality
    if q.get("warnings"):
        conflicting.extend(q["warnings"])
    if q.get("errors"):
        conflicting.extend(q["errors"])
    if (q.get("common_fraction") or 0) < 0.6:
        conflicting.append(
            f"Co-valid coverage is {q.get('common_fraction', 0):.0%}: parts of the region were "
            "not observed by both acquisitions."
        )

    # duplicate/overlap awareness
    if ctx.claimed_geometries and candidate.geometry is not None:
        best = max((overlap_ratio(candidate.geometry, g) for g in ctx.claimed_geometries), default=0.0)
        if best > 0.3:
            conflicting.append(
                f"Overlaps an already-published finding by {best:.0%} — treat as the same "
                "physical change seen by another agent."
            )

    status = verification_status_for(
        agent_id=agent_id, quality=quality, candidate=candidate, completeness=completeness
    )
    if corroborated:
        status = "corroborated"
    if q.get("errors"):
        status = "rejected_poor_quality"

    summary = (
        f"{agent_name} reported '{candidate.title}' from {len(ctx.observations)} observation(s) "
        f"({', '.join([d[:10] for d in ctx.dates[:4]])}). "
        f"{len(supporting)} supporting statement(s), {len(conflicting)} caveat(s); "
        f"evidence completeness {completeness:.2f}, data quality {quality:.2f}."
    )
    uncertainty = candidate.uncertainty or (
        "No agent-specific uncertainty statement was recorded."
    )

    return ValidatedEvidence(
        summary=summary,
        measurements={
            **candidate.measurements,
            "detection_confidence_heuristic": candidate.confidence,
            "evidence_completeness": completeness,
            "data_quality": quality,
            "days_between_observations": persistence.get("days_between"),
            "n_observations": n_dates,
        },
        supporting=supporting,
        conflicting=conflicting,
        uncertainty=uncertainty,
        limitations=limitations,
        method={"name": method, "version": model_version, "agent": agent_id},
        persistence=persistence,
        context_datasets=context_datasets,
        detection_confidence=round(float(candidate.confidence), 3),
        evidence_completeness=completeness,
        data_quality=round(float(quality), 3),
        severity=candidate.severity if candidate.severity in ("low", "moderate", "high") else "unknown",
        verification_status=status,  # type: ignore[arg-type]
        first_observed=candidate.first_observed,
    )
