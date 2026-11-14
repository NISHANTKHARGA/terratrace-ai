// `/agents/:agentId` — single agent: config, output schema, limitations,
// evaluation and recent runs (scanned from analysis history).

import { useMemo } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, ScrollText } from "lucide-react";
import { useApi } from "../services/api";
import {
  Badge,
  EmptyState,
  ErrorBanner,
  Panel,
  PanelLoading,
  SectionHeading,
} from "../components/ui";
import { fmtDate, fmtDuration, fmtPct01, humanize, prettyJson } from "../lib/geo";
import { agentStatusTone, datasetStatusTone, jobStatusTone, runStatusTone } from "../lib/status";
import type { AgentDetail, AnalysisJob } from "../types";

export default function AgentDetailPage() {
  const { agentId = "" } = useParams();
  const agentState = useApi<AgentDetail>(agentId ? `/api/agents/${agentId}` : null);
  const analysis = useApi<{ items: AnalysisJob[] }>("/api/analysis");
  const agent = agentState.data;

  const recentRuns = useMemo(() => {
    const out: { jobId: string; createdAt: string; run: AnalysisJob["agent_runs"][number] }[] = [];
    for (const job of analysis.data?.items ?? []) {
      for (const run of job.agent_runs) {
        if (run.agent_id === agentId) out.push({ jobId: job.id, createdAt: job.created_at, run });
      }
    }
    return out.sort((a, b) => b.createdAt.localeCompare(a.createdAt)).slice(0, 12);
  }, [analysis.data, agentId]);

  if (agentState.error && !agent) {
    return (
      <div className="p-4">
        <ErrorBanner message={agentState.error} onRetry={agentState.refetch} />
        <Link className="btn mt-3" to="/agents">
          <ArrowLeft size={12} /> back to agents
        </Link>
      </div>
    );
  }

  if (!agent) {
    return (
      <div className="p-4">
        <div className="panel">
          <PanelLoading label="loading agent…" />
        </div>
      </div>
    );
  }

  const measured = agent.evaluation.filter((m) => m.value !== null).length;

  return (
    <div className="space-y-6">
      <Link to="/agents" className="inline-flex items-center gap-1.5 text-[12px] text-muted hover:text-accent">
        <ArrowLeft size={12} /> all agents
      </Link>

      <SectionHeading
        title={`${String(agent.ordinal).padStart(2, "0")} · ${agent.name}`}
        sub={agent.purpose}
        right={
          <>
            <Badge tone={agentStatusTone(agent.status)}>{agent.status}</Badge>
            <Badge tone="muted">{agent.model_version}</Badge>
          </>
        }
      />

      <div className="border border-line bg-panel px-3 py-2">
        <div className="label">status reason</div>
        <p className="mt-1 text-[12.5px] leading-5 text-paper/90">{agent.status_reason}</p>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {/* -------------------------------------------------- config/schema */}
        <div className="space-y-4">
          <Panel title="configuration">
            <pre className="max-h-80 overflow-auto p-3 font-mono text-[11.5px] leading-4 text-paper/90">
              {prettyJson(agent.config)}
            </pre>
          </Panel>

          <Panel title="output schema">
            <table className="w-full">
              <thead>
                <tr>
                  <th className="cell-th">field</th>
                  <th className="cell-th">description</th>
                </tr>
              </thead>
              <tbody>
                {Object.keys(agent.output_schema).length === 0 && (
                  <tr>
                    <td className="cell-td text-muted" colSpan={2}>
                      The backend declared no output schema for this agent.
                    </td>
                  </tr>
                )}
                {Object.entries(agent.output_schema).map(([field, desc]) => (
                  <tr key={field} className="hover:bg-raised/60">
                    <td className="cell-td num w-48 text-steel2">{field}</td>
                    <td className="cell-td text-paper/85">{desc}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>

          <Panel title="known limitations">
            {agent.known_limitations.length === 0 ? (
              <EmptyState compact title="No limitations declared by the backend." />
            ) : (
              <ul className="divide-y divide-line/70">
                {agent.known_limitations.map((l, i) => (
                  <li key={i} className="flex gap-2 px-3 py-2 text-[12.5px] leading-5 text-paper/90">
                    <span className="num shrink-0 text-amber">{String(i + 1).padStart(2, "0")}</span>
                    {l}
                  </li>
                ))}
              </ul>
            )}
          </Panel>

          <Panel title="processing logs · last run">
            {agent.processing_logs_last_run.length === 0 ? (
              <EmptyState compact title="No processing logs stored for the last run." />
            ) : (
              <div className="max-h-72 overflow-auto bg-base p-2 font-mono text-[11px] leading-4 text-paper/85">
                {agent.processing_logs_last_run.map((line, i) => (
                  <div key={i} className="whitespace-pre-wrap break-words">
                    {line}
                  </div>
                ))}
              </div>
            )}
          </Panel>
        </div>

        {/* ------------------------------------------------ evaluation/runs */}
        <div className="space-y-4">
          <Panel
            title="evaluation metrics"
            right={
              <span className="num text-[11px] text-muted">
                {measured} / {agent.evaluation.length} measured
              </span>
            }
          >
            <table className="w-full">
              <thead>
                <tr>
                  <th className="cell-th">metric</th>
                  <th className="cell-th text-right">value</th>
                  <th className="cell-th">note</th>
                </tr>
              </thead>
              <tbody>
                {agent.evaluation.length === 0 && (
                  <tr>
                    <td className="cell-td text-muted" colSpan={3}>
                      No evaluation metrics defined.
                    </td>
                  </tr>
                )}
                {agent.evaluation.map((m) => (
                  <tr key={m.metric} className="hover:bg-raised/60">
                    <td className="cell-td">{humanize(m.metric)}</td>
                    <td
                      className={`cell-td num text-right ${
                        m.value === null ? "text-amber" : "text-accent"
                      }`}
                    >
                      {m.value === null ? "not measured" : fmtPct01(m.value)}
                    </td>
                    <td className="cell-td text-muted">{m.note || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>

          <Panel title="datasets & capabilities">
            <div className="border-b border-line">
              <table className="w-full">
                <thead>
                  <tr>
                    <th className="cell-th">dataset</th>
                    <th className="cell-th">status</th>
                    <th className="cell-th">note</th>
                  </tr>
                </thead>
                <tbody>
                  {agent.datasets.length === 0 && (
                    <tr>
                      <td className="cell-td text-muted" colSpan={3}>
                        No datasets registered for this agent.
                      </td>
                    </tr>
                  )}
                  {agent.datasets.map((d) => (
                    <tr key={d.id} className="hover:bg-raised/60">
                      <td className="cell-td">
                        <div className="text-paper">{d.name}</div>
                        <div className="num text-[10.5px] text-muted">{d.id}</div>
                      </td>
                      <td className="cell-td">
                        <Badge tone={datasetStatusTone(d.status)}>{d.status}</Badge>
                      </td>
                      <td className="cell-td text-muted">{d.note}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="grid grid-cols-1 gap-3 p-3 md:grid-cols-2">
              <div>
                <div className="label mb-1">capabilities</div>
                <div className="flex flex-wrap gap-1">
                  {agent.capabilities.length === 0 ? (
                    <span className="text-[11.5px] text-muted">none declared</span>
                  ) : (
                    agent.capabilities.map((c) => (
                      <span key={c} className="border border-line bg-raised px-1.5 py-0.5 text-[11px]">
                        {c}
                      </span>
                    ))
                  )}
                </div>
              </div>
              <div>
                <div className="label mb-1">supported inputs</div>
                <div className="flex flex-wrap gap-1">
                  {agent.supported_inputs.length === 0 ? (
                    <span className="text-[11.5px] text-muted">none declared</span>
                  ) : (
                    agent.supported_inputs.map((s) => (
                      <span key={s} className="border border-line bg-base px-1.5 py-0.5 font-mono text-[10.5px] text-steel2">
                        {s}
                      </span>
                    ))
                  )}
                </div>
              </div>
            </div>
          </Panel>

          <Panel
            title="recent runs · from analysis history"
            right={<span className="num text-[11px] text-muted">{recentRuns.length} matched</span>}
          >
            {analysis.loading && !analysis.data ? (
              <PanelLoading label="scanning /api/analysis…" />
            ) : analysis.error && !analysis.data ? (
              <ErrorBanner message={analysis.error} onRetry={analysis.refetch} className="m-3" />
            ) : recentRuns.length === 0 ? (
              <EmptyState
                compact
                title={`No recorded executions of ${agent.id} yet.`}
                hint="Runs appear here after an analysis job executes this agent."
                icon={<ScrollText size={18} strokeWidth={1.5} />}
              />
            ) : (
              <table className="w-full">
                <thead>
                  <tr>
                    <th className="cell-th">job</th>
                    <th className="cell-th">created</th>
                    <th className="cell-th">status</th>
                    <th className="cell-th text-right">duration</th>
                    <th className="cell-th text-right">candidates</th>
                    <th className="cell-th">model</th>
                  </tr>
                </thead>
                <tbody>
                  {recentRuns.map(({ jobId, createdAt, run }) => (
                    <tr key={`${jobId}-${createdAt}`} className="hover:bg-raised/60">
                      <td className="cell-td">
                        <Link to={`/jobs/${jobId}`} className="num text-accent hover:underline">
                          {jobId.slice(0, 10)}
                        </Link>
                      </td>
                      <td className="cell-td num text-muted">{fmtDate(createdAt, true)}</td>
                      <td className="cell-td">
                        <Badge tone={runStatusTone(run.status)}>{run.status}</Badge>
                      </td>
                      <td className="cell-td num text-right">{fmtDuration(run.duration_ms)}</td>
                      <td className="cell-td num text-right">{run.candidates}</td>
                      <td className="cell-td num text-[11px] text-steel2">{run.model_version}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Panel>

          <Panel title="last execution">
            {agent.last_execution ? (
              <div className="flex flex-wrap items-center gap-4 px-3 py-2.5 text-[12.5px]">
                <Badge tone={runStatusTone(agent.last_execution.status)}>
                  {agent.last_execution.status}
                </Badge>
                <span className="num text-muted">{fmtDate(agent.last_execution.at, true)}</span>
                <span className="num text-muted">{fmtDuration(agent.last_execution.duration_ms)}</span>
                <span className="num text-muted">{agent.last_execution.candidates} candidates</span>
                <Link
                  to={`/jobs/${agent.last_execution.job_id}`}
                  className="ml-auto text-accent hover:underline"
                >
                  open job {agent.last_execution.job_id.slice(0, 10)} →
                </Link>
              </div>
            ) : (
              <EmptyState compact title="This agent has never been executed." />
            )}
          </Panel>

          <Panel title="baseline">
            <div className="px-3 py-2.5">
              <div className="label mb-1">method</div>
              <div className="border border-line bg-base px-2 py-1.5 font-mono text-[12px] text-paper/90">
                {agent.baseline_method}
              </div>
              <div className="label mb-1 mt-3">last analysis jobs (context)</div>
              <div className="flex flex-wrap gap-1.5">
                {(analysis.data?.items ?? []).slice(0, 5).map((j) => (
                  <Link key={j.id} to={`/jobs/${j.id}`}>
                    <Badge tone={jobStatusTone(j.status)}>{j.id.slice(0, 8)}</Badge>
                  </Link>
                ))}
                {(analysis.data?.items ?? []).length === 0 && (
                  <span className="text-[11.5px] text-muted">no jobs yet</span>
                )}
              </div>
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}
