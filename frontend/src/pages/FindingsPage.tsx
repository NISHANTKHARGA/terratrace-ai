// `/findings` — Finding Explorer: filterable list (category, status, bbox).

import { useState } from "react";
import { Link } from "react-router-dom";
import { Layers, Search } from "lucide-react";
import { useApi } from "../services/api";
import {
  Badge,
  EmptyState,
  ErrorBanner,
  Pager,
  Panel,
  PanelLoading,
} from "../components/ui";
import { fmtDate, humanize } from "../lib/geo";
import { severityTone, verificationTone } from "../lib/status";
import type { FindingCategory, FindingListResponse, VerificationStatus } from "../types";

const CATEGORIES: FindingCategory[] = [
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
];

const STATUSES: VerificationStatus[] = [
  "candidate_detected",
  "under_investigation",
  "corroborated",
  "requires_verification",
  "insufficient_data",
  "rejected_poor_quality",
];

const PAGE_SIZE = 25;

export default function FindingsPage() {
  const [category, setCategory] = useState("");
  const [status, setStatus] = useState("");
  const [bbox, setBbox] = useState("");
  const [page, setPage] = useState(1);

  const params = new URLSearchParams();
  params.set("page", String(page));
  params.set("page_size", String(PAGE_SIZE));
  if (category) params.set("category", category);
  if (status) params.set("status", status);
  if (bbox.trim()) params.set("bbox", bbox.trim());

  const findings = useApi<FindingListResponse>(`/api/findings?${params.toString()}`);
  const items = findings.data?.items ?? [];

  function reset(patch: { category?: string; status?: string; bbox?: string }) {
    if (patch.category !== undefined) setCategory(patch.category);
    if (patch.status !== undefined) setStatus(patch.status);
    if (patch.bbox !== undefined) setBbox(patch.bbox);
    setPage(1);
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-2 border-b border-line pb-2">
        <div>
          <h1 className="flex items-center gap-2 text-[17px] font-semibold tracking-wide">
            <Layers size={16} className="text-accent" /> Finding Explorer
          </h1>
          <p className="mt-0.5 text-[12px] text-muted">
            Every published finding from <span className="font-mono">GET /api/findings</span> —
            filter by category, verification status or bounding box.
          </p>
        </div>
        <button className="btn" onClick={findings.refetch}>
          refresh
        </button>
      </div>

      {/* filters */}
      <div className="panel flex flex-wrap items-end gap-3 p-3">
        <div>
          <label className="label" htmlFor="f-category">
            category
          </label>
          <select
            id="f-category"
            className="mt-1 min-w-[200px] px-2 py-1.5 text-[12.5px] outline-none"
            value={category}
            onChange={(e) => reset({ category: e.target.value })}
          >
            <option value="">all categories</option>
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {humanize(c)}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="label" htmlFor="f-status">
            verification status
          </label>
          <select
            id="f-status"
            className="mt-1 min-w-[210px] px-2 py-1.5 text-[12.5px] outline-none"
            value={status}
            onChange={(e) => reset({ status: e.target.value })}
          >
            <option value="">all statuses</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {humanize(s)}
              </option>
            ))}
          </select>
        </div>

        <div className="min-w-[240px] flex-1">
          <label className="label" htmlFor="f-bbox">
            bbox · west, south, east, north
          </label>
          <div className="mt-1 flex items-center gap-1 border border-line bg-base px-2">
            <Search size={12} className="text-muted" />
            <input
              id="f-bbox"
              className="field border-0 bg-transparent font-mono"
              placeholder="85.2, 27.5, 85.6, 27.8"
              value={bbox}
              onChange={(e) => setBbox(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && reset({ bbox })}
            />
          </div>
        </div>

        <button className="btn" onClick={() => reset({ category: "", status: "", bbox: "" })}>
          clear filters
        </button>
      </div>

      {/* results */}
      <Panel
        title={
          findings.data
            ? `${findings.data.total} finding${findings.data.total === 1 ? "" : "s"} match`
            : "findings"
        }
      >
        {findings.error && <ErrorBanner message={findings.error} onRetry={findings.refetch} className="m-3" />}
        {findings.loading && !findings.data && <PanelLoading label="loading findings…" />}

        {!findings.loading && !findings.error && items.length === 0 && (
          <EmptyState
            title="No findings match the current filters."
            hint="No data — the backend has not discovered any observations for this area yet, or the filters exclude everything. Try clearing the filters."
          />
        )}

        {items.length > 0 && (
          <ul className="divide-y divide-line/70">
            {items.map((f) => (
              <li key={f.id}>
                <Link
                  to={`/findings/${f.id}`}
                  className="flex flex-wrap items-center gap-x-4 gap-y-1.5 px-3 py-2.5 transition-colors hover:bg-raised"
                >
                  <div className="min-w-[240px] flex-1">
                    <div className="text-[13px] leading-5 text-paper">{f.title}</div>
                    <div className="num mt-0.5 text-[10.5px] text-muted">
                      {f.id.slice(0, 14)} · {f.location.name ?? "unnamed location"} ·{" "}
                      {f.area_km2.toFixed(2)} km²
                    </div>
                  </div>

                  <div className="flex flex-wrap items-center gap-1.5">
                    <Badge tone="steel2">{humanize(f.category)}</Badge>
                    <Badge tone={verificationTone(f.verification_status)}>
                      {humanize(f.verification_status)}
                    </Badge>
                    <Badge tone={severityTone(f.severity)}>severity: {f.severity}</Badge>
                  </div>

                  <div className="num w-[150px] text-right text-[11px] text-muted">
                    <div>{fmtDate(f.first_observed ?? f.created_at)}</div>
                    <div className="text-[10px]">
                      conf {(f.detection_confidence * 100).toFixed(0)}% ·{" "}
                      {(f.data_quality * 100).toFixed(0)}% qual
                    </div>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        )}

        {findings.data && findings.data.total > 0 && (
          <Pager
            page={findings.data.page}
            pageSize={findings.data.page_size}
            total={findings.data.total}
            onPage={setPage}
          />
        )}
      </Panel>
    </div>
  );
}
