// `/reports` — Previous analysis reports and published findings.

import { Link } from "react-router-dom";
import { ChevronRight, FileText, Loader2 } from "lucide-react";
import { useApi } from "../services/api";
import { Badge, EmptyState, ErrorBanner, type Tone } from "../components/ui";
import { categoryLabel } from "../lib/agents";
import { fmtDate } from "../lib/geo";
import type { AnalysisJob, FindingListResponse } from "../types";

function jobTone(status: string): Tone {
  switch (status) {
    case "succeeded":
      return "success";
    case "running":
    case "queued":
      return "accent";
    case "failed":
      return "danger";
    case "cancelled":
      return "amber";
    default:
      return "muted";
  }
}

function regionLabel(job: AnalysisJob): string {
  if (job.label) return job.label;
  if (job.bbox && job.bbox.length === 4) {
    return `${job.bbox[1].toFixed(2)}°, ${job.bbox[0].toFixed(2)}° region`;
  }
  return job.id;
}

export default function ReportsPage() {
  const jobs = useApi<{ items: AnalysisJob[] }>("/api/analysis");
  const findings = useApi<FindingListResponse>("/api/findings?page_size=50");

  return (
    <div className="mx-auto w-full max-w-[900px] flex-1 px-4 py-6 sm:px-6">
      <h1 className="text-[18px] font-semibold tracking-tight text-paper">Reports</h1>
      <p className="mt-0.5 text-[12.5px] text-muted">
        Previous analyses of selected areas and their published findings.
      </p>

      {/* analyses */}
      <section className="mt-5">
        <h2 className="label mb-2">Analyses</h2>
        {jobs.error && <ErrorBanner message={jobs.error} onRetry={jobs.refetch} />}
        {jobs.loading && !jobs.data && (
          <div className="flex items-center gap-2 rounded-2xl border border-line bg-white p-4 text-[12.5px] text-muted shadow-card">
            <Loader2 size={14} className="animate-spin" /> loading…
          </div>
        )}
        {jobs.data && (jobs.data.items ?? []).length === 0 && (
          <div className="rounded-2xl border border-line bg-white shadow-card">
            <EmptyState
              compact
              title="No analyses yet."
              hint="Select an area on the Analyze page and run the agents."
            />
          </div>
        )}
        {jobs.data && (jobs.data.items ?? []).length > 0 && (
          <ul className="divide-y divide-line/70 overflow-hidden rounded-2xl border border-line bg-white shadow-card">
            {(jobs.data.items ?? []).map((job) => (
              <li key={job.id}>
                <Link
                  to={`/jobs/${job.id}`}
                  className="flex items-center gap-3 px-4 py-3 transition hover:bg-raised/60"
                >
                  <FileText size={16} className="shrink-0 text-muted" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[13.5px] font-medium text-paper">
                      {regionLabel(job)}
                    </p>
                    <p className="text-[11.5px] text-muted">
                      {fmtDate(job.created_at)} · {job.findings.length} finding
                      {job.findings.length === 1 ? "" : "s"}
                      {job.metrics?.changed_area_km2 != null
                        ? ` · ${job.metrics.changed_area_km2.toFixed(2)} km² changed`
                        : ""}
                    </p>
                  </div>
                  <Badge tone={jobTone(job.status)}>
                    {job.status === "running" || job.status === "queued" ? (
                      <Loader2 size={10} className="animate-spin" />
                    ) : null}
                    {job.status}
                  </Badge>
                  <ChevronRight size={15} className="shrink-0 text-slate-300" />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* published findings */}
      <section className="mt-6">
        <h2 className="label mb-2">Published findings</h2>
        {findings.error && <ErrorBanner message={findings.error} onRetry={findings.refetch} />}
        {findings.loading && !findings.data && (
          <div className="flex items-center gap-2 rounded-2xl border border-line bg-white p-4 text-[12.5px] text-muted shadow-card">
            <Loader2 size={14} className="animate-spin" /> loading…
          </div>
        )}
        {findings.data && (findings.data.items ?? []).length === 0 && (
          <div className="rounded-2xl border border-line bg-white shadow-card">
            <EmptyState compact title="No findings published yet." />
          </div>
        )}
        {findings.data && (findings.data.items ?? []).length > 0 && (
          <ul className="divide-y divide-line/70 overflow-hidden rounded-2xl border border-line bg-white shadow-card">
            {(findings.data.items ?? []).map((f) => (
              <li key={f.id}>
                <Link
                  to={`/findings/${f.id}`}
                  className="flex items-center gap-3 px-4 py-3 transition hover:bg-raised/60"
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[13.5px] font-medium text-paper">
                      {categoryLabel(f.category)}
                    </p>
                    <p className="text-[11.5px] text-muted">
                      {f.location.name ? `${f.location.name} · ` : ""}
                      {f.area_km2.toFixed(2)} km² ·{" "}
                      {(f.detection_confidence * 100).toFixed(0)}% confidence ·{" "}
                      {f.sources.map((s) => s.mission).join(", ")}
                    </p>
                  </div>
                  <ChevronRight size={15} className="shrink-0 text-slate-300" />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
