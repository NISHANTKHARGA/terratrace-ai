"""Agent metadata and execution contracts on the controlled fixture pair."""
from __future__ import annotations

from app.agents import LATE_AGENTS, build_agents, get_agent
from app.agents.base import AgentCandidate
from app.core.logging import JobLog
from app.orchestrator.engine import Orchestrator
from app.validation import evidence as evidence_mod
from shapely.geometry import box

VALID_STATUSES = {"operational", "experimental", "not_configured", "insufficient_data", "failed"}
VALID_REASON_CODES = {
    "MULTI_DATE_OVERLAP",
    "SUFFICIENT_VALID_PIXELS",
    "INSUFFICIENT_VALID_PIXELS",
    "SINGLE_DATE_ONLY",
    "NO_OVERLAP",
    "UNSUPPORTED_PRODUCT",
    "NEEDS_INSAR",
    "NEEDS_CONTEXT_DATASET",
    "ALWAYS_ELIGIBLE_UNKNOWN_SCREEN",
    "USER_EXCLUDED",
    "EARLIER_FAILURE",
}


def test_registry_has_twelve_agents_in_ordinal_order():
    agents = build_agents()
    assert len(agents) == 12
    assert [a.ordinal for a in agents] == list(range(1, 13))
    assert [a.id for a in agents] == [
        "flood", "wetlands", "forest", "wildfire", "deformation", "glacier",
        "landslide", "agriculture", "urban", "mining", "coastal", "unknown_change",
    ]
    assert LATE_AGENTS == {"unknown_change"}
    for agent in agents:
        assert agent.name and agent.purpose and agent.baseline_method
        assert agent.status in VALID_STATUSES
        assert agent.status_reason, f"{agent.id} must state its honest status"
        assert agent.supported_inputs
        assert agent.model_version
        assert isinstance(agent.datasets, list)


def test_all_agents_obey_the_selection_contract(pair_ctx):
    for agent in build_agents():
        selected, code, reason = agent.select(pair_ctx)
        assert isinstance(selected, bool)
        assert code  # every decision carries a machine-readable reason
        assert reason


def test_routing_records_skip_reasons_for_ineligible_agents(pair_ctx):
    by_id = {a.id: a for a in build_agents()}
    selected, code, reason = by_id["deformation"].select(pair_ctx)
    assert selected is False
    assert code == "NEEDS_INSAR"
    assert reason

    selected, code, reason = by_id["glacier"].select(pair_ctx)
    assert selected is False
    assert code == "NO_CRYOSPHERE_CONTEXT"


def test_single_date_context_is_skipped_with_reason(pair_ctx):
    only = pair_ctx.__class__(
        job_id=pair_ctx.job_id,
        bbox=pair_ctx.bbox,
        region=pair_ctx.region,
        size=pair_ctx.size,
        observations=[pair_ctx.before],
        before=pair_ctx.before,
        after=None,
        quality=pair_ctx.quality,
    )
    for agent in build_agents():
        selected, code, _ = agent.select(only)
        assert selected is False
        assert code == "SINGLE_DATE_ONLY"


def test_flood_agent_finds_the_expanded_lake(pair_ctx):
    agent = get_agent("flood")
    assert agent is not None
    selected, code, _ = agent.select(pair_ctx)
    assert selected is True
    assert code == "MULTI_DATE_OVERLAP"

    result = agent.run(pair_ctx)
    assert result.status == "succeeded"
    assert result.candidates, "the deliberately enlarged lake must produce a candidate"
    top = result.candidates[0]
    assert top.geometry is not None and not top.geometry.is_empty
    assert top.area_km2 > 0
    assert 0.0 <= top.confidence <= 1.0
    assert top.measurements["mean_backscatter_change_db"] < 0
    assert top.explanation
    assert top.supporting


def test_selected_agents_return_typed_results(pair_ctx):
    for agent in build_agents():
        selected, _, _ = agent.select(pair_ctx)
        if not selected:
            continue
        result = agent.run(pair_ctx)
        assert result.agent_id == agent.id
        assert result.status in {"succeeded", "no_candidates", "skipped", "failed"}
        if result.status == "succeeded":
            assert result.candidates, f"{agent.id} claimed success without candidates"
            for cand in result.candidates:
                assert cand.title
                assert cand.geometry is not None and not cand.geometry.is_empty
                assert cand.area_km2 > 0
                assert 0.0 <= cand.confidence <= 1.0
                assert cand.measurements
                assert cand.supporting
                assert cand.explanation


def test_confidence_is_a_heuristic_not_a_probability(pair_ctx):
    agent = get_agent("flood")
    result = agent.run(pair_ctx)
    assert result.candidates
    cand = result.candidates[0]
    assert 0.0 <= cand.confidence <= 1.0
    assert "heuristic" in cand.uncertainty.lower()
    assert "not a" in cand.uncertainty.lower()


def test_publisher_deduplicates_overlapping_candidates(pair_ctx):
    """A second copy of an already-published geometry must not create a finding."""
    for obs in pair_ctx.observations:
        obs.provider_id = obs.observation_id  # publish path expects provider metadata

    geom = box(85.30, 27.62, 85.33, 27.65)
    first = AgentCandidate(
        title="Dedupe probe candidate",
        geometry=geom,
        area_km2=0.012,
        confidence=0.55,
        measurements={"probe": 1},
        supporting=["controlled fixture overlap"],
        explanation="Fixture candidate used only to test de-duplication.",
    )
    agent = get_agent("flood")
    result = agent._result(
        status="succeeded",
        candidates=[first],
        reason_code="MULTI_DATE_OVERLAP",
        reason="fixture",
    )
    ev = evidence_mod.validate(
        agent_id=agent.id,
        agent_name=agent.name,
        method=agent.baseline_method,
        model_version=agent.model_version,
        candidate=first,
        ctx=pair_ctx,
        result=result,
        quality=float(pair_ctx.quality["quality_score"]),
    )
    orch = Orchestrator()
    jl = JobLog("job_dedupe_probe")
    published = orch._publish("job_dedupe_probe", [(result, first, ev)], {}, pair_ctx, jl)
    assert len(published) == 1

    # Re-publishing the same geometry in a later run must be suppressed globally.
    second = AgentCandidate(
        title="Dedupe probe candidate copy",
        geometry=geom,
        area_km2=0.012,
        confidence=0.5,
        measurements={"probe": 1},
        supporting=["controlled fixture overlap"],
        explanation="Fixture duplicate candidate.",
    )
    result2 = agent._result(
        status="succeeded",
        candidates=[second],
        reason_code="MULTI_DATE_OVERLAP",
        reason="fixture",
    )
    ev2 = evidence_mod.validate(
        agent_id=agent.id,
        agent_name=agent.name,
        method=agent.baseline_method,
        model_version=agent.model_version,
        candidate=second,
        ctx=pair_ctx,
        result=result2,
        quality=float(pair_ctx.quality["quality_score"]),
    )
    assert orch._publish("job_dedupe_probe_2", [(result2, second, ev2)], {}, pair_ctx, jl) == []
