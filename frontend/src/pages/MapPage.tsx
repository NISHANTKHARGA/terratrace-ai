// `/map` — Step 4 companion: global map of published findings and the
// satellite observations behind them. Deliberately minimal.

import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowUpRight, Layers } from "lucide-react";
import { api, useApi } from "../services/api";
import { Spinner } from "../components/ui";
import MapCanvas from "../components/MapCanvas";
import { FindingLayer, ObservationLayer } from "../components/GeoLayers";
import { categoryLabel } from "../lib/agents";
import { featureFindingId, fmtDate, fmtNum, geojsonExtent } from "../lib/geo";
import type { Feature, FeatureCollection, FindingDetail, MapLayersResponse } from "../types";

export default function MapPage() {
  const layers = useApi<MapLayersResponse>("/api/map-layers", { pollMs: 60_000 });

  const [showFindings, setShowFindings] = useState(true);
  const [showObservations, setShowObservations] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<FindingDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const data = layers.data;

  const findingsFC = useMemo<FeatureCollection>(
    () => data?.findings_geojson ?? { type: "FeatureCollection", features: [] },
    [data]
  );
  const observationsFC = useMemo<FeatureCollection>(
    () => data?.observations_geojson ?? { type: "FeatureCollection", features: [] },
    [data]
  );

  const bounds = useMemo(() => {
    const ext = geojsonExtent({
      type: "FeatureCollection",
      features: [...findingsFC.features, ...observationsFC.features],
    });
    return ext;
  }, [findingsFC, observationsFC]);

  async function selectFeature(feature: Feature) {
    const id = featureFindingId(feature);
    if (!id) return;
    setSelectedId(id);
    setDetail(null);
    setDetailLoading(true);
    try {
      setDetail(await api.finding(id));
    } catch {
      setDetail(null);
    } finally {
      setDetailLoading(false);
    }
  }

  const findingCount = findingsFC.features.length;

  return (
    <div className="relative min-h-[calc(100vh-56px)] flex-1">
      <div className="absolute inset-0">
        <MapCanvas bounds={bounds} fitKey="global-map" minZoom={2} className="h-full w-full">
          <ObservationLayer
            data={observationsFC}
            layerKey={`o-${observationsFC.features.length}`}
            visible={showObservations}
          />
          <FindingLayer
            data={findingsFC}
            layerKey={`f-${findingCount}`}
            visible={showFindings}
            onSelect={(feature) => void selectFeature(feature)}
          />
        </MapCanvas>
      </div>

      {/* layer toggles */}
      <div className="no-print absolute left-3 top-3 z-[1000] flex flex-col gap-1.5 rounded-xl border border-line bg-white/95 p-1.5 shadow-card">
        <button
          type="button"
          onClick={() => setShowFindings(!showFindings)}
          className={`flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[12px] font-medium transition ${
            showFindings ? "bg-cyan-50 text-accent" : "text-muted hover:bg-raised"
          }`}
        >
          <Layers size={13} className={showFindings ? "text-accent" : "text-slate-400"} />
          Published findings
        </button>
        <button
          type="button"
          onClick={() => setShowObservations(!showObservations)}
          className={`flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[12px] font-medium transition ${
            showObservations ? "bg-cyan-50 text-accent" : "text-muted hover:bg-raised"
          }`}
        >
          <Layers size={13} className={showObservations ? "text-accent" : "text-slate-400"} />
          Observation footprints
        </button>
      </div>

      {/* loading / error */}
      {layers.loading && !data && (
        <div className="absolute right-3 top-3 z-[1000] flex items-center gap-2 rounded-lg border border-line bg-white/95 px-3 py-2 text-[12px] text-muted shadow-card">
          <Spinner size={13} /> loading layers…
        </div>
      )}
      {layers.error && !data && (
        <div className="absolute right-3 top-3 z-[1000] rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[12px] text-danger shadow-card">
          Map layers unavailable — {layers.error}
        </div>
      )}

      {/* selected finding card */}
      {selectedId && (
        <div className="no-print absolute bottom-4 right-4 z-[1000] w-[320px] rounded-2xl border border-line bg-white p-4 shadow-card">
          {detailLoading && (
            <div className="flex items-center gap-2 text-[12.5px] text-muted">
              <Spinner size={13} /> loading finding…
            </div>
          )}
          {detail && (
            <>
              <div className="flex items-start justify-between gap-3">
                <h3 className="text-[14px] font-semibold text-paper">
                  {categoryLabel(detail.category)}
                </h3>
                <button
                  type="button"
                  className="text-muted hover:text-paper"
                  onClick={() => setSelectedId(null)}
                  aria-label="Close"
                >
                  ✕
                </button>
              </div>
              <p className="mt-1 text-[12px] text-muted">
                {detail.location.name ? `${detail.location.name} · ` : ""}
                {detail.observation_dates.length > 0
                  ? detail.observation_dates.map((d) => fmtDate(d)).join(", ")
                  : "—"}
              </p>
              <p className="mt-2 line-clamp-3 text-[12.5px] leading-5 text-paper/85">
                {detail.explanation}
              </p>
              <dl className="mt-2.5 flex gap-4 border-t border-line/70 pt-2.5 text-[12px]">
                <div>
                  <dt className="text-[10.5px] text-muted">Area</dt>
                  <dd className="num font-medium text-paper">{fmtNum(detail.area_km2)} km²</dd>
                </div>
                <div>
                  <dt className="text-[10.5px] text-muted">Confidence</dt>
                  <dd className="num font-medium text-paper">
                    {(detail.detection_confidence * 100).toFixed(0)}%
                  </dd>
                </div>
                <div>
                  <dt className="text-[10.5px] text-muted">Source</dt>
                  <dd className="font-medium text-paper">
                    {detail.sources.map((s) => s.mission).join(", ") || "—"}
                  </dd>
                </div>
              </dl>
              <Link
                to={`/findings/${detail.id}`}
                className="mt-3 flex items-center gap-1 text-[12px] font-medium text-accent hover:underline"
              >
                Full evidence record <ArrowUpRight size={12} />
              </Link>
            </>
          )}
          {!detailLoading && !detail && (
            <p className="text-[12.5px] text-muted">Could not load this finding.</p>
          )}
        </div>
      )}

      {/* quiet counter */}
      {data && (
        <div className="no-print pointer-events-none absolute bottom-4 left-4 z-[1000] rounded-full border border-line bg-white/95 px-3 py-1.5 text-[11.5px] text-muted shadow-card">
          {findingCount} published finding{findingCount === 1 ? "" : "s"} ·{" "}
          {observationsFC.features.length} observation footprints
        </div>
      )}
    </div>
  );
}
