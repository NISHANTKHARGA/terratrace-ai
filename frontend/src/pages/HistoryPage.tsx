// `/history` — Reports & History: history feed, analysis jobs, findings over
// time, agent runtime chart and client-side exports of loaded records.

import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Download, History as HistoryIcon, ScrollText } from "lucide-react";
import { useApi } from "../services/api";
import {
  Badge,
  EmptyState,
  ErrorBanner,
  Panel,
  PanelLoading,
  SectionHeading,
} from "../components/ui";
import { AgentRuntimeChart, FindingsOverTimeChart } from "../components/charts";
import { downloadText, fmtDate, fmtDuration } from "../lib/geo";
import { jobStatusTone } from "../lib/status";
import type { AnalysisJob, Finding, FindingListResponse, HistoryEntry } from "../types";

const FINDINGS_EXPORT_LIMIT = 500;

function toCsv(rows: (string | number)[][]): string {
  return rows
    .map((row) =>
      row
        .map((cell) => {
          const s = String(cell ?? "");
          return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
        })
        .join(",")
    )
    .join("\n");
}

export default function HistoryPage() {
  const history = useApi<{ items: HistoryEntry[] }>("/api/history?page=1&page_size=100");
  const jobs = useApi<{ items: AnalysisJob[] }>("/api/analysis");
  const findings = useApi<FindingListResponse>(`/api/findings?page=1&page_size=${FINDINGS_EXPORT_LIMIT}`);

  const [exportNote, setExportNote] = useState<string | null>(null);

  const historyItems = history.data?.items ?? [];
  const jobItems = jobs.data?.items ?? [];
  const findingItems = findings.data?.items ?? [];

  // mean runtime per agent across every run found in the loaded job history
  const runtimeSeries = useMemo(() => {
    const acc = new Map<string, { total: number; count: number }>();
    for (const job of jobItems) {
      for (const run of job.agent_runs) {
        const cur = acc.get(run.agent_id) ?? { total: 0, count: 0 };
        cur.total += run.duration_ms;
        cur.count += 1;
        acc.set(run.agent_id, cur);
      }
    }
    return [...acc.entries()].map(([name, v]) => ({
      name,
      ms: Math.round(v.total / v.count),
    }));
  }, [jobItems]);

  const totalRuns = useMemo(
    () => jobItems.reduce((n, j) => n + j.agent_runs.length, 0),
    [jobItems]
  );

  function exportHistory() {
    const rows: (string | number)[][] = [
      ["kind", "id", "label", "status", "created_at", "findings_count", "bbox"],
      ...historyItems.map((h) => [
        h.kind,
        h.id,
        h.label,
        h.status,
        h.created_at,
        h.findings_count,
        h.bbox.join(" "),
      ]),
    ];
    downloadText("terratrace-history.csv", toCsv(rows), "text/csv;charset=utf-8");
    setExportNote(`Exported ${historyItems.length} history records as CSV.`);
  }

  function exportFindingsGeoJson() {
    const fc = {
      type: "FeatureCollection" as const,
      features: findingItems.map((f: Finding) => ({
        type: "Feature" as const,
        id: f.id,
        geometry: {
          type: "Point" as const,
          coordinates: [f.location.centroid[1], f.location.centroid[0]],
        },
        properties: {
          id: f.id,
          title: f.title,
          category: f.category,
          verification_status: f.verification_status,
          severity: f.severity,
          area_km2: f.area_km2,
          first_observed: f.first_observed,
          created_at: f.created_at,
          agent_id: f.agent_id,
          job_id: f.job_id,
          bbox: f.location.bbox,
        },
      })),
    };
    downloadText(
      "terratrace-findings.geojson",
      JSON.stringify(fc, null, 2),
      "application/geo+json;charset=utf-8"
    );
    setExportNote(`Exported ${findingItems.length} loaded findings as GeoJSON.`);
  }

  return (
    <div className="space-y-6">
      <SectionHeading
        title="Reports & History"
        sub="Analysis history, discovery feed and derived charts — every value comes from the API."
        right={
          <>
            <button className="btn" onClick={exportHistory} disabled={historyItems.length === 0}>
              <Download size={12} /> history CSV
            </button>
            <button
              className="btn"
              onClick={exportFindingsGeoJson}
              disabled={findingItems.length === 0}
            >
              <Download size={12} /> findings GeoJSON ({findingItems.length})
            </button>
            <button className="btn" onClick={() => { history.refetch(); jobs.refetch(); findings.refetch(); }}>
              refresh
            </button>
          </>
        }
      />

      {exportNote && (
        <div className="border border-accent/40 bg-accent/10 px-3 py-1.5 text-[12px] text-accent">
          {exportNote} Exports contain only records already loaded from the API.
        </div>
      )}

      {/* ------------------------------------------------------- charts */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <Panel
          title="findings over time · by month"
          right={
            <span className="num text-[11px] text-muted">
              {findings.data ? `${findingItems.length} of ${findings.data.total} loaded` : ""}
            </span>
          }
        >
          {findings.error && (
            <ErrorBanner message={findings.error} onRetry={findings.refetch} className="m-3" />
          )}
          {findings.loading && !findings.data ? (
            <PanelLoading />
          ) : (
            <FindingsOverTimeChart findings={findingItems} />
          )}
        </Panel>

        <Panel
          title="agent runtime · mean per agent"
          right={<span className="num text-[11px] text-muted">{totalRuns} runs</span>}
        >
          {jobs.error && <ErrorBanner message={jobs.error} onRetry={jobs.refetch} className="m-3" />}
          {jobs.loading && !jobs.data ? (
            <PanelLoading />
          ) : (
            <div className="p-2">
              <AgentRuntimeChart runs={runtimeSeries} />
              <p className="mt-1 px-1 text-[10.5px] text-muted">
                Averages <span className="num">{totalRuns}</span> recorded agent runs across{" "}
                <span className="num">{jobItems.length}</span> loaded jobs.
              </p>
            </div>
          )}
        </Panel>
      </div>

      {/* ------------------------------------------------------- history */}
      <Panel
        title="history feed · GET /api/history"
        right={<span className="num text-[11px] text-muted">{historyItems.length}</span>}
      >
        {history.error && (
          <ErrorBanner message={history.error} onRetry={history.refetch} className="m-3" />
        )}
        {history.loading && !history.data && <PanelLoading />}
        {!history.loading && !history.error && historyItems.length === 0 && (
          <EmptyState
            title="No history yet — the backend has not recorded analyses or discoveries."
            hint="Run an analysis to populate this report."
            icon={<HistoryIcon size={20} strokeWidth={1.5} />}
          />
        )}
        {historyItems.length > 0 && (
          <div className="max-h-[420px] overflow-auto">
            <table className="w-full min-w-[760px]">
              <thead className="sticky top-0 bg-panel">
                <tr>
                  <th className="cell-th">kind</th>
                  <th className="cell-th">label</th>
                  <th className="cell-th">status</th>
                  <th className="cell-th">created</th>
                  <th className="cell-th text-right">findings</th>
                  <th className="cell-th">bbox</th>
                </tr>
              </thead>
              <tbody>
                {historyItems.map((h) => (
                  <tr key={`${h.kind}-${h.id}`} className="hover:bg-raised/60">
                    <td className="cell-td">
                      <Badge tone={h.kind === "analysis" ? "steel2" : "amber"}>{h.kind}</Badge>
                    </td>
                    <td className="cell-td">
                      <Link to={`/jobs/${h.id}`} className="text-accent hover:underline">
                        {h.label || h.id.slice(0, 12)}
                      </Link>
                    </td>
                    <td className="cell-td">
                      <Badge tone={jobStatusTone(h.status)}>{h.status}</Badge>
                    </td>
                    <td className="cell-td num text-[11.5px]">{fmtDate(h.created_at, true)}</td>
                    <td className="cell-td num text-right">{h.findings_count}</td>
                    <td className="cell-td num text-[11px] text-muted">
                      {h.bbox?.map((n) => Number(n).toFixed(2)).join(", ") || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {/* ------------------------------------------------------ job list */}
      <Panel
        title="analysis jobs · GET /api/analysis"
        right={<span className="num text-[11px] text-muted">{jobItems.length}</span>}
      >
        {jobs.error && <ErrorBanner message={jobs.error} onRetry={jobs.refetch} className="m-3" />}
        {jobs.loading && !jobs.data && <PanelLoading />}
        {!jobs.loading && !jobs.error && jobItems.length === 0 && (
          <EmptyState
            title="No analysis jobs recorded."
            hint="Jobs appear here once POST /api/analysis has been used."
            icon={<ScrollText size={20} strokeWidth={1.5} />}
          />
        )}
        {jobItems.length > 0 && (
          <div className="max-h-[420px] overflow-auto">
            <table className="w-full min-w-[820px]">
              <thead className="sticky top-0 bg-panel">
                <tr>
                  <th className="cell-th">job</th>
                  <th className="cell-th">label</th>
                  <th className="cell-th">status</th>
                  <th className="cell-th">created</th>
                  <th className="cell-th text-right">findings</th>
                  <th className="cell-th text-right">processing</th>
                  <th className="cell-th">stage</th>
                </tr>
              </thead>
              <tbody>
                {jobItems.map((j) => (
                  <tr key={j.id} className="hover:bg-raised/60">
                    <td className="cell-td">
                      <Link to={`/jobs/${j.id}`} className="num text-accent hover:underline">
                        {j.id.slice(0, 12)}
                      </Link>
                    </td>
                    <td className="cell-td">{j.label ?? "—"}</td>
                    <td className="cell-td">
                      <Badge tone={jobStatusTone(j.status)}>{j.status}</Badge>
                    </td>
                    <td className="cell-td num text-[11.5px]">{fmtDate(j.created_at, true)}</td>
                    <td className="cell-td num text-right">{j.findings.length}</td>
                    <td className="cell-td num text-right">
                      {j.metrics?.processing_ms != null ? fmtDuration(j.metrics.processing_ms) : "—"}
                    </td>
                    <td className="cell-td text-[11.5px] text-muted">{j.current_stage ?? "—"}</td>
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
