// `/findings/:findingId` — full finding record: imagery swipe/side-by-side
// comparison, change-mask overlay, evidence panel, sources and agent
// explanation, plus GeoJSON / HTML report exports.

import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ArrowLeft,
  Download,
  ExternalLink,
  FileText,
  Image as ImageIcon,
  Layers,
} from "lucide-react";
import { apiUrl, useApi } from "../services/api";
import {
  Badge,
  DataList,
  EmptyState,
  ErrorBanner,
  Panel,
  PanelLoading,
} from "../components/ui";
import { fmtDate, humanize } from "../lib/geo";
import { datasetStatusTone, severityTone, verificationTone } from "../lib/status";
import type { FindingDetail } from "../types";

/* -------------------------------------------------------------- score bar */

function ScoreBar({ label, value, note }: { label: string; value: number; note?: string }) {
  const pct = Math.max(0, Math.min(1, value)) * 100;
  return (
    <div title={note}>
      <div className="flex items-baseline justify-between">
        <span className="label">{label}</span>
        <span className="num text-[12px] text-accent">{pct.toFixed(1)}%</span>
      </div>
      <div className="mt-1 h-1 w-full bg-raised">
        <div className="h-full bg-accent" style={{ width: `${pct}%` }} />
      </div>
      {note && <div className="mt-0.5 text-[10.5px] leading-4 text-muted">{note}</div>}
    </div>
  );
}

/* ------------------------------------------------------------ comparison */

function ImageryCompare({ finding }: { finding: FindingDetail }) {
  const [mode, setMode] = useState<"swipe" | "side">("swipe");
  const [pos, setPos] = useState(50);
  const [showMask, setShowMask] = useState(false);
  const [maskOpacity, setMaskOpacity] = useState(0.55);
  const [broken, setBroken] = useState<Record<string, boolean>>({});

  const before = finding.assets.before_png ? apiUrl(finding.assets.before_png) : null;
  const after = finding.assets.after_png ? apiUrl(finding.assets.after_png) : null;
  const mask = finding.assets.change_png ? apiUrl(finding.assets.change_png) : null;

  if (!before && !after) {
    return (
      <div className="p-3">
        <EmptyState
          title="No imagery assets available for this finding."
          hint="The backend did not store before/after quicklooks (assets.before_png and assets.after_png are null). Re-run an analysis with browse imagery enabled to generate them."
          icon={<ImageIcon size={20} strokeWidth={1.5} />}
        />
      </div>
    );
  }

  const maskLayer = showMask && mask && !broken[mask] ? (
    <img
      src={mask}
      alt="change mask overlay"
      className="pointer-events-none absolute inset-0 h-full w-full object-contain"
      style={{ opacity: maskOpacity }}
      onError={() => setBroken((b) => ({ ...b, [mask]: true }))}
    />
  ) : null;

  const img = (src: string | null, key: string, alt: string) =>
    src && !broken[key] ? (
      <img
        src={src}
        alt={alt}
        className="h-full w-full object-contain"
        onError={() => setBroken((b) => ({ ...b, [key]: true }))}
      />
    ) : (
      <div className="flex h-full w-full items-center justify-center bg-base text-[11.5px] text-muted">
        {src ? "image failed to load" : "not provided"}
      </div>
    );

  return (
    <div>
      {/* control bar */}
      <div className="flex flex-wrap items-center gap-3 border-b border-line px-3 py-2">
        <div className="flex border border-line">
          <button
            className={`px-2.5 py-1 text-[11.5px] ${mode === "swipe" ? "bg-accent/15 text-accent" : "text-muted"}`}
            onClick={() => setMode("swipe")}
          >
            swipe
          </button>
          <button
            className={`border-l border-line px-2.5 py-1 text-[11.5px] ${mode === "side" ? "bg-accent/15 text-accent" : "text-muted"}`}
            onClick={() => setMode("side")}
          >
            side-by-side
          </button>
        </div>

        <label className="flex items-center gap-1.5 text-[11.5px] text-paper">
          <input
            type="checkbox"
            checked={showMask}
            onChange={(e) => setShowMask(e.target.checked)}
            disabled={!mask}
          />
          change mask
          {!mask && <span className="text-muted">(not provided)</span>}
        </label>

        {showMask && mask && (
          <label className="flex min-w-[160px] flex-1 items-center gap-2 text-[11.5px] text-muted">
            opacity
            <input
              type="range"
              className="flex-1"
              min={0}
              max={100}
              value={Math.round(maskOpacity * 100)}
              onChange={(e) => setMaskOpacity(Number(e.target.value) / 100)}
            />
            <span className="num w-9 text-right text-paper">{Math.round(maskOpacity * 100)}%</span>
          </label>
        )}
      </div>

      {/* viewport */}
      {mode === "swipe" ? (
        <div className="relative h-[380px] w-full select-none overflow-hidden bg-base">
          <div className="absolute inset-0">{img(after, "after", "after imagery")}</div>
          <div
            className="absolute inset-0"
            style={{ clipPath: `inset(0 ${100 - pos}% 0 0)` }}
          >
            {img(before, "before", "before imagery")}
          </div>
          {maskLayer}
          <div
            className="pointer-events-none absolute bottom-0 top-0 w-px bg-accent"
            style={{ left: `${pos}%` }}
          >
            <span className="absolute top-1/2 -left-2 h-4 w-4 -translate-y-1/2 border border-accent bg-base" />
          </div>
          <span className="absolute left-2 top-2 border border-line bg-base/85 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-label text-paper">
            before
          </span>
          <span className="absolute right-2 top-2 border border-line bg-base/85 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-label text-paper">
            after
          </span>
          <input
            type="range"
            className="absolute bottom-3 left-4 right-4 z-20 w-[calc(100%-2rem)]"
            min={0}
            max={100}
            value={pos}
            onChange={(e) => setPos(Number(e.target.value))}
            aria-label="Before/after comparison position"
          />
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-4">
          <figure className="relative m-0 h-[340px] bg-base">
            {img(before, "before", "before imagery")}
            <figcaption className="absolute left-2 top-2 border border-line bg-base/85 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-label">
              before
            </figcaption>
          </figure>
          <figure className="relative m-0 h-[340px] bg-base">
            {img(after, "after", "after imagery")}
            {showMask && maskLayer}
            <figcaption className="absolute left-2 top-2 border border-line bg-base/85 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-label">
              after
            </figcaption>
          </figure>
        </div>
      )}

      {mask && broken[mask] && (
        <div className="border-t border-amber/40 bg-amber/10 px-3 py-1.5 text-[11.5px] text-amber">
          The change mask asset failed to load ({finding.assets.change_png}).
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ page */

export default function FindingDetailPage() {
  const { findingId = "" } = useParams();
  const state = useApi<FindingDetail>(findingId ? `/api/findings/${findingId}` : null);
  const f = state.data;

  if (state.error && !f) {
    return (
      <div className="space-y-3 p-4">
        <ErrorBanner message={state.error} onRetry={state.refetch} />
        <Link className="btn" to="/findings">
          <ArrowLeft size={12} /> back to findings
        </Link>
      </div>
    );
  }

  if (!f) {
    return (
      <div className="p-4">
        <div className="panel">
          <PanelLoading label="loading finding…" />
        </div>
      </div>
    );
  }

  const evidence = f.evidence;
  const centroid = f.location.centroid;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Link to="/findings" className="inline-flex items-center gap-1.5 text-[12px] text-muted hover:text-accent">
          <ArrowLeft size={12} /> all findings
        </Link>
        <div className="flex flex-wrap gap-2">
          <a className="btn" href={apiUrl(`/api/findings/${f.id}/export.geojson`)} target="_blank" rel="noreferrer">
            <Download size={12} /> GeoJSON
          </a>
          <a className="btn" href={apiUrl(`/api/findings/${f.id}/report`)} target="_blank" rel="noreferrer">
            <FileText size={12} /> HTML report
          </a>
          <button className="btn" onClick={state.refetch}>
            refresh
          </button>
        </div>
      </div>

      {/* header */}
      <section className="panel">
        <div className="border-b border-line px-3 py-3">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="num text-[11px] text-muted">{f.id}</div>
              <h1 className="mt-1 text-[17px] font-semibold leading-6">{f.title}</h1>
            </div>
            <div className="flex flex-wrap gap-1.5">
              <Badge tone="steel2">{humanize(f.category)}</Badge>
              <Badge tone={verificationTone(f.verification_status)}>
                {humanize(f.verification_status)}
              </Badge>
              <Badge tone={severityTone(f.severity)}>severity {f.severity}</Badge>
            </div>
          </div>
          <div className="mt-2 grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
            <DataList
              items={[
                { label: "location", value: f.location.name ?? "unnamed" },
                { label: "area", value: <span className="num">{f.area_km2.toFixed(3)} km²</span> },
                {
                  label: "observation dates",
                  value: (
                    <span className="num">{f.observation_dates.map((d) => fmtDate(d)).join(" → ")}</span>
                  ),
                },
                { label: "first observed", value: <span className="num">{fmtDate(f.first_observed)}</span> },
                {
                  label: "centroid",
                  value: (
                    <span className="num">
                      {centroid[0].toFixed(4)}, {centroid[1].toFixed(4)}
                    </span>
                  ),
                },
                { label: "geometry source", value: humanize(f.geometry_source) },
              ]}
            />
          </div>
        </div>

        {/* scores */}
        <div className="grid grid-cols-1 gap-4 px-3 py-3 md:grid-cols-3">
          <ScoreBar
            label="detection confidence"
            value={f.detection_confidence}
            note="Heuristic score produced by the agent — not a calibrated probability."
          />
          <ScoreBar label="evidence completeness" value={f.evidence_completeness} />
          <ScoreBar label="data quality" value={f.data_quality} />
        </div>
      </section>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(320px,1fr)]">
        {/* ------------------------------------------- imagery + evidence */}
        <div className="space-y-4">
          <Panel title="before / after comparison">
            <ImageryCompare finding={f} />
          </Panel>

          <Panel
            title="evidence"
            right={
              <span className="num text-[11px] text-muted">
                {evidence.method.name} v{evidence.method.version}
              </span>
            }
          >
            <div className="space-y-3 p-3">
              <div>
                <div className="label mb-1">summary</div>
                <p className="text-[12.5px] leading-5 text-paper/90">{evidence.summary}</p>
              </div>

              <div>
                <div className="label mb-1">measurements</div>
                {Object.keys(evidence.measurements).length === 0 ? (
                  <p className="text-[12px] text-muted">No measurements recorded.</p>
                ) : (
                  <table className="w-full border border-line">
                    <tbody>
                      {Object.entries(evidence.measurements).map(([k, v]) => (
                        <tr key={k} className="border-b border-line/70 last:border-0">
                          <td className="px-2 py-1.5 font-mono text-[11.5px] text-muted">
                            {humanize(k)}
                          </td>
                          <td
                            className={`num px-2 py-1.5 text-right text-[12px] ${
                              v === null ? "text-amber" : "text-accent"
                            }`}
                          >
                            {v === null ? "not measured" : typeof v === "number" ? v.toFixed(4) : v}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>

              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                <div>
                  <div className="label mb-1">supporting evidence</div>
                  {evidence.supporting.length === 0 ? (
                    <p className="text-[12px] text-muted">None recorded.</p>
                  ) : (
                    <ul className="space-y-1.5">
                      {evidence.supporting.map((s, i) => (
                        <li key={i} className="flex gap-2 border-l-2 border-accent/60 pl-2 text-[12px] leading-5 text-paper/90">
                          {s}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
                <div>
                  <div className="label mb-1">conflicting evidence</div>
                  {evidence.conflicting.length === 0 ? (
                    <p className="text-[12px] text-muted">No conflicting signals recorded.</p>
                  ) : (
                    <ul className="space-y-1.5">
                      {evidence.conflicting.map((s, i) => (
                        <li key={i} className="flex gap-2 border-l-2 border-amber/70 pl-2 text-[12px] leading-5 text-paper/90">
                          {s}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>

              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                <div className="border border-amber/40 bg-amber/5 p-2.5">
                  <div className="label mb-1 text-amber">uncertainty</div>
                  <p className="text-[12px] leading-5 text-paper/90">{evidence.uncertainty}</p>
                </div>
                <div className="border border-line bg-raised/50 p-2.5">
                  <div className="label mb-1">persistence</div>
                  <div className="flex flex-wrap items-center gap-2 text-[12px]">
                    <Badge tone={evidence.persistence.persistent ? "accent" : "muted"}>
                      {evidence.persistence.persistent ? "persistent" : "not persistent"}
                    </Badge>
                    <span className="num text-muted">
                      {evidence.persistence.days_between !== null
                        ? `${evidence.persistence.days_between} days between dates`
                        : "days between: not computed"}
                    </span>
                  </div>
                  <div className="num mt-1 text-[11px] text-muted">
                    {evidence.persistence.dates_supporting.length > 0
                      ? evidence.persistence.dates_supporting.map((d) => fmtDate(d)).join(" · ")
                      : "no supporting dates recorded"}
                  </div>
                </div>
              </div>

              <div>
                <div className="label mb-1">limitations</div>
                {evidence.limitations.length === 0 ? (
                  <p className="text-[12px] text-muted">None declared.</p>
                ) : (
                  <ul className="list-inside list-disc space-y-1 text-[12px] leading-5 text-paper/85">
                    {evidence.limitations.map((l, i) => (
                      <li key={i}>{l}</li>
                    ))}
                  </ul>
                )}
              </div>

              <div>
                <div className="label mb-1">context datasets</div>
                <table className="w-full border border-line">
                  <thead>
                    <tr>
                      <th className="cell-th">dataset</th>
                      <th className="cell-th">status</th>
                      <th className="cell-th">note</th>
                    </tr>
                  </thead>
                  <tbody>
                    {evidence.context_datasets.length === 0 && (
                      <tr>
                        <td className="cell-td text-muted" colSpan={3}>
                          No context datasets referenced.
                        </td>
                      </tr>
                    )}
                    {evidence.context_datasets.map((d) => (
                      <tr key={d.id} className="hover:bg-raised/60">
                        <td className="cell-td num text-[11.5px]">{d.id}</td>
                        <td className="cell-td">
                          <Badge tone={datasetStatusTone(d.status)}>{humanize(d.status)}</Badge>
                        </td>
                        <td className="cell-td text-muted">{d.note}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </Panel>

          <Panel title="source observations">
            {f.source_observations.length === 0 ? (
              <EmptyState
                compact
                title="No source observations linked to this finding."
                hint="The backend returned an empty source_observations list."
              />
            ) : (
              <div className="max-h-72 overflow-auto">
                <table className="w-full min-w-[640px]">
                  <thead className="sticky top-0 bg-panel">
                    <tr>
                      <th className="cell-th">mission</th>
                      <th className="cell-th">platform</th>
                      <th className="cell-th">product</th>
                      <th className="cell-th">acquired</th>
                      <th className="cell-th">provider id</th>
                      <th className="cell-th">link</th>
                    </tr>
                  </thead>
                  <tbody>
                    {f.source_observations.map((o) => (
                      <tr key={o.id} className="hover:bg-raised/60">
                        <td className="cell-td num text-[11.5px]">{o.mission}</td>
                        <td className="cell-td">{o.platform}</td>
                        <td className="cell-td num text-[11.5px] text-steel2">{o.product_type}</td>
                        <td className="cell-td num text-[11.5px]">{fmtDate(o.datetime)}</td>
                        <td className="cell-td num text-[11px] text-muted">{o.provider_id}</td>
                        <td className="cell-td">
                          {o.url ? (
                            <a
                              href={o.url}
                              target="_blank"
                              rel="noreferrer"
                              className="inline-flex items-center gap-1 text-accent hover:underline"
                            >
                              open <ExternalLink size={11} />
                            </a>
                          ) : (
                            <span className="text-muted">—</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>
        </div>

        {/* ------------------------------------------------ right column */}
        <div className="space-y-4">
          <Panel title="agent explanation">
            <div className="p-3">
              <p className="text-[12.5px] leading-5 text-paper/90">{f.explanation}</p>
              <div className="mt-3 border-t border-line pt-2.5">
                <div className="flex items-center justify-between text-[12px]">
                  <span className="label">produced by</span>
                  <Link to={`/agents/${f.agent_id}`} className="text-accent hover:underline">
                    {f.agent.name || f.agent_id} →
                  </Link>
                </div>
                <div className="mt-1 flex items-center justify-between text-[12px]">
                  <span className="label">agent status</span>
                  <Badge tone={f.agent.status === "operational" ? "accent" : "muted"}>
                    {humanize(f.agent.status)}
                  </Badge>
                </div>
              </div>
            </div>
          </Panel>

          <Panel title="record metadata">
            <DataList
              items={[
                { label: "finding id", value: <span className="num">{f.id}</span> },
                { label: "category", value: humanize(f.category) },
                { label: "verification", value: humanize(f.verification_status) },
                { label: "severity", value: f.severity },
                { label: "method", value: <span className="num">{f.method}</span> },
                { label: "model version", value: <span className="num">{f.model_version}</span> },
                { label: "created", value: <span className="num">{fmtDate(f.created_at, true)}</span> },
                { label: "updated", value: <span className="num">{fmtDate(f.updated_at, true)}</span> },
                {
                  label: "bbox",
                  value: (
                    <span className="num">{f.location.bbox.map((n) => n.toFixed(3)).join(", ")}</span>
                  ),
                },
              ]}
            />
          </Panel>

          <Panel title="provenance">
            <div className="space-y-2 p-3 text-[12px]">
              <div className="flex items-center justify-between">
                <span className="label">analysis job</span>
                {f.job ? (
                  <Link to={`/jobs/${f.job.id}`} className="num text-accent hover:underline">
                    {f.job.id.slice(0, 12)} ({f.job.status})
                  </Link>
                ) : (
                  <span className="text-muted">not linked</span>
                )}
              </div>
              <div className="flex items-center justify-between">
                <span className="label">job created</span>
                <span className="num text-muted">{fmtDate(f.job?.created_at ?? null, true)}</span>
              </div>
              <div className="border-t border-line pt-2">
                <div className="label mb-1">catalogued sources</div>
                {f.sources.length === 0 ? (
                  <p className="text-muted">No source records returned.</p>
                ) : (
                  <ul className="space-y-1.5">
                    {f.sources.map((s, i) => (
                      <li key={i} className="border border-line bg-base px-2 py-1.5">
                        <div className="flex items-center justify-between gap-2">
                          <span className="num text-[11.5px] text-steel2">{s.mission}</span>
                          <span className="num text-[10.5px] text-muted">{s.source}</span>
                        </div>
                        <div className="num mt-0.5 truncate text-[10.5px] text-muted" title={s.provider_id}>
                          {s.product_type} · {s.provider_id}
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          </Panel>

          <Panel title="exports">
            <div className="flex flex-wrap gap-2 p-3">
              <a
                className="btn btn-primary"
                href={apiUrl(`/api/findings/${f.id}/export.geojson`)}
                target="_blank"
                rel="noreferrer"
              >
                <Download size={12} /> GeoJSON
              </a>
              <a
                className="btn btn-primary"
                href={apiUrl(`/api/findings/${f.id}/report`)}
                target="_blank"
                rel="noreferrer"
              >
                <FileText size={12} /> HTML report
              </a>
              <Link className="btn" to={`/map`}>
                <Layers size={12} /> view on map
              </Link>
            </div>
            <p className="border-t border-line px-3 py-2 text-[10.5px] leading-4 text-muted">
              Exports are served directly by the backend as{" "}
              <span className="font-mono">application/geo+json</span> and{" "}
              <span className="font-mono">text/html</span>.
            </p>
          </Panel>
        </div>
      </div>
    </div>
  );
}
