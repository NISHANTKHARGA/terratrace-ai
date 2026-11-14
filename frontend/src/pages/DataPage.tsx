// `/data` — Data Explorer: source health, dataset catalog and observation
// search with footprint preview.

import { useMemo, useState } from "react";
import { GeoJSON } from "react-leaflet";
import { Database, RefreshCw, Satellite } from "lucide-react";
import { api, useApi } from "../services/api";
import {
  Badge,
  EmptyState,
  ErrorBanner,
  Pager,
  Panel,
  PanelLoading,
} from "../components/ui";
import MapCanvas from "../components/MapCanvas";
import { fmtBytesMb, fmtDate, parseBbox, bboxToBounds } from "../lib/geo";
import { datasetStatusTone, sourceStatusTone } from "../lib/status";
import type {
  DataSourceStatus,
  DatasetInfo,
  FeatureCollection,
  MissionId,
  Observation,
  ObservationListResponse,
} from "../types";

const MISSIONS: MissionId[] = ["NISAR", "SENTINEL-1", "OPERA", "UAVSAR", "OTHER"];
const PAGE_SIZE = 25;

/* ------------------------------------------------------------- sources */

function SourcesPanel() {
  const sources = useApi<{ items: DataSourceStatus[] }>("/api/sources");
  const [checking, setChecking] = useState<string | null>(null);
  const [items, setItems] = useState<DataSourceStatus[] | null>(null);
  const [checkError, setCheckError] = useState<string | null>(null);

  const list = items ?? sources.data?.items ?? [];

  async function recheck(id: string) {
    setChecking(id);
    setCheckError(null);
    try {
      const updated = await api.checkSource(id);
      setItems((prev) => {
        const base = prev ?? sources.data?.items ?? [];
        return base.map((s) => (s.id === id ? updated : s));
      });
    } catch (err) {
      setCheckError(`${id}: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setChecking(null);
    }
  }

  return (
    <Panel
      title="data source status · GET /api/sources"
      right={
        <button className="btn" onClick={() => { setItems(null); sources.refetch(); }}>
          <RefreshCw size={12} /> reload
        </button>
      }
    >
      {sources.error && !sources.data && (
        <ErrorBanner message={sources.error} onRetry={sources.refetch} className="m-3" />
      )}
      {sources.loading && !sources.data && <PanelLoading />}
      {checkError && (
        <div className="mx-3 mt-3 border border-amber/50 bg-amber/10 px-2.5 py-1.5 text-[11.5px] text-amber">
          re-check failed — {checkError}
        </div>
      )}
      {!sources.loading && list.length === 0 && !sources.error && (
        <EmptyState compact title="The backend reported no data sources." />
      )}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {list.map((s) => (
          <div key={s.id} className="flex min-w-0 flex-col gap-1.5 bg-panel p-3">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="truncate text-[12.5px] text-paper">{s.name}</div>
                <div className="num text-[10.5px] text-muted">
                  {s.provider} · {s.id}
                </div>
              </div>
              <Badge tone={sourceStatusTone(s.status)}>{s.status.replace(/_/g, " ")}</Badge>
            </div>
            <p className="text-[11.5px] leading-4 text-muted">{s.detail}</p>
            <div className="mt-auto flex items-center justify-between gap-2 pt-1">
              <span className="num text-[10.5px] text-muted">
                checked {fmtDate(s.checked_at, true)}
              </span>
              <div className="flex items-center gap-1.5">
                {s.auth_required && <Badge tone="amber">auth</Badge>}
                <button
                  className="btn"
                  disabled={checking === s.id}
                  onClick={() => void recheck(s.id)}
                  title="POST /api/sources/{id}/check"
                >
                  {checking === s.id ? "checking…" : "re-check"}
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>
    </Panel>
  );
}

/* ------------------------------------------------------------- datasets */

function DatasetsPanel() {
  const datasets = useApi<{ items: DatasetInfo[] }>("/api/datasets");
  const items = datasets.data?.items ?? [];

  return (
    <Panel
      title="dataset catalog · GET /api/datasets"
      right={<span className="num text-[11px] text-muted">{items.length}</span>}
    >
      {datasets.error && <ErrorBanner message={datasets.error} onRetry={datasets.refetch} className="m-3" />}
      {datasets.loading && !datasets.data && <PanelLoading />}
      {!datasets.loading && !datasets.error && items.length === 0 && (
        <EmptyState compact title="No datasets registered by the backend yet." />
      )}
      {items.length > 0 && (
        <div className="max-h-[420px] overflow-auto">
          <table className="w-full min-w-[760px]">
            <thead className="sticky top-0 bg-panel">
              <tr>
                <th className="cell-th">dataset</th>
                <th className="cell-th">status</th>
                <th className="cell-th">access</th>
                <th className="cell-th">agents</th>
                <th className="cell-th">note</th>
              </tr>
            </thead>
            <tbody>
              {items.map((d) => (
                <tr key={d.id} className="hover:bg-raised/60">
                  <td className="cell-td">
                    <div className="text-paper">{d.name}</div>
                    <div className="num text-[10.5px] text-muted">{d.id}</div>
                  </td>
                  <td className="cell-td">
                    <Badge tone={datasetStatusTone(d.status)}>{d.status.replace(/_/g, " ")}</Badge>
                  </td>
                  <td className="cell-td text-[11.5px] text-muted">
                    {d.url ? (
                      <a href={d.url} target="_blank" rel="noreferrer" className="text-accent hover:underline">
                        {d.access}
                      </a>
                    ) : (
                      d.access
                    )}
                  </td>
                  <td className="cell-td">
                    <div className="flex flex-wrap gap-1">
                      {d.agent_ids.length === 0 ? (
                        <span className="text-muted">—</span>
                      ) : (
                        d.agent_ids.map((a) => (
                          <span key={a} className="border border-line bg-base px-1 py-px font-mono text-[10px] text-steel2">
                            {a}
                          </span>
                        ))
                      )}
                    </div>
                  </td>
                  <td className="cell-td text-[11.5px] text-muted">{d.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

/* ---------------------------------------------------------- observations */

function ObservationsPanel() {
  const [bbox, setBbox] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [mission, setMission] = useState("");
  const [source, setSource] = useState("");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Observation | null>(null);

  const params = new URLSearchParams();
  params.set("page", String(page));
  params.set("page_size", String(PAGE_SIZE));
  const parsed = parseBbox(bbox);
  if (parsed) params.set("bbox", parsed.join(","));
  if (start) params.set("start", start);
  if (end) params.set("end", end);
  if (mission) params.set("mission", mission);
  if (source.trim()) params.set("source", source.trim());

  const observations = useApi<ObservationListResponse>(`/api/observations?${params.toString()}`);
  const items = observations.data?.items ?? [];

  const previewBounds = useMemo(() => {
    if (!selected) return null;
    if (selected.footprint?.coordinates?.[0]) {
      const ring = selected.footprint.coordinates[0];
      const lngs = ring.map((c) => c[0]);
      const lats = ring.map((c) => c[1]);
      return [
        [Math.min(...lats), Math.min(...lngs)],
        [Math.max(...lats), Math.max(...lngs)],
      ] as [[number, number], [number, number]];
    }
    if (selected.bbox) return bboxToBounds(selected.bbox);
    return null;
  }, [selected]);

  const previewKey = selected ? `obs-${selected.id}` : "none";

  return (
    <Panel title="observation search · GET /api/observations">
      {/* filters */}
      <div className="flex flex-wrap items-end gap-3 border-b border-line p-3">
        <div className="min-w-[230px] flex-1">
          <label className="label" htmlFor="o-bbox">
            bbox · w, s, e, n
          </label>
          <input
            id="o-bbox"
            className="field mt-1 font-mono"
            placeholder="85.2, 27.5, 85.6, 27.8"
            value={bbox}
            onChange={(e) => {
              setBbox(e.target.value);
              setPage(1);
            }}
          />
        </div>
        <div>
          <label className="label" htmlFor="o-start">
            start
          </label>
          <input
            id="o-start"
            type="date"
            className="field mt-1 font-mono"
            value={start}
            onChange={(e) => {
              setStart(e.target.value);
              setPage(1);
            }}
          />
        </div>
        <div>
          <label className="label" htmlFor="o-end">
            end
          </label>
          <input
            id="o-end"
            type="date"
            className="field mt-1 font-mono"
            value={end}
            onChange={(e) => {
              setEnd(e.target.value);
              setPage(1);
            }}
          />
        </div>
        <div>
          <label className="label" htmlFor="o-mission">
            mission
          </label>
          <select
            id="o-mission"
            className="mt-1 px-2 py-1.5 text-[12.5px] outline-none"
            value={mission}
            onChange={(e) => {
              setMission(e.target.value);
              setPage(1);
            }}
          >
            <option value="">all</option>
            {MISSIONS.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label" htmlFor="o-source">
            source id
          </label>
          <input
            id="o-source"
            className="field mt-1 font-mono"
            placeholder="planetary_computer"
            value={source}
            onChange={(e) => {
              setSource(e.target.value);
              setPage(1);
            }}
          />
        </div>
        <button
          className="btn"
          onClick={() => {
            setBbox("");
            setStart("");
            setEnd("");
            setMission("");
            setSource("");
            setPage(1);
          }}
        >
          clear
        </button>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        {/* list */}
        <div className="min-w-0 bg-panel">
          {observations.error && (
            <ErrorBanner message={observations.error} onRetry={observations.refetch} className="m-3" />
          )}
          {observations.loading && !observations.data && <PanelLoading label="querying catalog…" />}
          {!observations.loading && !observations.error && items.length === 0 && (
            <EmptyState
              title="No data — the backend has not discovered any observations for this area yet."
              hint="Widen the bbox or date range, or clear the filters."
            />
          )}
          {items.length > 0 && (
            <>
              <div className="max-h-[460px] overflow-auto">
                <table className="w-full min-w-[720px]">
                  <thead className="sticky top-0 bg-panel">
                    <tr>
                      <th className="cell-th">mission</th>
                      <th className="cell-th">platform</th>
                      <th className="cell-th">product</th>
                      <th className="cell-th">acquired</th>
                      <th className="cell-th text-right">size</th>
                      <th className="cell-th">flags</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((o) => (
                      <tr
                        key={o.id}
                        className={`cursor-pointer hover:bg-raised/60 ${
                          selected?.id === o.id ? "bg-accent/10" : ""
                        }`}
                        onClick={() => setSelected(o)}
                      >
                        <td className="cell-td num text-[11.5px]">{o.mission}</td>
                        <td className="cell-td">{o.platform}</td>
                        <td className="cell-td">
                          <span className="num text-[11.5px] text-steel2">{o.product_type}</span>
                          <span className="num block text-[10px] text-muted">{o.processing_level}</span>
                        </td>
                        <td className="cell-td num text-[11.5px]">{fmtDate(o.datetime)}</td>
                        <td className="cell-td num text-right text-[11.5px]">
                          {fmtBytesMb(o.size_mb)}
                        </td>
                        <td className="cell-td">
                          <div className="flex flex-wrap gap-1">
                            {o.requires_credentials && <Badge tone="amber">credentials</Badge>}
                            {o.quality.valid_coverage !== null && (
                              <Badge tone={o.quality.valid_coverage > 0.9 ? "accent" : "steel"}>
                                {(o.quality.valid_coverage * 100).toFixed(0)}% cov
                              </Badge>
                            )}
                            {o.browse_url && <Badge tone="muted">browse</Badge>}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {observations.data && (
                <Pager
                  page={observations.data.page}
                  pageSize={observations.data.page_size}
                  total={observations.data.total}
                  onPage={setPage}
                />
              )}
            </>
          )}
        </div>

        {/* preview map */}
        <div className="bg-panel">
          <div className="flex items-center justify-between border-b border-line px-3 py-1.5">
            <span className="label">footprint preview</span>
            {selected && (
              <span className="num truncate text-[10.5px] text-muted" title={selected.provider_id}>
                {selected.provider_id.slice(0, 24)}
              </span>
            )}
          </div>
          <div className="h-[300px]">
            <MapCanvas bounds={previewBounds} fitKey={previewKey} className="h-full w-full" minZoom={1}>
              {selected?.footprint && previewBounds && (
                <FootprintPolygon observation={selected} />
              )}
            </MapCanvas>
          </div>
          <div className="border-t border-line p-3">
            {!selected ? (
              <p className="text-[11.5px] text-muted">
                Select an observation row to preview its footprint on the map.
              </p>
            ) : (
              <dl className="space-y-1.5 text-[11.5px]">
                <div className="flex justify-between gap-2">
                  <dt className="label">platform</dt>
                  <dd>{selected.platform}</dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt className="label">polarizations</dt>
                  <dd className="num">{selected.polarizations.join("/") || "—"}</dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt className="label">orbit</dt>
                  <dd className="num">{selected.orbit_direction ?? "—"}</dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt className="label">source</dt>
                  <dd className="num">{selected.source}</dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt className="label">acquired</dt>
                  <dd className="num">{fmtDate(selected.datetime, true)}</dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt className="label">quality notes</dt>
                  <dd className="text-right text-muted">
                    {selected.quality.notes.length > 0
                      ? selected.quality.notes.join("; ")
                      : "none"}
                  </dd>
                </div>
                <div className="flex gap-2 pt-1">
                  {selected.url && (
                    <a className="btn flex-1 justify-center" href={selected.url} target="_blank" rel="noreferrer">
                      product page
                    </a>
                  )}
                  <a
                    className="btn flex-1 justify-center"
                    href={api.observationBrowseUrl(selected.id)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    quicklook
                  </a>
                </div>
              </dl>
            )}
          </div>
        </div>
      </div>
    </Panel>
  );
}

function FootprintPolygon({ observation }: { observation: Observation }) {
  if (!observation.footprint) return null;
  const fc: FeatureCollection = {
    type: "FeatureCollection",
    features: [
      { type: "Feature", geometry: observation.footprint, properties: {} },
    ],
  };
  return (
    <GeoJSON
      key={observation.id}
      data={fc}
      style={{ color: "#5FD0D6", weight: 1.5, opacity: 0.95, fillOpacity: 0.12 }}
    />
  );
}

/* ------------------------------------------------------------- exports */

export default function DataPage() {
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-2 border-b border-line pb-2">
        <div>
          <h1 className="flex items-center gap-2 text-[17px] font-semibold tracking-wide">
            <Database size={16} className="text-accent" /> Data Explorer
          </h1>
          <p className="mt-0.5 text-[12px] text-muted">
            Source health, dataset catalog and the observation catalog with footprint preview.
          </p>
        </div>
        <Badge tone="muted">
          <Satellite size={10} className="mr-1" />
          WGS84 footprints
        </Badge>
      </div>

      <SourcesPanel />
      <ObservationsPanel />
      <DatasetsPanel />
    </div>
  );
}
