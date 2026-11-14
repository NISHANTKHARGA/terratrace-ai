// `/jobs/:jobId` — Steps 2 and 3: the 12-agent analysis sequence and the
// final evidence-based report. All states come from the real backend job;
// nothing is simulated.

import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  AlertTriangle,
  CheckCircle2,
  CircleDashed,
  Download,
  Loader2,
  XCircle,
} from "lucide-react";
import { Rectangle } from "react-leaflet";
import type { LatLngBoundsExpression } from "leaflet";
import { api, useApi } from "../services/api";
import { Badge, ErrorBanner, Spinner, type Tone } from "../components/ui";
import MapCanvas from "../components/MapCanvas";
import { FindingLayer, ObservationLayer } from "../components/GeoLayers";
import { AGENTS, categoryLabel } from "../lib/agents";
import { fmtDate, fmtDuration, fmtNum, humanize } from "../lib/geo";
import type {
  AnalysisJob,
  Feature,
  FeatureCollection,
  Finding,
  FindingDetail,
} from "../types";

/* ---------------------------------------------------------- agent states */

type AgentState = "waiting" | "processing" | "completed" | "insufficient" | "failed";

interface AgentDisplay {
  state: AgentState;
  /** Short honest status line shown under the agent name. */
  line: string;
}

const STATE_META: Record<
  AgentState,
  { label: string; tone: Tone; icon: typeof Loader2; cls: string; dot: string }
> = {
  waiting: { label: "Waiting", tone: "muted", icon: CircleDashed, cls: "text-slate-400", dot: "bg-slate-300" },
  processing: { label: "Processing", tone: "accent", icon: Loader2, cls: "text-accent", dot: "bg-accent" },
  completed: { label: "Completed", tone: "success", icon: CheckCircle2, cls: "text-success", dot: "bg-success" },
  insufficient: { label: "Completed", tone: "success", icon: CheckCircle2, cls: "text-success", dot: "bg-success" },
  failed: { label: "Failed", tone: "danger", icon: XCircle, cls: "text-danger", dot: "bg-danger" },
};

function deriveAgentState(job: AnalysisJob, agentId: string, publishedByAgent: Map<string, number>): AgentDisplay {
  const run = job.agent_runs.find((r) => r.agent_id === agentId);
  const decision = job.agents_selected.find((d) => d.agent_id === agentId);

  if (run) {
    switch (run.status) {
      case "succeeded": {
        const published = publishedByAgent.get(agentId) ?? 0;
        if (published > 0) {
          return {
            state: "completed",
            line: `${published} finding${published === 1 ? "" : "s"} published from ${run.candidates} candidate region${run.candidates === 1 ? "" : "s"} (${fmtDuration(run.duration_ms)}).`,
          };
        }
        if (run.candidates > 0) {
          return {
            state: "completed",
            line: `${run.candidates} candidate region${run.candidates === 1 ? "" : "s"} found — none survived evidence validation.`,
          };
        }
        return { state: "completed", line: `No change above the detection threshold (${fmtDuration(run.duration_ms)}).` };
      }
      case "no_candidates":
        return {
          state: "insufficient",
          line: "",
        };
      case "timeout":
        return { state: "failed", line: "Agent exceeded its execution time limit." };
      case "failed":
        return { state: "failed", line: run.error ?? "Agent execution failed." };
      default:
        return { state: "insufficient", line: run.reason?.trim() || "Agent skipped." };
    }
  }

  if (decision && !decision.selected) {
    return { state: "insufficient", line: "" };
  }

  const routingDone = job.steps.some((s) => s.step === 3 && s.status === "succeeded");
  const execRunning =
    job.current_stage === "agent_execution" ||
    job.current_stage === "evidence_validation" ||
    job.current_stage === "finding_publisher";

  if (decision && decision.selected && routingDone && execRunning) {
    return { state: "processing", line: "Checking the region against this agent's data requirements…" };
  }
  return { state: "waiting", line: "Queued behind the earlier agents." };
}

/* ------------------------------------------------------------ conclusion */

function buildConclusion(
  job: AnalysisJob,
  findings: Finding[],
  counts: { completed: number; insufficient: number; failed: number }
): { headline: string; body: string[] } {
  const body: string[] = [];
  const area = job.metrics?.changed_area_km2;

  if (findings.length === 0) {
    body.push(
      "No validated changes were identified in the selected area for this observation period. " +
        "This is a genuine result: the SAR change detection found no regions above its threshold, " +
        "and no specialist agent reported a detection that survived evidence validation."
    );
    body.push(
      `${counts.completed} agent${counts.completed === 1 ? "" : "s"} completed their checks; ` +
        `${counts.insufficient} reported insufficient data (suitable observations were not available for them here); ` +
        `${counts.failed} failed. Insufficient-data agents cannot be forced to produce a detection.`
    );
    return { headline: "No validated changes identified", body };
  }

  const sorted = [...findings].sort(
    (a, b) => b.detection_confidence - a.detection_confidence
  );
  const top = sorted
    .slice(0, 3)
    .map(
      (f) =>
        `${categoryLabel(f.category)} (${fmtNum(f.area_km2)} km², ${(f.detection_confidence * 100).toFixed(0)}% confidence, ${humanize(f.verification_status).toLowerCase()})`
    )
    .join("; ");
  body.push(`${findings.length} finding${findings.length === 1 ? "" : "s"} passed evidence validation. ` + `Strongest: ${top}.`);
  if (area != null) {
    body.push(`The underlying SAR change detection measured ${fmtNum(area)} km² of changed surface in the image pair.`);
  }
  const unverified = findings.filter(
    (f) => f.verification_status === "candidate_detected" || f.verification_status === "requires_verification"
  ).length;
  if (unverified > 0) {
    body.push(
      `${unverified} finding${unverified === 1 ? " is" : "s are"} still a candidate or requires follow-up verification — ` +
        "radar change detections are not field-confirmed facts."
    );
  }
  body.push(
    `${counts.insufficient} agent${counts.insufficient === 1 ? "" : "s"} reported insufficient data and checked nothing here, ` +
      "which limits the completeness of this analysis."
  );
  return { headline: `${findings.length} validated finding${findings.length === 1 ? "" : "s"}`, body };
}

/* ------------------------------------------------------------- helpers */

function missionsLabel(job: AnalysisJob): string[] {
  const set = new Map<string, string>();
  for (const o of job.observations) {
    const label =
      o.mission === "NISAR"
        ? "NISAR (NASA–ISRO)"
        : o.mission === "SENTINEL-1"
          ? "Sentinel-1 (ESA Copernicus)"
          : o.mission === "OPERA"
            ? "OPERA products (NASA JPL)"
            : o.mission === "UAVSAR"
              ? "UAVSAR (NASA/JPL airborne)"
              : humanize(o.mission);
    if (!set.has(label)) set.set(label, o.mission);
  }
  return [...set.keys()];
}

function findingToFeature(f: Finding): Feature {
  return {
    type: "Feature",
    id: f.id,
    geometry: f.geometry as Feature["geometry"],
    properties: {
      id: f.id,
      title: categoryLabel(f.category),
      category: f.category,
    },
  };
}

/* ================================================================= page */

export default function JobPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const path = jobId ? `/api/analysis/${encodeURIComponent(jobId)}` : null;
  const [jobStatus, setJobStatus] = useState<string | null>(null);
  const jobLive = useApi<AnalysisJob>(path, {
    pollMs: path !== null && !isTerminal(jobStatus) ? 1500 : 0,
  });
  const job = jobLive.data;
  useEffect(() => setJobStatus(job?.status ?? null), [job?.status]);

  const agentsLive = useApi<{ items: { id: string; status: string }[] }>("/api/agents");
  const agentStatus = useMemo(() => {
    const m = new Map<string, string>();
    for (const a of agentsLive.data?.items ?? []) m.set(a.id, a.status);
    return m;
  }, [agentsLive.data]);

  const findingsLive = useApi<{ items: Finding[] }>(
    job && job.findings.length > 0 ? `/api/findings?job_id=${encodeURIComponent(job.id)}&page_size=100` : null
  );
  const findings = findingsLive.data?.items ?? [];

  const publishedByAgent = useMemo(() => {
    const m = new Map<string, number>();
    for (const f of findings) m.set(f.agent_id, (m.get(f.agent_id) ?? 0) + 1);
    return m;
  }, [findings]);

  const counts = useMemo(() => {
    if (!job) return { completed: 0, insufficient: 0, failed: 0, processing: 0, waiting: 12 };
    let completed = 0,
      insufficient = 0,
      failed = 0,
      processing = 0,
      waiting = 0;
    for (const a of AGENTS) {
      const d = deriveAgentState(job, a.id, publishedByAgent);
      if (d.state === "completed") completed++;
      else if (d.state === "insufficient") insufficient++;
      else if (d.state === "failed") failed++;
      else if (d.state === "processing") processing++;
      else waiting++;
    }
    return { completed, insufficient, failed, processing, waiting };
  }, [job, publishedByAgent]);

  /* evidence for the selected finding */
  const [selectedFindingId, setSelectedFindingId] = useState<string | null>(null);
  const [detail, setDetail] = useState<FindingDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  useEffect(() => {
    setDetail(null);
    setDetailError(null);
    if (!selectedFindingId) return;
    let alive = true;
    api
      .finding(selectedFindingId)
      .then((d) => alive && setDetail(d))
      .catch((e) => alive && setDetailError(e instanceof Error ? e.message : String(e)));
    return () => {
      alive = false;
    };
  }, [selectedFindingId]);

  /* auto-reveal the report when the job succeeds */
  const reportRef = useRef<HTMLDivElement | null>(null);
  const wasRunning = useRef(false);
  useEffect(() => {
    if (!job) return;
    if (wasRunning.current && job.status === "succeeded" && reportRef.current) {
      reportRef.current.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    wasRunning.current = job.status === "running" || job.status === "queued";
  }, [job?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  /* ------------------------------------------------------------------ map */
  const bbox = job?.bbox ?? null;
  const mapBounds = useMemo<LatLngBoundsExpression | null>(() => {
    if (!bbox || bbox.length !== 4) return null;
    return [
      [bbox[1], bbox[0]],
      [bbox[3], bbox[2]],
    ];
  }, [bbox]);

  const findingsFC = useMemo<FeatureCollection>(
    () => ({
      type: "FeatureCollection",
      features: findings.filter((f) => f.geometry).map(findingToFeature),
    }),
    [findings]
  );

  const obsFC = useMemo<FeatureCollection>(
    () => ({
      type: "FeatureCollection",
      features: (job?.observations ?? [])
        .filter((o) => o.footprint)
        .map((o) => ({
          type: "Feature" as const,
          id: o.id,
          geometry: o.footprint as Feature["geometry"],
          properties: {
            platform: o.platform,
            product_type: o.product_type,
            datetime: o.datetime,
          },
        })),
    }),
    [job?.observations]
  );

  if (!jobId) {
    return (
      <div className="p-6 text-[13px] text-muted">No analysis job selected.</div>
    );
  }

  if (jobLive.error && !job) {
    return (
      <div className="mx-auto max-w-2xl p-6">
        <ErrorBanner message={jobLive.error} onRetry={jobLive.refetch} />
      </div>
    );
  }

  if (!job) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center">
        <Spinner size={20} className="text-accent" />
      </div>
    );
  }

  const running = job.status === "running" || job.status === "queued";
  const done = counts.completed + counts.insufficient + counts.failed;
  const conclusion = buildConclusion(job, findings, counts);

  return (
    <div className="mx-auto w-full max-w-[1180px] px-4 py-6 sm:px-6">
      {/* ------------------------------------------------------- header */}
      <div className="mb-5">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <h1 className="text-[19px] font-semibold tracking-tight text-paper">
            {job.label ?? "Analysis"}
          </h1>
          <Badge tone={running ? "accent" : job.status === "succeeded" ? "success" : job.status === "failed" ? "danger" : "amber"}>
            {running && <Loader2 size={11} className="animate-spin" />}
            {job.status}
          </Badge>
        </div>
        <p className="mt-1 text-[12.5px] text-muted">
          Started {fmtDate(job.created_at, true)} · region{" "}
          <span className="num">
            {job.bbox.map((v) => v.toFixed(2)).join(", ")}
          </span>
          {running && job.current_stage
            ? ` · ${humanize(job.current_stage).toLowerCase()}`
            : ""}
        </p>
        {running && (
          <div className="mt-2 h-1.5 w-full max-w-md overflow-hidden rounded-full bg-raised">
            <div
              className="h-full rounded-full bg-accent transition-all duration-700"
              style={{ width: `${Math.round((job.progress ?? 0) * 100)}%` }}
            />
          </div>
        )}
      </div>

      {job.error && (
        <div className="mb-5">
          <ErrorBanner message={`Analysis failed — ${job.error}`} onRetry={jobLive.refetch} />
        </div>
      )}

      {/* -------------------------------------------- 12-agent sequence */}
      <section className="no-print rounded-2xl border border-line bg-white shadow-card">
        <header className="flex items-center justify-between border-b border-line px-5 py-3.5">
          <div>
            <h2 className="text-[14px] font-semibold text-paper">The 12 agents at work</h2>
            <p className="text-[12px] text-muted">
              Each agent checks the region with its own method and data.
            </p>
          </div>
          <span className="num text-[12px] text-muted">
            {done}/12 finished
          </span>
        </header>
        <ol>
          {AGENTS.map((a, idx) => {
            const d = deriveAgentState(job, a.id, publishedByAgent);
            const m = STATE_META[d.state];
            const Icon = a.icon;
            const StateIcon = m.icon;
            const current = d.state === "processing";
            return (
              <li
                key={a.id}
                className={`flex items-start gap-3.5 px-5 py-3 ${
                  idx !== 0 ? "border-t border-line/70" : ""
                } ${current ? "bg-cyan-50/60" : ""}`}
              >
                <span
                  className={`mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border ${
                    current
                      ? "border-accent/40 bg-accent/10 text-accent"
                      : d.state === "completed"
                        ? "border-success/30 bg-success/10 text-success"
                        : d.state === "insufficient"
                          ? "border-amber/30 bg-amber/10 text-amber"
                          : d.state === "failed"
                            ? "border-danger/30 bg-danger/10 text-danger"
                            : "border-line bg-raised text-slate-400"
                  }`}
                >
                  <Icon size={17} strokeWidth={1.7} />
                </span>

                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
                    <span className="text-[13.5px] font-medium text-paper">
                      <span className="num mr-1.5 text-[11px] text-muted">{a.ordinal}</span>
                      {a.shortName} agent
                    </span>
                    <span className={`flex items-center gap-1.5 text-[12px] font-medium ${m.cls}`}>
                      <StateIcon size={13} className={current ? "animate-spin" : ""} />
                      {m.label}
                    </span>
                  </div>
                  <p className="mt-0.5 text-[12px] leading-5 text-muted">{a.checks}</p>
                  {(d.state === "completed" || d.state === "insufficient" || d.state === "failed") && d.line && (
                    <p
                      className={`mt-0.5 text-[12px] leading-5 ${
                        d.state === "failed" ? "text-danger" : d.state === "insufficient" ? "text-amber" : "text-paper/85"
                      }`}
                    >
                      {d.line}
                    </p>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      </section>

      {/* ------------------------------------------------------- report */}
      {(job.status === "succeeded" || job.status === "failed") && (
        <div ref={reportRef} className="report print-area mt-8">
          <div className="mb-4 flex items-end justify-between gap-4">
            <div>
              <h2 className="text-[18px] font-semibold tracking-tight text-paper">Analysis report</h2>
              <p className="text-[12.5px] text-muted">
                Evidence-based results for the selected area — nothing here is simulated.
              </p>
            </div>
            <button
              type="button"
              onClick={() => window.print()}
              className="no-print btn"
              title="Opens the print dialog — choose “Save as PDF”"
            >
              <Download size={14} /> Download report
            </button>
          </div>

          {job.status === "failed" && job.error && (
            <div className="mb-5">
              <ErrorBanner message={`Analysis failed — ${job.error}`} />
            </div>
          )}

          {/* overview */}
          <div className="rounded-2xl border border-line bg-white p-5 shadow-card">
            <h3 className="label mb-3">Analysis overview</h3>
            <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-[13px] md:grid-cols-4">
              <div>
                <dt className="text-[11px] text-muted">Location</dt>
                <dd className="mt-0.5 font-medium text-paper">{job.label ?? "Selected area"}</dd>
                <dd className="num text-[11.5px] text-muted">
                  {job.bbox.map((v) => v.toFixed(3)).join(", ")}
                </dd>
              </div>
              <div>
                <dt className="text-[11px] text-muted">Observation period</dt>
                <dd className="mt-0.5 text-paper">
                  {fmtDate(job.request.start)} → {fmtDate(job.request.end)}
                </dd>
              </div>
              <div>
                <dt className="text-[11px] text-muted">Data sources used</dt>
                <dd className="mt-0.5 leading-5 text-paper">
                  {missionsLabel(job).map((m) => (
                    <span key={m} className="block">{m}</span>
                  ))}
                  {missionsLabel(job).length === 0 && <span className="text-muted">—</span>}
                </dd>
              </div>
              <div>
                <dt className="text-[11px] text-muted">Agents</dt>
                <dd className="mt-0.5 text-paper">
                  {counts.completed} completed
                  <span className="text-muted"> · </span>
                  {counts.insufficient} insufficient data
                  {counts.failed > 0 && (
                    <>
                      <span className="text-muted"> · </span>
                      {counts.failed} failed
                    </>
                  )}
                </dd>
                <dd className="mt-0.5 text-[11.5px] text-muted">
                  {job.observations.length} satellite observation{job.observations.length === 1 ? "" : "s"} used
                </dd>
              </div>
            </dl>
          </div>

          {/* detected changes */}
          <section className="mt-5">
            <h3 className="label mb-3">Detected changes</h3>
            {findings.length === 0 ? (
              <div className="rounded-2xl border border-line bg-white p-5 shadow-card">
                <div className="flex items-start gap-3">
                  <AlertTriangle size={18} className="mt-0.5 shrink-0 text-amber" />
                  <p className="text-[13px] leading-6 text-paper">
                    <span className="font-medium">No validated changes were identified</span> in this area
                    for the selected period. The agents completed their checks without producing a
                    detection that survived evidence validation — no findings are invented when the
                    data shows none.
                  </p>
                </div>
              </div>
            ) : (
              <div className="grid gap-4 lg:grid-cols-2">
                {findings.map((f) => {
                  const selected = selectedFindingId === f.id;
                  return (
                    <button
                      key={f.id}
                      type="button"
                      onClick={() => setSelectedFindingId(selected ? null : f.id)}
                      className={`rounded-2xl border bg-white p-4 text-left shadow-card transition ${
                        selected ? "border-accent ring-1 ring-accent/30" : "border-line hover:border-accent/50"
                      }`}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <h4 className="text-[14px] font-semibold text-paper">
                          {categoryLabel(f.category)}
                        </h4>
                        <Badge
                          tone={
                            f.verification_status === "corroborated"
                              ? "success"
                              : f.verification_status === "insufficient_data" ||
                                  f.verification_status === "rejected_poor_quality"
                                ? "amber"
                                : "accent"
                          }
                        >
                          {humanize(f.verification_status)}
                        </Badge>
                      </div>
                      <p className="mt-1 text-[12px] text-muted">
                        {f.location.name ? `${f.location.name} · ` : ""}
                        observed {f.observation_dates.length > 0 ? f.observation_dates.map((d) => fmtDate(d)).join(", ") : "—"}
                      </p>
                      <p className="mt-2 line-clamp-2 text-[12.5px] leading-5 text-paper/85">
                        {f.explanation}
                      </p>
                      <dl className="mt-3 grid grid-cols-3 gap-3 border-t border-line/70 pt-3 text-[12px]">
                        <div>
                          <dt className="text-[10.5px] text-muted">Affected area</dt>
                          <dd className="num mt-0.5 font-medium text-paper">{fmtNum(f.area_km2)} km²</dd>
                        </div>
                        <div>
                          <dt className="text-[10.5px] text-muted">Confidence</dt>
                          <dd className="num mt-0.5 font-medium text-paper">
                            {(f.detection_confidence * 100).toFixed(0)}%
                          </dd>
                        </div>
                        <div>
                          <dt className="text-[10.5px] text-muted">Evidence</dt>
                          <dd className="mt-0.5 font-medium text-paper">
                            {f.sources.map((s) => s.mission).join(", ") || "—"}
                          </dd>
                        </div>
                      </dl>
                      <p className="mt-2 text-[11px] text-accent">
                        {selected ? "Hide evidence" : "Click to inspect evidence"}
                      </p>
                    </button>
                  );
                })}
              </div>
            )}
          </section>

          {/* evidence panel */}
          {selectedFindingId && (
            <section className="mt-4 rounded-2xl border border-line bg-white p-5 shadow-card">
              {detailError && <ErrorBanner message={detailError} />}
              {!detail && !detailError && (
                <div className="flex items-center gap-2 text-[12.5px] text-muted">
                  <Spinner size={13} /> Loading evidence…
                </div>
              )}
              {detail && (
                <>
                  <h3 className="text-[14px] font-semibold text-paper">
                    Evidence — {categoryLabel(detail.category)}
                  </h3>
                  <p className="mt-1.5 text-[12.5px] leading-6 text-paper/85">
                    {detail.evidence.summary}
                  </p>
                  <div className="mt-3 grid gap-4 md:grid-cols-2">
                    <div>
                      <h4 className="label mb-1.5">Measurements</h4>
                      <ul className="space-y-1 text-[12px] text-paper/85">
                        {Object.entries(detail.evidence.measurements).map(([k, v]) => (
                          <li key={k} className="flex justify-between gap-4 border-b border-line/60 pb-1">
                            <span className="text-muted">{humanize(k)}</span>
                            <span className="num">{v === null ? "—" : String(v)}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                    <div>
                      <h4 className="label mb-1.5">Uncertainty & limitations</h4>
                      <p className="text-[12px] leading-5 text-paper/85">{detail.evidence.uncertainty}</p>
                      <ul className="mt-1.5 list-disc space-y-0.5 pl-4 text-[11.5px] leading-5 text-muted">
                        {detail.evidence.limitations.slice(0, 4).map((l, i) => (
                          <li key={i}>{l}</li>
                        ))}
                      </ul>
                    </div>
                  </div>
                  {detail.evidence.supporting.length > 0 && (
                    <p className="mt-3 text-[12px] leading-5 text-paper/85">
                      <span className="font-medium text-success">Supporting evidence: </span>
                      {detail.evidence.supporting.join(" · ")}
                    </p>
                  )}
                  {detail.evidence.conflicting.length > 0 && (
                    <p className="mt-1.5 text-[12px] leading-5 text-paper/85">
                      <span className="font-medium text-amber">Conflicting evidence: </span>
                      {detail.evidence.conflicting.join(" · ")}
                    </p>
                  )}
                  <div className="mt-3 flex items-center justify-between">
                    <p className="text-[11.5px] text-muted">
                      Method {detail.evidence.method.name} v{detail.evidence.method.version} · agent{" "}
                      {detail.agent?.name ?? detail.agent_id}
                    </p>
                    <Link
                      to={`/findings/${detail.id}`}
                      className="no-print text-[12px] font-medium text-accent hover:underline"
                    >
                      Full finding record →
                    </Link>
                  </div>
                </>
              )}
            </section>
          )}

          {/* map results */}
          <section className="mt-5">
            <h3 className="label mb-3">Map results</h3>
            <div className="overflow-hidden rounded-2xl border border-line shadow-card">
              <MapCanvas bounds={mapBounds} fitKey={`report-${job.id}`} className="h-[420px] w-full">
                {bbox && (
                  <Rectangle
                    bounds={mapBounds!}
                    pathOptions={{
                      color: "#0E7490",
                      weight: 1.5,
                      dashArray: "6 4",
                      fillOpacity: 0.04,
                    }}
                  />
                )}
                <ObservationLayer data={obsFC} layerKey={`o-${job.id}`} visible />
                <FindingLayer
                  data={findingsFC}
                  layerKey={`f-${findings.length}`}
                  visible
                  onSelect={(feature) => {
                    const id = (feature.properties as Record<string, unknown>)?.id;
                    if (typeof id === "string") setSelectedFindingId(id);
                  }}
                />
              </MapCanvas>
            </div>
            <p className="mt-2 text-[11.5px] text-muted">
              Dashed rectangle — the analyzed region. Blue outlines — satellite observation footprints.
              Amber/cyan — detected change regions (click one to inspect its evidence above).
            </p>
          </section>

          {/* agent summary */}
          <section className="mt-5">
            <h3 className="label mb-3">Agent summary</h3>
            <div className="grid grid-cols-1 gap-2 rounded-2xl border border-line bg-white p-4 shadow-card sm:grid-cols-2 lg:grid-cols-3">
              {AGENTS.map((a) => {
                const d = deriveAgentState(job, a.id, publishedByAgent);
                const m = STATE_META[d.state];
                const registry = agentStatus.get(a.id);
                return (
                  <div key={a.id} className="flex items-center gap-2 text-[12.5px]">
                    <span className={`inline-block h-2 w-2 shrink-0 rounded-full ${m.dot}`} />
                    <Link
                      to={`/agents/${a.id}`}
                      className="truncate text-paper hover:text-accent hover:underline"
                      title={registry ? `Registry status: ${registry}` : a.shortName}
                    >
                      {a.shortName}
                    </Link>
                    <span className={`ml-auto shrink-0 text-[11px] ${m.cls}`}>{m.label}</span>
                  </div>
                );
              })}
            </div>
          </section>

          {/* conclusion */}
          <section className="mt-5 rounded-2xl border border-line bg-white p-5 shadow-card">
            <h3 className="label mb-2">Final conclusion</h3>
            <p className="text-[14px] font-medium text-paper">{conclusion.headline}</p>
            <div className="mt-2 space-y-1.5">
              {conclusion.body.map((line, i) => (
                <p key={i} className="text-[12.5px] leading-6 text-paper/85">
                  {line}
                </p>
              ))}
            </div>
            <p className="mt-3 border-t border-line/70 pt-3 text-[11.5px] leading-5 text-muted">
              Data provenance: discoveries via NASA CMR / Planetary Computer / Earth Search ·
              change detection from real SAR backscatter (log-ratio) · confidence values are
              heuristic 0–1 scores, not probabilities. Generated {fmtDate(job.ended_at, true)}.
            </p>
          </section>
        </div>
      )}

      {job.status === "cancelled" && (
        <div className="rounded-2xl border border-amber/40 bg-amber/10 p-5 text-[13px] text-amber">
          This analysis was cancelled before completion. Start a new one from the Analyze page.
        </div>
      )}
    </div>
  );
}

function isTerminal(status: string | null): boolean {
  return status === "succeeded" || status === "failed" || status === "cancelled";
}
