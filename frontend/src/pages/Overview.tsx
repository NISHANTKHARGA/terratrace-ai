// `/` — Global Overview: health strip, world map, recent activity,
// agent execution status, global discovery feed.

import { useMemo, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowUpRight, Globe2, Radar, RefreshCw } from "lucide-react";
import { useApi } from "../services/api";
import { useHealth } from "../components/Layout";
import {
  Badge,
  ErrorBanner,
  EmptyState,
  Panel,
  PanelLoading,
  Stat,
} from "../components/ui";
import { FindingLayer, ObservationLayer } from "../components/GeoLayers";
import { FindingsByCategoryChart } from "../components/charts";
import MapCanvas from "../components/MapCanvas";
import { fmtDate, fmtDuration, geojsonExtent, humanize, truncate } from "../lib/geo";
import {
  agentStatusTone,
  jobStatusTone,
  verificationTone,
} from "../lib/status";
import type {
  AgentSummary,
  AnalysisJob,
  FindingListResponse,
  MapLayersResponse,
} from "../types";

const PAGE = "space-y-6";

function PanelBody({ loading, error, onRetry, children }: {
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  children: ReactNode;
}) {
  if (error) return <ErrorBanner message={error} onRetry={onRetry} className="m-3" />;
  if (loading) return <PanelLoading />;
  return <>{children}</>;
}

export default function Overview() {
  const { health } = useHealth();
  const navigate = useNavigate();

  const layers = useApi<MapLayersResponse>("/api/map-layers");
  const jobs = useApi<{ items: AnalysisJob[] }>("/api/analysis");
  const agents = useApi<{ items: AgentSummary[] }>("/api/agents");
  const findings = useApi<FindingListResponse>("/api/findings?page=1&page_size=50");

  const mapBounds = useMemo(() => {
    if (!layers.data) return null;
    const combined = {
      type: "FeatureCollection" as const,
      features: [...layers.data.observations_geojson.features, ...layers.data.findings_geojson.features],
    };
    return geojsonExtent(combined);
  }, [layers.data]);

  const mapKey = useMemo(
    () =>
      layers.data
        ? JSON.stringify([
            layers.data.observations_geojson.features.length,
            layers.data.findings_geojson.features.length,
          ])
        : "empty",
    [layers.data]
  );

  const findingItems = findings.data?.items ?? [];
  const healthCounts = health?.counts;

  return (
    <div className={PAGE}>
      {/* ---------------------------------------------------- health strip */}
      <section className="panel">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-3 py-2">
          <div className="flex items-center gap-3">
            <Globe2 size={14} className="text-accent" />
            <span className="label">system health</span>
            <Badge tone={health?.status === "ok" ? "accent" : health ? "amber" : "muted"}>
              {health ? health.status : "no response"}
            </Badge>
            <span className="num text-[11.5px] text-muted">
              v{health?.version ?? "—"} · db {health?.database ?? "—"}
            </span>
          </div>
          <span className="text-[11px] text-muted">
            {health
              ? `live counts from GET /api/health · ${fmtDate(health.time, true)}`
              : "waiting for GET /api/health"}
          </span>
        </div>

        <div className="grid grid-cols-2 gap-4 p-4 md:grid-cols-4 xl:grid-cols-6">
          <Stat label="observations" value={healthCounts ? healthCounts.observations : "—"} sub="catalogued scenes" />
          <Stat label="findings" value={healthCounts ? healthCounts.findings : "—"} sub="published results" />
          <Stat label="analysis jobs" value={healthCounts ? healthCounts.jobs : "—"} sub="total submitted" />
          <Stat label="agents" value={healthCounts ? healthCounts.agents : "—"} sub="registered agents" />
          <div className="col-span-2 bg-panel px-3 py-2 xl:col-span-2">
            <div className="label">data sources</div>
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {(health?.sources ?? []).length === 0 && (
                <span className="text-[11.5px] text-muted">
                  {health ? "no sources reported by backend" : "—"}
                </span>
              )}
              {(health?.sources ?? []).map((s) => (
                <Badge
                  key={s.id}
                  title={`${s.detail} · checked ${fmtDate(s.checked_at, true)}`}
                  tone={
                    s.status === "operational"
                      ? "accent"
                      : s.status === "degraded"
                        ? "amber"
                        : s.status === "requires_credentials"
                          ? "steel"
                          : s.status === "unavailable"
                            ? "danger"
                            : "muted"
                  }
                >
                  {s.name}
                </Badge>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ----------------------------------------------- map + recent jobs */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Panel
          title="world observation footprint & published findings"
          className="xl:col-span-2"
          right={
            <button className="btn" onClick={() => navigate("/map")}>
              open map <ArrowUpRight size={12} />
            </button>
          }
          bodyClassName="relative"
        >
          <div className="h-[400px]">
            {layers.error ? (
              <ErrorBanner message={layers.error} onRetry={layers.refetch} className="m-3" />
            ) : layers.loading ? (
              <PanelLoading label="loading map layers…" />
            ) : (
              <MapCanvas bounds={mapBounds} fitKey={mapKey} className="h-full w-full">
                <ObservationLayer
                  data={layers.data!.observations_geojson}
                  layerKey={mapKey}
                  visible
                />
                <FindingLayer
                  data={layers.data!.findings_geojson}
                  layerKey={mapKey}
                  visible
                  onSelect={(feature) => {
                    const props = (feature.properties ?? {}) as Record<string, unknown>;
                    const id =
                      typeof feature.id === "string"
                        ? feature.id
                        : typeof props.id === "string"
                          ? props.id
                          : null;
                    if (id) navigate(`/findings/${id}`);
                  }}
                />
              </MapCanvas>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-4 border-t border-line px-3 py-1.5 text-[11px] text-muted">
            <span className="flex items-center gap-1.5">
              <span className="inline-block h-2 w-3 border border-steel bg-steel/20" />
              observation footprints
              <span className="num text-paper/70">
                {layers.data?.observations_geojson.features.length ?? 0}
              </span>
            </span>
            <span className="flex items-center gap-1.5">
              <span className="inline-block h-2 w-2 rounded-full bg-accent" />
              findings
              <span className="num text-paper/70">
                {layers.data?.findings_geojson.features.length ?? 0}
              </span>
            </span>
            <span className="ml-auto">© OpenStreetMap contributors © CARTO</span>
          </div>
        </Panel>

        <Panel
          title="recent analysis activity"
          right={
            <Link className="btn" to="/history">
              history
            </Link>
          }
        >
          <PanelBody
            loading={jobs.loading}
            error={jobs.error}
            onRetry={jobs.refetch}
          >
            {(jobs.data?.items ?? []).length === 0 ? (
              <EmptyState
                compact
                title="No analysis jobs yet."
                hint="Run an analysis to populate this activity feed."
              />
            ) : (
              <ul className="divide-y divide-line/70">
                {(jobs.data!.items ?? []).slice(0, 8).map((job) => (
                  <li key={job.id}>
                    <Link
                      to={`/jobs/${job.id}`}
                      className="block px-3 py-2 transition-colors hover:bg-raised"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate text-[12.5px] text-paper">
                          {job.label ?? job.id.slice(0, 12)}
                        </span>
                        <Badge tone={jobStatusTone(job.status)}>{job.status}</Badge>
                      </div>
                      <div className="mt-1 flex items-center justify-between gap-2 font-mono text-[10.5px] text-muted">
                        <span>{fmtDate(job.created_at, true)}</span>
                        <span>
                          {job.findings.length} finding{job.findings.length === 1 ? "" : "s"} ·{" "}
                          {fmtDuration(job.metrics?.processing_ms ?? null)}
                        </span>
                      </div>
                      {job.error && (
                        <div className="mt-1 truncate text-[11px] text-danger" title={job.error}>
                          {job.error}
                        </div>
                      )}
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </PanelBody>
        </Panel>
      </div>

      {/* ---------------------------------------------------- agent tiles */}
      <Panel
        title={`agent execution status · ${agents.data?.items.length ?? 0} registered`}
        right={
          <Link className="btn" to="/agents">
            agent center <ArrowUpRight size={12} />
          </Link>
        }
      >
        <PanelBody loading={agents.loading} error={agents.error} onRetry={agents.refetch}>
          <div className="grid grid-cols-2 gap-4 p-4 md:grid-cols-3 xl:grid-cols-6">
            {(agents.data?.items ?? []).map((agent) => (
              <Link
                key={agent.id}
                to={`/agents/${agent.id}`}
                className="group flex min-w-0 flex-col gap-1.5 bg-panel p-2.5 transition-colors hover:bg-raised"
              >
                <div className="flex items-center justify-between gap-1.5">
                  <span className="num text-[10.5px] text-muted">
                    {String(agent.ordinal).padStart(2, "0")}
                  </span>
                  <Badge tone={agentStatusTone(agent.status)}>{agent.status}</Badge>
                </div>
                <span className="line-clamp-2 text-[12px] leading-4 text-paper group-hover:text-accent">
                  {agent.name}
                </span>
                <span className="mt-auto truncate font-mono text-[10px] text-muted">
                  {agent.last_execution
                    ? `${agent.last_execution.status} · ${fmtDate(agent.last_execution.at)}`
                    : "no executions yet"}
                </span>
              </Link>
            ))}
            {(agents.data?.items ?? []).length === 0 && (
              <div className="col-span-full bg-panel">
                <EmptyState compact title="No agents registered by the backend yet." />
              </div>
            )}
          </div>
        </PanelBody>
      </Panel>

      {/* ------------------------------------------- discovery feed + chart */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Panel
          title="global discovery feed · latest findings"
          right={
            <Link className="btn" to="/findings">
              all findings <ArrowUpRight size={12} />
            </Link>
          }
        >
          <PanelBody loading={findings.loading} error={findings.error} onRetry={findings.refetch}>
            {findingItems.length === 0 ? (
              <EmptyState
                title="No findings published yet — run an analysis."
                hint="GET /api/findings returned an empty list; counts on this page stay at zero until the backend publishes results."
                icon={<Radar size={20} strokeWidth={1.5} />}
              />
            ) : (
              <ul className="divide-y divide-line/70">
                {findingItems.slice(0, 8).map((f) => (
                  <li key={f.id}>
                    <Link
                      to={`/findings/${f.id}`}
                      className="flex items-start gap-3 px-3 py-2 transition-colors hover:bg-raised"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-[12.5px] text-paper">{f.title}</div>
                        <div className="mt-0.5 flex flex-wrap items-center gap-2 font-mono text-[10.5px] text-muted">
                          <span>{humanize(f.category)}</span>
                          <span>·</span>
                          <span>{f.area_km2.toFixed(2)} km²</span>
                          <span>·</span>
                          <span>{fmtDate(f.created_at, true)}</span>
                          {f.location.name && (
                            <>
                              <span>·</span>
                              <span className="truncate">{f.location.name}</span>
                            </>
                          )}
                        </div>
                      </div>
                      <Badge tone={verificationTone(f.verification_status)}>
                        {f.verification_status.replace(/_/g, " ")}
                      </Badge>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
            {findings.data && findings.data.total > findingItems.length && (
              <div className="border-t border-line px-3 py-1.5 text-[11px] text-muted">
                showing {findingItems.length} of {findings.data.total} total findings
              </div>
            )}
          </PanelBody>
        </Panel>

        <Panel
          title={`findings by category${findings.data ? ` · latest ${findingItems.length} records` : ""}`}
          right={
            <button className="btn" onClick={findings.refetch} title="Refetch">
              <RefreshCw size={12} />
            </button>
          }
        >
          <div className="p-3">
            {findings.error ? (
              <ErrorBanner message={findings.error} onRetry={findings.refetch} />
            ) : findings.loading ? (
              <PanelLoading />
            ) : (
              <FindingsByCategoryChart findings={findingItems} />
            )}
          </div>
          <div className="border-t border-line px-3 py-1.5 text-[11px] text-muted">
            {truncate(
              findings.data
                ? `Computed client-side from ${findingItems.length} of ${findings.data.total} findings returned by GET /api/findings.`
                : "Awaiting GET /api/findings.",
              160
            )}
          </div>
        </Panel>
      </div>
    </div>
  );
}
