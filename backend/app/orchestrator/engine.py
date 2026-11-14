"""Central multi-agent orchestrator.

Pipeline (Part 3 of the specification):

    1. Global Data Scout      – discover available observations
    2. SAR Processing Service – validate + prepare compatible rasters
    3. Change Detection Engine – identify candidate change
    4. Central Orchestrator   – decide which agents are relevant and why
    5. Specialist Agents      – execute (parallel, with retries & timeouts)
    6. Evidence Validation    – cross-check every candidate
    7. Finding Publisher      – de-duplicate and store publishable findings

Every activated *and* skipped agent is recorded with a machine-readable reason.
"""
from __future__ import annotations

import hashlib
import json
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeout
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from shapely.geometry import box

from app.agents import LATE_AGENTS, build_agents
from app.agents.base import AgentCandidate, AgentContext, AgentResult, BaseAgent, unclaimed
from app.change_detection.log_ratio import detect_log_ratio
from app.change_detection.segmentation import segment_water
from app.config import settings
from app.core.errors import AppError, UnsupportedAnalysisError
from app.core.geo import area_km2, bbox_to_polygon, geom_from_geojson, overlap_ratio, validate_bbox
from app.core.logging import JobLog, get_logger
from app.database.models import AgentRecord, Evidence, Finding, Job, Observation, now_iso, new_id
from app.database.session import SessionLocal, session_scope
from app.data_sources.registry import registry
from app.preprocessing.io import RasterScene, read_scene
from app.preprocessing.quality import assess_pair
from app.preprocessing.raster import (
    mask_to_polygons, render_backscatter_png, render_change_png,
)
from app.schemas.api import AnalysisRequest
from app.validation import evidence as evidence_mod
from app.workers.jobs import runner

log = get_logger("orchestrator.engine")

STEPS = [
    ("global_data_scout", "Global Data Scout"),
    ("sar_processing", "SAR Processing Service"),
    ("change_detection", "Change Detection Engine"),
    ("agent_routing", "Central Orchestrator · Agent Selection"),
    ("agent_execution", "Specialist Agent Execution"),
    ("evidence_validation", "Evidence Validation Service"),
    ("finding_publisher", "Finding Publisher"),
]

READABLE_SOURCES = ("planetary_computer", "earth_search", "nasa_cmr", "copernicus_dataspace")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _init_steps() -> List[Dict[str, Any]]:
    return [{"step": i + 1, "name": key, "label": label, "status": "pending"}
            for i, (key, label) in enumerate(STEPS)]


class Orchestrator:
    """Executes one analysis job end to end."""

    # ------------------------------------------------------------ step helpers
    def _update(self, job_id: str, **fields: Any) -> None:
        with session_scope() as db:
            job = db.get(Job, job_id)
            if job is None:
                return
            for k, v in fields.items():
                setattr(job, k, v)

    def _flush(self, job_id: str, jl: "JobLog") -> None:
        """Persist the live log buffer so the API can stream it."""
        with session_scope() as db:
            job = db.get(Job, job_id)
            if job is not None:
                job.logs = jl.lines()

    def _step(self, job_id: str, index: int, status: str, detail: Optional[str] = None,
              job: Optional[Job] = None) -> None:
        def apply(steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            s = list(steps)
            while len(s) < len(STEPS):
                s.append({"step": len(s) + 1, "name": STEPS[len(s)][0],
                          "label": STEPS[len(s)][1], "status": "pending"})
            entry = dict(s[index])
            entry["status"] = status
            if status == "running":
                entry["started_at"] = utc_now()
            if status in ("succeeded", "failed", "skipped"):
                entry["ended_at"] = utc_now()
            if detail is not None:
                entry["detail"] = detail
            s[index] = entry
            return s

        if job is not None:
            job.steps = apply(job.steps or _init_steps())
        else:
            with session_scope() as db:
                j = db.get(Job, job_id)
                if j is not None:
                    j.steps = apply(j.steps or _init_steps())

    # ------------------------------------------------------------------ main
    def run(self, job_id: str) -> None:
        jl = JobLog(job_id)
        t_start = time.time()
        last_flush = {"t": 0.0}

        def _live_flush() -> None:
            now = time.time()
            if now - last_flush["t"] >= 0.5:
                last_flush["t"] = now
                self._flush(job_id, jl)

        jl.on_add = _live_flush
        try:
            self._run_inner(job_id, jl, t_start)
        except UnsupportedAnalysisError as exc:
            self._finish(job_id, "failed", str(exc), jl, t_start)
            jl.add(f"UNSUPPORTED: {exc}", level="ERROR")
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("job failed", extra={"extra_fields": {"job": job_id}})
            self._finish(job_id, "failed", f"{type(exc).__name__}: {exc}\n"
                                           f"{traceback.format_exc()[-1200:]}", jl, t_start)

    def _finish(self, job_id: str, status: str, error: Optional[str],
                jl: JobLog, t_start: float, metrics: Optional[Dict[str, Any]] = None) -> None:
        with session_scope() as db:
            job = db.get(Job, job_id)
            if job is None:
                return
            job.status = status
            job.ended_at = utc_now()
            job.error = error
            job.progress = 1.0 if status in ("succeeded", "failed", "cancelled") else job.progress
            job.current_stage = None
            job.logs = jl.lines()
            if metrics:
                job.metrics = {**(job.metrics or {}), **metrics}
        jl.add(f"Job {status} in {time.time() - t_start:.1f}s"
               + (f": {error}" if error else ""))

    # -------------------------------------------------------------- pipeline
    def _run_inner(self, job_id: str, jl: JobLog, t_start: float) -> None:
        with session_scope() as db:
            job = db.get(Job, job_id)
            if job is None:
                raise AppError("not_found", f"job {job_id} not found", 404)
            if job.cancel_requested:
                self._finish(job_id, "cancelled", None, jl, t_start)
                return
            job.status = "running"
            job.started_at = utc_now()
            job.steps = _init_steps()
            job.progress = 0.02
            job.current_stage = "global_data_scout"
            job.logs = jl.lines()
            req = AnalysisRequest(**job.request)
            bbox = validate_bbox(job.bbox)
            label = job.label

        jl.add(f"Analysis started for bbox={bbox} {req.start}..{req.end} ({label or 'no label'})")
        metrics: Dict[str, Any] = {"processing_ms": None}

        # ------------------------------------------------ 1. Global Data Scout
        self._step(job_id, 0, "running")
        jl.add("Discovering observations across configured sources …")
        search = registry.search(
            bbox=bbox, start=req.start, end=req.end,
            limit=req.max_observations or settings.max_observations,
            sources=req.source_preference or None,
        )
        observations = search["observations"]
        for c in search["sources_checked"]:
            jl.add(f"source {c['source']}: {'OK' if c['ok'] else 'FAILED'} "
                   f"({c['count']} obs, {c['elapsed_ms']} ms)"
                   + (f" — {c['detail']}" if c["detail"] and not c["ok"] else ""))
        if not observations:
            self._step(job_id, 0, "failed", "no observations found")
            self._finish(job_id, "failed",
                         f"No satellite observations were found for {bbox} between "
                         f"{req.start} and {req.end}. TerraTrace does not fabricate data — "
                         "widen the period, move the region, or enable another source.", jl, t_start)
            return

        self._store_observations(observations)
        with session_scope() as db:
            job = db.get(Job, job_id)
            job.observations = [o.model_dump() for o in observations]
            job.progress = 0.12
        jl.add(f"Found {len(observations)} observation(s): "
               + "; ".join(f"{o.mission}/{o.product_type} {o.datetime[:19]}" for o in observations[:6]))
        self._step(job_id, 0, "succeeded",
                   f"{len(observations)} observation(s) from "
                   f"{len({o.source for o in observations})} source(s)")
        if runner.should_cancel(job_id):
            self._finish(job_id, "cancelled", None, jl, t_start)
            return

        # --------------------------------------------- 2. SAR Processing
        self._step(job_id, 1, "running")
        with session_scope() as db:
            db.get(Job, job_id).current_stage = "sar_processing"
        jl.add("Selecting and reading compatible rasters …")
        before, after, used_obs, read_notes = self._load_pair(observations, bbox, jl)
        for n in read_notes:
            jl.add(n)

        quality = assess_pair(before, after)
        for w in quality["warnings"]:
            jl.add(f"quality warning: {w}", level="WARNING")
        for e in quality["errors"]:
            jl.add(f"quality error: {e}", level="ERROR")
        jl.add(f"quality score {quality['quality_score']:.2f} · "
               f"co-valid {quality['common_fraction']:.0%} · "
               f"Δt {quality['days_between']} d · offset {quality['median_shift_db']:+.2f} dB")
        if quality["errors"] or quality["quality_score"] < 0.3:
            self._step(job_id, 1, "failed", "raster compatibility check failed")
            self._finish(job_id, "failed",
                         "The available observations cannot support a reliable comparison: "
                         + " ".join(quality["errors"] or quality["warnings"]), jl, t_start,
                         metrics={"overlap_ratio": quality["common_fraction"]})
            return
        with session_scope() as db:
            job = db.get(Job, job_id)
            job.observations = [o.model_dump() for o in used_obs] + [
                o.model_dump() for o in observations if o.id not in {u.id for u in used_obs}]
            job.progress = 0.28
        self._step(job_id, 1, "succeeded",
                   f"read {before.mission} pair, {quality['common_fraction']:.0%} co-valid")
        if runner.should_cancel(job_id):
            self._finish(job_id, "cancelled", None, jl, t_start)
            return

        # ------------------------------------------- 3. Change Detection
        self._step(job_id, 2, "running")
        with session_scope() as db:
            db.get(Job, job_id).current_stage = "change_detection"
        region = geom_from_geojson(bbox_to_polygon(bbox))
        valid = quality["common_mask"]
        b_db, a_db = before.db(before.primary_pol), after.db(after.primary_pol)
        change = detect_log_ratio(b_db, a_db, valid)
        for n in change.notes:
            jl.add(f"change detection: {n}")
        jl.add(f"changed pixels {change.changed_pixels} "
               f"({change.stats.get('changed_fraction', 0):.1%}), "
               f"threshold ±{change.threshold_db:.2f} dB")

        water_kw = dict(hard_ceiling_db=-9.0, hard_floor_db=-34.0, min_component_px=30)
        water_after = segment_water(a_db, valid, **water_kw)
        water_before = segment_water(b_db, valid, **water_kw)
        jl.add(f"water segmentation after: {'used' if water_after.used else 'no water class'} "
               f"(thr {water_after.threshold_db:.1f} dB); before: "
               f"{'used' if water_before.used else 'no water class'}")

        changed_area = 0.0
        if change.mask.any():
            geojson, geom, changed_area = mask_to_polygons(change.mask, before.transform,
                                                           min_area_km2=0.0)
        metrics.update({
            "change_pixels": change.changed_pixels,
            "changed_area_km2": round(changed_area, 4),
            "overlap_ratio": quality["common_fraction"],
        })
        with session_scope() as db:
            job = db.get(Job, job_id)
            job.progress = 0.4
            job.metrics = dict(metrics)
        self._step(job_id, 2, "succeeded",
                   f"{change.changed_pixels} px / {changed_area:.2f} km² flagged")
        if runner.should_cancel(job_id):
            self._finish(job_id, "cancelled", None, jl, t_start, metrics)
            return

        # ------------------------------------------- 4. Agent selection
        self._step(job_id, 3, "running")
        with session_scope() as db:
            db.get(Job, job_id).current_stage = "agent_routing"
        datasets = self._load_context(bbox, observations, jl)
        ctx = AgentContext(
            job_id=job_id, bbox=bbox, region=region, size=settings.raster_size,
            observations=used_obs, before=before, after=after, quality=quality,
            change=change, water_before=water_before, water_after=water_after,
            datasets=datasets, config={}, log=lambda m, **k: jl.add(str(m)),
        )
        agents = build_agents()
        decisions: List[Dict[str, Any]] = []
        selected: List[BaseAgent] = []
        for agent in agents:
            try:
                ok, code, reason = agent.select(ctx)
            except Exception as exc:
                ok, code, reason = False, "ROUTER_ERROR", f"selection failed: {exc}"
            decisions.append({
                "agent_id": agent.id, "agent_name": agent.name, "selected": bool(ok),
                "reason": reason, "reason_code": code,
            })
            jl.add(f"routing · {agent.name}: "
                   + (f"SELECTED [{code}]" if ok else f"skipped [{code}]") + f" — {reason}")
            if ok:
                selected.append(agent)
        jl.add(f"{len(selected)}/{len(agents)} agents selected for execution")
        with session_scope() as db:
            job = db.get(Job, job_id)
            job.agents_selected = decisions
            job.progress = 0.5
        self._step(job_id, 3, "succeeded", f"{len(selected)} selected / {len(agents)} registered")
        if not selected:
            self._step(job_id, 4, "skipped", "no agent applicable")
            for i in (4, 5, 6):
                self._step(job_id, i, "skipped", "no candidates")
            self._finish(job_id, "succeeded",
                         None, jl, t_start, metrics)
            with session_scope() as db:
                job = db.get(Job, job_id)
                job.agents_selected = decisions
                job.progress = 1.0
            jl.add("No agent was applicable to these observations — nothing to publish.")
            return
        if runner.should_cancel(job_id):
            self._finish(job_id, "cancelled", None, jl, t_start, metrics)
            return

        # ------------------------------------------- 5. Agent execution
        self._step(job_id, 4, "running")
        with session_scope() as db:
            db.get(Job, job_id).current_stage = "agent_execution"
        wave1 = [a for a in selected if a.id not in LATE_AGENTS]
        wave2 = [a for a in selected if a.id in LATE_AGENTS]
        results: Dict[str, AgentResult] = {}
        results.update(self._execute_wave(wave1, ctx, jl, job_id))
        # late agents see what wave-1 claimed
        claimed = [c.geometry for r in results.values() for c in r.candidates
                   if c.geometry is not None and not c.geometry.is_empty]
        ctx.claimed_geometries = claimed
        if wave2:
            jl.add(f"late screen: {len(claimed)} claimed region(s) handed to "
                   + ", ".join(a.name for a in wave2))
            results.update(self._execute_wave(wave2, ctx, jl, job_id))
        agent_runs = [self._run_record(r) for r in
                      sorted(results.values(), key=lambda r: r.agent_id)]
        with session_scope() as db:
            job = db.get(Job, job_id)
            job.agent_runs = agent_runs
            job.progress = 0.72
            self._record_agent_history(db, results, job_id)
        self._step(job_id, 4, "succeeded",
                   "; ".join(f"{r.agent_id}={r.status}({len(r.candidates)})"
                             for r in sorted(results.values(), key=lambda x: x.agent_id)))
        if runner.should_cancel(job_id):
            self._finish(job_id, "cancelled", None, jl, t_start, metrics)
            return

        # ------------------------------------------- 6. Evidence validation
        self._step(job_id, 5, "running")
        with session_scope() as db:
            db.get(Job, job_id).current_stage = "evidence_validation"
        validated: List[Tuple[AgentResult, AgentCandidate, evidence_mod.ValidatedEvidence]] = []
        n_candidates = sum(len(r.candidates) for r in results.values())
        for r in results.values():
            agent_obj = next((a for a in agents if a.id == r.agent_id), None)
            if agent_obj is None:
                continue
            for cand in r.candidates:
                ev = evidence_mod.validate(
                    agent_id=agent_obj.id, agent_name=agent_obj.name,
                    method=agent_obj.baseline_method, model_version=r.model_version or agent_obj.model_version,
                    candidate=cand, ctx=ctx, result=r,
                    quality=float(quality["quality_score"]),
                )
                validated.append((r, cand, ev))
                jl.add(f"validation · {cand.title}: {ev.verification_status} "
                       f"(confidence {ev.detection_confidence:.2f}, "
                       f"completeness {ev.evidence_completeness:.2f}, "
                       f"quality {ev.data_quality:.2f})")
        with session_scope() as db:
            job = db.get(Job, job_id)
            job.progress = 0.85
        self._step(job_id, 5, "succeeded", f"{len(validated)} candidate(s) validated")
        if runner.should_cancel(job_id):
            self._finish(job_id, "cancelled", None, jl, t_start, metrics)
            return

        # ------------------------------------------- 7. Publishing
        self._step(job_id, 6, "running")
        with session_scope() as db:
            db.get(Job, job_id).current_stage = "finding_publisher"
        assets = self._write_artifacts(job_id, before, after, change, jl)
        published = self._publish(job_id, validated, assets, ctx, jl, db=None)
        finding_ids = [f["id"] for f in published]
        with session_scope() as db:
            job = db.get(Job, job_id)
            job.findings = finding_ids
            job.progress = 1.0
        self._step(job_id, 6, "succeeded", f"{len(published)} finding(s) published")
        metrics["processing_ms"] = int((time.time() - t_start) * 1000)
        jl.add(f"Published {len(published)} finding(s).")
        self._finish(job_id, "succeeded", None, jl, t_start, metrics)

    # ------------------------------------------------------------ discovery
    def _store_observations(self, observations) -> None:
        with session_scope() as db:
            for obs in observations:
                existing = db.get(Observation, obs.id)
                payload = obs.model_dump()
                payload.pop("id", None)
                if existing is None:
                    db.add(Observation(id=obs.id, **payload, first_seen=now_iso()))
                else:
                    for k, v in payload.items():
                        setattr(existing, k, v)

    # ---------------------------------------------------------- raster pair
    def _load_pair(self, observations, bbox, jl: JobLog):
        """Choose and read a compatible before/after pair (never fabricated)."""
        readable = [o for o in observations
                    if o.url and not o.requires_credentials
                    and not o.context.get("metadata_only")
                    and o.context.get("georeferenced") is not False
                    and o.source in READABLE_SOURCES]
        notes: List[str] = []
        if not readable:
            blocked = [o for o in observations if o.requires_credentials]
            detail = ""
            if blocked:
                detail = (f" {len(blocked)} discovered observation(s) require Earthdata Login "
                          "credentials that are not configured on this server.")
            raise UnsupportedAnalysisError(
                "No readable, georeferenced raster is available for this region/period. "
                "Discovered products are metadata-only or lack embedded georeferencing."
                + detail + " TerraTrace will not substitute synthetic data."
            )

        # group by source+orbit to maximise radiometric comparability
        readable.sort(key=lambda o: o.datetime or "")
        pairs: List[Tuple[Any, Any]] = []
        by_key: Dict[Tuple[str, str], List[Any]] = {}
        for o in readable:
            by_key.setdefault((o.source, (o.orbit_direction or "unknown")), []).append(o)
        # Prefer adjacent same-orbit pairs first (highest overlap probability)
        for group in by_key.values():
            for i in range(len(group) - 1):
                pairs.append((group[i], group[i + 1]))
        # Then same-orbit earliest vs latest
        for group in by_key.values():
            if len(group) >= 2:
                pairs.append((group[0], group[-1]))
        # Then overall adjacent dates
        for i in range(len(readable) - 1):
            pairs.append((readable[i], readable[i + 1]))
        # Fall back: earliest vs latest overall
        if len(readable) >= 2:
            pairs.append((readable[0], readable[-1]))

        tried = 0
        for early, late in pairs:
            if early.id == late.id:
                continue
            tried += 1
            try:
                before = read_scene(
                    early.url, bbox, source=early.source, mission=early.mission,
                    polarizations=early.polarizations or ["VV"], observation_id=early.id,
                    product_type=early.product_type, datetime_=early.datetime,
                    fallback_url=early.context.get("s3_url"),
                    platform=early.platform, orbit_direction=early.orbit_direction,
                )
                after = read_scene(
                    late.url, bbox, source=late.source, mission=late.mission,
                    polarizations=late.polarizations or ["VV"], observation_id=late.id,
                    product_type=late.product_type, datetime_=late.datetime,
                    fallback_url=late.context.get("s3_url"),
                    platform=late.platform, orbit_direction=late.orbit_direction,
                )
                # Check quality before accepting — skip low-overlap pairs
                try:
                    q = assess_pair(before, after)
                    if q["errors"] or q.get("quality_score", 0) < 0.3:
                        notes.append(
                            f"pair {early.datetime[:10]}→{late.datetime[:10]} rejected: "
                            f"low quality (co-valid {q.get('common_fraction', 0):.0%})"
                        )
                        continue
                except Exception:
                    pass
                notes.append(
                    f"Pair accepted: {early.mission}/{early.product_type} {early.datetime[:19]} "
                    f"→ {late.mission}/{late.product_type} {late.datetime[:19]} "
                    f"(read {before.read_ms} ms / {after.read_ms} ms, attempt {tried})"
                )
                used = [o for o in observations if o.id in (early.id, late.id)]
                return before, after, used, notes
            except UnsupportedAnalysisError as exc:
                notes.append(f"pair {early.datetime[:10]}→{late.datetime[:10]} rejected: {exc}")
            except Exception as exc:
                notes.append(f"pair {early.datetime[:10]}→{late.datetime[:10]} failed: {exc}")
        raise UnsupportedAnalysisError(
            "No compatible observation pair could be read for this region: "
            + " | ".join(notes[-4:])
        )

    # ---------------------------------------------------------- context data
    def _load_context(self, bbox, observations, jl: JobLog):
        from app.agents.base import ContextDatasets
        from app.data_sources.earth_search import EarthSearchSource

        ds = ContextDatasets()
        # DEM for slope-based agents
        try:
            es = EarthSearchSource()
            href = es.copernicus_dem_href(bbox)
            if href:
                from app.preprocessing.io import read_raster_array
                arr, tr, _ = read_raster_array(href, bbox, size=settings.raster_size)
                if np.isfinite(arr).any():
                    ds.dem_array, ds.dem_transform = arr, tr
                    jl.add("Context: Copernicus DEM GLO-30 loaded for slope analysis.")
                else:
                    jl.add("Context: Copernicus DEM tile returned no valid pixels.", level="WARNING")
            else:
                jl.add("Context: no Copernicus DEM tile overlaps this region.", level="WARNING")
        except Exception as exc:
            jl.add(f"Context: DEM unavailable ({exc})", level="WARNING")

        # optical corroboration
        try:
            s2 = EarthSearchSource().sentinel2_scene(bbox, None, None)
            if s2 is not None:
                ds.sentinel2 = s2
                jl.add(f"Context: Sentinel-2 scene {s2.provider_id} "
                       f"({s2.context.get('cloud_cover')}% cloud).")
        except Exception as exc:
            jl.add(f"Context: Sentinel-2 lookup failed ({exc})", level="WARNING")

        ds.dswx_product_found = any(o.product_type.startswith("DSWx") or o.product_type == "DSWx-S1"
                                    for o in observations)
        if ds.dswx_product_found:
            jl.add("Context: OPERA DSWx-S1 water product discovered in the same footprint.")
        return ds

    # -------------------------------------------------------- agent execution
    def _execute_wave(self, agents: List[BaseAgent], ctx: AgentContext, jl: JobLog,
                      job_id: str) -> Dict[str, AgentResult]:
        results: Dict[str, AgentResult] = {}
        if not agents:
            return results
        jl.add(f"Executing {len(agents)} agent(s) in parallel "
               f"(max_workers={settings.agent_max_workers}, "
               f"timeout={settings.agent_timeout_s:.0f}s, retries={settings.agent_retries})")
        with ThreadPoolExecutor(max_workers=min(settings.agent_max_workers, len(agents)),
                                thread_name_prefix="agent") as pool:
            futures = {pool.submit(self._run_agent, a, ctx, job_id): a for a in agents}
            for fut in as_completed(futures, timeout=settings.agent_timeout_s + 30):
                agent = futures[fut]
                try:
                    res = fut.result(timeout=settings.agent_timeout_s)
                except FuturesTimeout:
                    res = AgentResult(agent_id=agent.id, status="timeout",
                                      reason_code="TIMEOUT",
                                      reason=f"Agent exceeded {settings.agent_timeout_s:.0f}s.")
                    jl.add(f"agent {agent.id}: TIMEOUT", level="ERROR")
                except Exception as exc:
                    res = AgentResult(agent_id=agent.id, status="failed",
                                      reason_code="AGENT_ERROR", reason=str(exc), error=str(exc))
                    jl.add(f"agent {agent.id}: ERROR {exc}", level="ERROR")
                results[res.agent_id] = res
                if res.status == "timeout" or res.status == "failed":
                    # one retry for transient failures (never for timeouts)
                    if res.status == "failed" and settings.agent_retries > 0:
                        jl.add(f"agent {agent.id}: retrying once …", level="WARNING")
                        try:
                            retry = self._run_agent(agent, ctx, job_id)
                            results[retry.agent_id] = retry
                            jl.add(f"agent {agent.id}: retry → {retry.status}")
                        except Exception as exc:
                            jl.add(f"agent {agent.id}: retry failed: {exc}", level="ERROR")
                for line in res.logs:
                    jl.add(f"[{res.agent_id}] {line}")
                jl.add(f"agent {res.agent_id}: {res.status} "
                       f"({len(res.candidates)} candidate(s), {res.duration_ms} ms)"
                       + (f" — {res.reason}" if res.reason and res.status != "succeeded" else ""))
        return results

    def _run_agent(self, agent: BaseAgent, ctx: AgentContext, job_id: str) -> AgentResult:
        started = time.time()
        if runner.should_cancel(job_id):
            return AgentResult(agent_id=agent.id, status="skipped", reason_code="CANCELLED",
                               reason="Job cancelled before this agent ran.")
        try:
            res = agent.run(ctx)
        except Exception as exc:
            return AgentResult(agent_id=agent.id, status="failed", reason_code="AGENT_ERROR",
                               reason=f"{type(exc).__name__}: {exc}", error=str(exc),
                               duration_ms=int((time.time() - started) * 1000))
        if not res.duration_ms:
            res.duration_ms = int((time.time() - started) * 1000)
        if not res.model_version:
            res.model_version = agent.model_version
        if not res.datasets:
            res.datasets = [d["id"] for d in agent.datasets]
        return res

    @staticmethod
    def _run_record(res: AgentResult) -> Dict[str, Any]:
        return {
            "agent_id": res.agent_id, "status": res.status, "duration_ms": res.duration_ms,
            "model_version": res.model_version, "datasets": list(res.datasets),
            "candidates": len(res.candidates), "log": list(res.logs), "error": res.error,
            "reason": res.reason,
        }

    def _record_agent_history(self, db, results: Dict[str, AgentResult], job_id: str) -> None:
        for res in results.values():
            rec = db.get(AgentRecord, res.agent_id)
            if rec is None:
                continue
            rec.last_execution = {
                "at": utc_now(), "job_id": job_id, "duration_ms": res.duration_ms,
                "candidates": len(res.candidates), "status": res.status,
                "reason_code": res.reason_code, "model_version": res.model_version,
            }
            rec.last_logs = list(res.logs)[-80:]
            rec.model_version = res.model_version or rec.model_version
            rec.updated_at = utc_now()

    # ---------------------------------------------------------------- artifacts
    def _write_artifacts(self, job_id: str, before: RasterScene, after: RasterScene,
                         change, jl: JobLog) -> Dict[str, Optional[str]]:
        out_dir = settings.artifacts_dir / job_id
        out_dir.mkdir(parents=True, exist_ok=True)
        written: Dict[str, Optional[str]] = {"before_png": None, "after_png": None,
                                             "change_png": None, "geojson": None}
        try:
            b_db, a_db = before.db(before.primary_pol), after.db(after.primary_pol)
            (out_dir / "before.png").write_bytes(render_backscatter_png(b_db))
            (out_dir / "after.png").write_bytes(render_backscatter_png(a_db))
            (out_dir / "change.png").write_bytes(
                render_change_png(b_db, a_db, change.mask))
            written.update(before_png=f"/api/jobs/{job_id}/assets/before.png",
                           after_png=f"/api/jobs/{job_id}/assets/after.png",
                           change_png=f"/api/jobs/{job_id}/assets/change.png")
            geojson, _, area = mask_to_polygons(change.mask, before.transform, min_area_km2=0.0)
            payload = {
                "type": "FeatureCollection",
                "properties": {
                    "job_id": job_id, "generated_at": utc_now(),
                    "method": change.method, "threshold_db": change.threshold_db,
                    "median_shift_db": change.shift_db,
                    "changed_area_km2": round(area, 4),
                    "crs": "EPSG:4326",
                    "note": "Change mask vectorised from real SAR backscatter log-ratio analysis.",
                },
                "features": ([{"type": "Feature", "properties": {
                    "changed": True, "method": change.method,
                    "threshold_db": change.threshold_db},
                    "geometry": geojson}] if geojson else []),
            }
            (out_dir / "change.geojson").write_text(json.dumps(payload), encoding="utf-8")
            written["geojson"] = f"/api/jobs/{job_id}/assets/change.geojson"
            jl.add(f"Artifacts written: {sorted(p.name for p in out_dir.iterdir())}")
        except Exception as exc:
            jl.add(f"Artifact writing failed: {exc}", level="WARNING")
        return written

    # ---------------------------------------------------------------- publish
    def _publish(self, job_id: str,
                 validated: List[Tuple[AgentResult, AgentCandidate, evidence_mod.ValidatedEvidence]],
                 assets: Dict[str, Optional[str]], ctx: AgentContext, jl: JobLog,
                 db=None) -> List[Dict[str, Any]]:
        published: List[Dict[str, Any]] = []
        accepted_geoms = []
        seen_keys = set()
        for res, cand, ev in validated:
            if cand.geometry is None or cand.geometry.is_empty:
                continue
            # 1) duplicate inside this job
            dup_inside = any(
                overlap_ratio(cand.geometry, g) > 0.6 for g in accepted_geoms)
            if dup_inside:
                jl.add(f"de-dup: dropped '{cand.title}' (overlaps an accepted candidate >60%)",
                       level="WARNING")
                continue
            # 2) duplicate against previously published findings
            if self._is_global_duplicate(cand, ctx):
                jl.add(f"de-dup: dropped '{cand.title}' (matches an existing finding)",
                       level="WARNING")
                continue
            key = self._dedupe_key(cand, res.agent_id)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            fid = new_id("fnd")
            bbox = [float(v) for v in cand.geometry.bounds]
            centroid = list(cand.centroid)
            agent_obj = next((a for a in build_agents() if a.id == res.agent_id), None)
            category = agent_obj.category if agent_obj else "UNCASSIFIED_CHANGE"
            sources = [{"mission": o.mission, "provider_id": o.provider_id, "source": o.source,
                        "product_type": o.product_type} for o in ctx.observations]
            dates = sorted([d for d in ctx.dates if d])
            with session_scope() as dbess:
                rec = Finding(
                    id=fid, dedupe_key=key, title=cand.title, category=category,
                    agent_id=res.agent_id, job_id=job_id,
                    location_name=None, bbox=bbox, centroid=centroid,
                    geometry=cand.geojson, geometry_source="raster_vectorize",
                    observation_dates=dates, sources=sources,
                    area_km2=round(cand.area_km2, 4),
                    detection_confidence=ev.detection_confidence,
                    evidence_completeness=ev.evidence_completeness,
                    data_quality=ev.data_quality, severity=ev.severity,
                    verification_status=ev.verification_status,
                    first_observed=ev.first_observed,
                    method=ev.method.get("name", ""), model_version=ev.method.get("version", ""),
                    explanation=cand.explanation, assets=assets,
                    created_at=utc_now(), updated_at=utc_now(),
                )
                dbess.add(rec)
                dbess.add(Evidence(
                    finding_id=fid, summary=ev.summary, measurements=ev.measurements,
                    supporting=ev.supporting, conflicting=ev.conflicting,
                    uncertainty=ev.uncertainty, limitations=ev.limitations,
                    method=ev.method, persistence=ev.persistence,
                    context_datasets=ev.context_datasets,
                ))
            accepted_geoms.append(cand.geometry)
            published.append({"id": fid, "title": cand.title, "category": category})
            jl.add(f"published finding {fid}: {cand.title} "
                   f"[{ev.verification_status}, area {cand.area_km2:.2f} km²]")
        return published

    @staticmethod
    def _dedupe_key(cand: AgentCandidate, agent_id: str) -> str:
        c = cand.centroid
        raw = f"{round(c[0], 3)}|{round(c[1], 3)}|{round(cand.area_km2, 2)}|{cand.title[:40]}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:40]

    @staticmethod
    def _is_global_duplicate(cand: AgentCandidate, ctx: AgentContext) -> bool:
        if cand.geometry is None:
            return False
        minx, miny, maxx, maxy = cand.geometry.bounds
        try:
            with session_scope() as db:
                rows = (db.query(Finding)
                        .filter(Finding.bbox != None)  # noqa: E711
                        .limit(500).all())
            for row in rows:
                bb = row.bbox or []
                if len(bb) != 4:
                    continue
                if maxx < bb[0] or minx > bb[2] or maxy < bb[1] or miny > bb[3]:
                    continue
                if row.geometry is None:
                    continue
                try:
                    other = geom_from_geojson(row.geometry)
                    if overlap_ratio(cand.geometry, other) > 0.65:
                        return True
                except Exception:
                    continue
        except Exception:
            return False
        return False


orchestrator = Orchestrator()


def submit_analysis(req: AnalysisRequest) -> str:
    """Create a job row and hand it to the background runner."""
    bbox = validate_bbox(req.bbox if req.bbox else
                         list(geom_from_geojson(req.polygon).bounds) if req.polygon else None)
    area = area_km2(geom_from_geojson(req.polygon)) if req.polygon else None
    if area and area > settings_max_area():
        raise AppError("region_too_large",
                       f"Requested region is {area:,.0f} km²; the limit for one analysis is "
                       f"{settings_max_area():,.0f} km².", 413)
    job_id = new_id("job")
    with session_scope() as db:
        db.add(Job(
            id=job_id, label=req.label, status="queued", request=req.model_dump(),
            bbox=list(bbox), steps=_init_steps(), created_at=utc_now(),
        ))
    runner.submit(job_id, lambda: orchestrator.run(job_id))
    return job_id


def settings_max_area() -> float:
    from app.core.geo import MAX_AREA_KM2
    return MAX_AREA_KM2
