// `/models` — Model & Training Center: model registry and training runs
// with honest handling of unmeasured metrics.

import { Database, GraduationCap } from "lucide-react";
import { useApi } from "../services/api";
import { Badge, EmptyState, ErrorBanner, Panel, PanelLoading } from "../components/ui";
import { fmtDate, fmtNum, humanize, prettyJson } from "../lib/geo";
import { modelStatusTone, runStatusTone } from "../lib/status";
import type { ModelInfo, TrainingRun } from "../types";

function kindLabel(kind: ModelInfo["kind"]): string {
  switch (kind) {
    case "baseline_algorithm":
      return "baseline algorithm";
    case "trained_model":
      return "trained model";
    case "pretrained_adapter":
      return "pretrained adapter";
    default:
      return humanize(kind);
  }
}

export default function ModelsPage() {
  const models = useApi<{ items: ModelInfo[] }>("/api/models");
  const runs = useApi<{ items: TrainingRun[] }>("/api/training/runs");

  const modelItems = models.data?.items ?? [];
  const runItems = runs.data?.items ?? [];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-2 border-b border-line pb-2">
        <div>
          <h1 className="flex items-center gap-2 text-[17px] font-semibold tracking-wide">
            <GraduationCap size={16} className="text-accent" /> Model & Training Center
          </h1>
          <p className="mt-0.5 text-[12px] text-muted">
            Model registry from <span className="font-mono">GET /api/models</span> and training
            history from <span className="font-mono">GET /api/training/runs</span>. Null metrics
            are shown as “not measured”, never as a fabricated score.
          </p>
        </div>
        <div className="flex gap-2">
          <button className="btn" onClick={models.refetch}>
            refresh models
          </button>
          <button className="btn" onClick={runs.refetch}>
            refresh runs
          </button>
        </div>
      </div>

      {/* ------------------------------------------------------ models */}
      <Panel
        title="model registry"
        right={<span className="num text-[11px] text-muted">{modelItems.length}</span>}
      >
        {models.error && <ErrorBanner message={models.error} onRetry={models.refetch} className="m-3" />}
        {models.loading && !models.data && <PanelLoading />}
        {!models.loading && !models.error && modelItems.length === 0 && (
          <EmptyState
            title="No models registered yet."
            hint="GET /api/models returned an empty list — baselines are registered per agent once the backend starts."
            icon={<Database size={20} strokeWidth={1.5} />}
          />
        )}
        {modelItems.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[980px]">
              <thead>
                <tr>
                  <th className="cell-th">model</th>
                  <th className="cell-th">agent</th>
                  <th className="cell-th">kind</th>
                  <th className="cell-th">version</th>
                  <th className="cell-th">status</th>
                  <th className="cell-th">metrics</th>
                  <th className="cell-th">training</th>
                </tr>
              </thead>
              <tbody>
                {modelItems.map((m) => (
                  <tr key={m.id} className="align-top hover:bg-raised/60">
                    <td className="cell-td">
                      <div className="text-paper">{m.name}</div>
                      <div className="num text-[10.5px] text-muted">{m.id}</div>
                    </td>
                    <td className="cell-td">
                      <span className="num text-steel2">{m.agent_id}</span>
                    </td>
                    <td className="cell-td text-[11.5px] text-muted">{kindLabel(m.kind)}</td>
                    <td className="cell-td num text-[11.5px]">{m.version}</td>
                    <td className="cell-td">
                      <Badge tone={modelStatusTone(m.status)}>{m.status}</Badge>
                    </td>
                    <td className="cell-td">
                      {m.metrics.length === 0 ? (
                        <span className="text-[11.5px] text-muted">no metrics defined</span>
                      ) : (
                        <ul className="space-y-0.5">
                          {m.metrics.map((metric, i) => (
                            <li key={`${metric.name}-${i}`} className="flex items-baseline gap-2 text-[11.5px]">
                              <span className="text-muted">{metric.name}</span>
                              <span
                                className={`num ${metric.value === null ? "text-amber" : "text-accent"}`}
                              >
                                {metric.value === null ? "not measured" : fmtNum(metric.value, 4)}
                              </span>
                              {metric.split && (
                                <span className="num text-[10px] text-muted">({metric.split})</span>
                              )}
                            </li>
                          ))}
                        </ul>
                      )}
                    </td>
                    <td className="cell-td text-[11px] text-muted">
                      <div className="num">{fmtDate(m.trained_at, true)}</div>
                      <div className="num">
                        {m.sample_count !== null ? `${m.sample_count} samples` : "sample count n/a"}
                      </div>
                      {m.checkpoint_path && (
                        <div className="num truncate" title={m.checkpoint_path}>
                          {m.checkpoint_path}
                        </div>
                      )}
                      {m.limitations.length > 0 && (
                        <ul className="mt-1 list-inside list-disc space-y-0.5 text-[10.5px]">
                          {m.limitations.map((l, i) => (
                            <li key={i}>{l}</li>
                          ))}
                        </ul>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {/* ---------------------------------------------- training runs */}
      <Panel
        title="training runs"
        right={<span className="num text-[11px] text-muted">{runItems.length}</span>}
      >
        {runs.error && <ErrorBanner message={runs.error} onRetry={runs.refetch} className="m-3" />}
        {runs.loading && !runs.data && <PanelLoading />}
        {!runs.loading && !runs.error && runItems.length === 0 && (
          <EmptyState
            title="No training runs recorded."
            hint="GET /api/training/runs returned an empty list — nothing has been trained yet."
          />
        )}
        {runItems.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px]">
              <thead>
                <tr>
                  <th className="cell-th">run</th>
                  <th className="cell-th">agent / model</th>
                  <th className="cell-th">status</th>
                  <th className="cell-th">started</th>
                  <th className="cell-th">ended</th>
                  <th className="cell-th">datasets</th>
                  <th className="cell-th">metrics</th>
                  <th className="cell-th">notes</th>
                </tr>
              </thead>
              <tbody>
                {runItems.map((r) => (
                  <tr key={r.id} className="align-top hover:bg-raised/60">
                    <td className="cell-td num text-[11px] text-muted">{r.id}</td>
                    <td className="cell-td">
                      <div className="num text-steel2">{r.agent_id}</div>
                      <div className="num text-[11px] text-muted">{r.model_id}</div>
                    </td>
                    <td className="cell-td">
                      <Badge tone={runStatusTone(r.status)}>{r.status.replace(/_/g, " ")}</Badge>
                    </td>
                    <td className="cell-td num text-[11px]">{fmtDate(r.started_at, true)}</td>
                    <td className="cell-td num text-[11px]">{fmtDate(r.ended_at, true)}</td>
                    <td className="cell-td">
                      <div className="flex flex-wrap gap-1">
                        {r.dataset_ids.length === 0 ? (
                          <span className="text-muted">—</span>
                        ) : (
                          r.dataset_ids.map((d) => (
                            <span key={d} className="border border-line bg-base px-1 py-px font-mono text-[10px] text-steel2">
                              {d}
                            </span>
                          ))
                        )}
                      </div>
                    </td>
                    <td className="cell-td">
                      {Object.keys(r.metrics).length === 0 ? (
                        <span className="text-[11.5px] text-muted">no metrics</span>
                      ) : (
                        <ul className="space-y-0.5">
                          {Object.entries(r.metrics).map(([k, v]) => (
                            <li key={k} className="text-[11.5px]">
                              <span className="text-muted">{k}</span>{" "}
                              <span className="num text-accent">{fmtNum(v, 4)}</span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </td>
                    <td className="cell-td max-w-[260px] text-[11.5px] text-muted">
                      {r.notes || "—"}
                      <details className="mt-1">
                        <summary className="cursor-pointer text-[10.5px] text-steel2">
                          config
                        </summary>
                        <pre className="mt-1 max-h-40 overflow-auto border border-line bg-base p-1.5 font-mono text-[10.5px] leading-4">
                          {prettyJson(r.config)}
                        </pre>
                      </details>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
