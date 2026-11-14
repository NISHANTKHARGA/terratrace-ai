// `/` — Step 1 of the tool: select an area on Earth, then run the 12 agents.
// The map is the main surface; a single floating panel offers the three ways
// to select (search / coordinates / draw a rectangle) and one primary action.

import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Crosshair, Eraser, MapPin, Search, Square } from "lucide-react";
import { Rectangle } from "react-leaflet";
import { api } from "../services/api";
import { Spinner } from "../components/ui";
import MapCanvas from "../components/MapCanvas";
import { fmtCoord } from "../lib/geo";
import type { AnalysisRequest } from "../types";

type BBox = [number, number, number, number]; // west, south, east, north

interface Selection {
  name: string | null;
  bbox: BBox;
}

interface PlaceResult {
  place_id: number;
  display_name: string;
  boundingbox: [string, string, string, string];
}

const EXAMPLES: { name: string; bbox: BBox; start: string; end: string }[] = [
  { name: "Kathmandu (landslide)", bbox: [85.2, 27.55, 85.5, 27.75], start: "2024-12-24", end: "2024-12-31" },
  { name: "Sydney coast (coastal)", bbox: [151.0, -34.0, 151.3, -33.7], start: "2024-01-01", end: "2024-12-31" },
  { name: "Amazon forest (loss)", bbox: [-62.0, -3.5, -61.5, -3.0], start: "2023-06-01", end: "2024-06-30" },
  { name: "California fire (burn)", bbox: [-122.5, 38.0, -122.0, 38.5], start: "2020-08-01", end: "2020-10-31" },
  { name: "Open-pit mine", bbox: [120.5, -22.0, 121.0, -21.5], start: "2023-01-01", end: "2024-12-31" },
];

/** Half-size of the box created from a point / pair of coordinates (degrees). */
const POINT_HALF = 0.5;

function pointBbox(lat: number, lng: number): BBox {
  const s = Math.max(-90, lat - POINT_HALF);
  const n = Math.min(90, lat + POINT_HALF);
  const w = Math.max(-180, lng - POINT_HALF);
  const e = Math.min(180, lng + POINT_HALF);
  return [w, s, e, n];
}

function bboxToBounds(bbox: BBox): [[number, number], [number, number]] {
  return [
    [bbox[1], bbox[0]],
    [bbox[3], bbox[2]],
  ];
}

/** Rough equirectangular area in km² (good enough for a confirmation panel). */
function areaKm2(bbox: BBox): number {
  const midLat = (bbox[1] + bbox[3]) / 2;
  const hKm = (bbox[3] - bbox[1]) * 111.32;
  const wKm = (bbox[2] - bbox[0]) * 111.32 * Math.cos((midLat * Math.PI) / 180);
  return Math.max(0, hKm * wKm);
}

function fmtArea(km2: number): string {
  if (km2 >= 10_000) return `${Math.round(km2).toLocaleString()} km²`;
  if (km2 >= 100) return `${km2.toFixed(0)} km²`;
  return `${km2.toFixed(1)} km²`;
}

function isoDaysAgo(days: number): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString().slice(0, 10);
}

export default function AnalyzePage() {
  const navigate = useNavigate();

  /* ----------------------------------------------------------- selection */
  const [selection, setSelection] = useState<Selection | null>(null);
  const [drawMode, setDrawMode] = useState(false);
  const [firstCorner, setFirstCorner] = useState<[number, number] | null>(null);
  const [hint, setHint] = useState<string | null>(null);

  /* ---------------------------------------------------------- coordinate */
  const [latText, setLatText] = useState("");
  const [lngText, setLngText] = useState("");
  const [coordError, setCoordError] = useState<string | null>(null);

  function applyCoordinates(event: FormEvent) {
    event.preventDefault();
    const lat = Number(latText.trim());
    const lng = Number(lngText.trim());
    if (latText.trim() === "" || lngText.trim() === "" || Number.isNaN(lat) || Number.isNaN(lng)) {
      setCoordError("Enter numeric latitude and longitude.");
      return;
    }
    if (lat < -90 || lat > 90 || lng < -180 || lng > 180) {
      setCoordError("Latitude must be −90…90 and longitude −180…180.");
      return;
    }
    setCoordError(null);
    setFirstCorner(null);
    setDrawMode(false);
    setSelection({ name: null, bbox: pointBbox(lat, lng) });
    setFitBounds(bboxToBounds(pointBbox(lat, lng)));
    setFitKey(`coord-${lat}-${lng}`);
  }

  /* ------------------------------------------------------------- search */
  const [placeQuery, setPlaceQuery] = useState("");
  const [places, setPlaces] = useState<PlaceResult[]>([]);
  const [placeBusy, setPlaceBusy] = useState(false);
  const [placeError, setPlaceError] = useState<string | null>(null);

  async function searchPlace(event: FormEvent) {
    event.preventDefault();
    const q = placeQuery.trim();
    if (!q) return;
    setPlaceBusy(true);
    setPlaceError(null);
    setPlaces([]);
    try {
      const res = await fetch(
        `https://nominatim.openstreetmap.org/search?format=json&limit=5&q=${encodeURIComponent(q)}`,
        { headers: { Accept: "application/json" } }
      );
      if (!res.ok) throw new Error(`search responded ${res.status}`);
      const json: unknown = await res.json();
      if (!Array.isArray(json)) throw new Error("unexpected response");
      const items = json as PlaceResult[];
      setPlaces(items);
      if (items.length === 0) setPlaceError(`No place matched “${q}”.`);
    } catch (err) {
      setPlaceError(
        `Location search unavailable (${err instanceof Error ? err.message : String(err)}). ` +
          "Use coordinates or draw a rectangle instead."
      );
    } finally {
      setPlaceBusy(false);
    }
  }

  function usePlace(p: PlaceResult) {
    const [south, north, west, east] = p.boundingbox.map(Number);
    if ([south, north, west, east].some(Number.isNaN)) return;
    const shortName = p.display_name.split(",")[0];
    setFirstCorner(null);
    setDrawMode(false);
    setPlaces([]);
    setPlaceQuery(p.display_name);
    setSelection({ name: shortName, bbox: [west, south, east, north] });
    setFitBounds(bboxToBounds([west, south, east, north]));
    setFitKey(`place-${p.place_id}`);
  }

  /* ---------------------------------------------------------------- draw */
  function handleMapClick(lat: number, lng: number) {
    if (!drawMode) return;
    if (!firstCorner) {
      setFirstCorner([lat, lng]);
      return;
    }
    const [lat0, lng0] = firstCorner;
    const w = Math.min(lng0, lng);
    const e = Math.max(lng0, lng);
    const s = Math.min(lat0, lat);
    const n = Math.max(lat0, lat);
    setFirstCorner(null);
    setDrawMode(false);
    setSelection({ name: selection?.name ?? null, bbox: [w, s, e, n] });
    setFitBounds(bboxToBounds([w, s, e, n]));
    setFitKey(`draw-${Date.now()}`);
  }

  function clearSelection() {
    setSelection(null);
    setFirstCorner(null);
    setDrawMode(false);
    setCoordError(null);
    setHint(null);
  }

  /* --------------------------------------------------------------- dates */
  const [start, setStart] = useState(isoDaysAgo(365));
  const [end, setEnd] = useState(isoDaysAgo(0));

  /* ----------------------------------------------------------------- map */
  const [fitBounds, setFitBounds] = useState<[[number, number], [number, number]] | null>(null);
  const [fitKey, setFitKey] = useState<string | null>(null);

  const preview = useMemo(() => {
    if (!selection) return null;
    return (
      <Rectangle
        bounds={bboxToBounds(selection.bbox)}
        pathOptions={{
          color: "#0E7490",
          weight: 2,
          fillColor: "#0E7490",
          fillOpacity: 0.10,
          dashArray: "6 4",
        }}
      />
    );
  }, [selection]);

  const drawingPreview = useMemo(() => {
    if (!drawMode || !firstCorner) return null;
    const [lat, lng] = firstCorner;
    return (
      <Rectangle
        bounds={[
          [lat, lng],
          [lat, lng],
        ]}
        pathOptions={{ color: "#0E7490", weight: 1, dashArray: "4 3", fillOpacity: 0.04 }}
      />
    );
  }, [drawMode, firstCorner]);

  /* -------------------------------------------------------------- submit */
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  async function runAnalysis() {
    setSubmitError(null);
    if (!selection) {
      setHint("Select an area first — search a place, enter coordinates, or draw a rectangle.");
      return;
    }
    if (!start || !end) {
      setHint("Choose the observation period (start and end dates).");
      return;
    }
    if (end < start) {
      setHint("The end date must be on or after the start date.");
      return;
    }
    setHint(null);

    const body: AnalysisRequest = {
      bbox: selection.bbox,
      start,
      end,
      label: selection.name ?? undefined,
      include_browse: true,
    };
    setSubmitting(true);
    try {
      const job = await api.createAnalysis(body);
      void navigate(`/jobs/${job.id}`);
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : String(err));
      setSubmitting(false);
    }
  }

  /* mount default view: world */
  useEffect(() => {
    if (!fitKey) setFitKey("initial");
  }, [fitKey]);

  const area = selection ? areaKm2(selection.bbox) : null;

  /* ------------------------------------------------------------- render */
  return (
    <div className="relative flex min-h-[calc(100vh-56px)] flex-1">
      {/* map fills the page */}
      <div className="absolute inset-0">
        <MapCanvas
          bounds={fitBounds}
          fitKey={fitKey ?? "initial"}
          onClick={handleMapClick}
          minZoom={2}
          className="h-full w-full"
        >
          {preview}
          {drawingPreview}
        </MapCanvas>
      </div>

      {/* floating selection panel */}
      <div className="no-print relative z-[1000] m-3 flex max-h-[calc(100vh-88px)] w-[360px] shrink-0 flex-col overflow-hidden rounded-2xl border border-line bg-white shadow-card sm:m-4 sm:w-[390px]">
        <div className="border-b border-line px-5 py-4">
          <h1 className="text-[17px] font-semibold tracking-tight text-paper">
            Select an area on Earth
          </h1>
          <p className="mt-0.5 text-[12.5px] leading-5 text-muted">
            Search, enter coordinates, or draw a rectangle. Then run the 12 agents.
          </p>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {/* Option C — search */}
          <form onSubmit={searchPlace} className="relative">
            <label className="label" htmlFor="place">
              Search location
            </label>
            <div className="mt-1.5 flex items-center gap-1.5 rounded-lg border border-line px-2.5 focus-within:border-accent/70">
              <Search size={14} className="shrink-0 text-muted" />
              <input
                id="place"
                className="w-full bg-transparent py-2 text-[13.5px] outline-none placeholder:text-slate-400"
                placeholder="Country, city or place…"
                value={placeQuery}
                onChange={(e) => setPlaceQuery(e.target.value)}
              />
              {placeBusy ? (
                <Spinner size={14} className="shrink-0 text-accent" />
              ) : (
                <button
                  type="submit"
                  className="shrink-0 rounded-md px-1.5 py-1 text-[12px] font-medium text-accent hover:bg-cyan-50"
                >
                  Find
                </button>
              )}
            </div>
            {placeError && <p className="mt-1 text-[11.5px] text-amber">{placeError}</p>}
            {places.length > 0 && (
              <ul className="absolute left-0 right-0 top-full z-20 mt-1 max-h-48 overflow-y-auto rounded-lg border border-line bg-white shadow-card">
                {places.map((p) => (
                  <li key={p.place_id}>
                    <button
                      type="button"
                      className="block w-full px-3 py-2 text-left text-[12.5px] leading-4 hover:bg-raised"
                      onClick={() => usePlace(p)}
                    >
                      {p.display_name}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </form>

          {/* Option A — coordinates */}
          <form onSubmit={applyCoordinates} className="mt-4">
            <span className="label">Coordinates</span>
            <div className="mt-1.5 grid grid-cols-2 gap-2">
              <input
                className="field py-1.5 text-[13.5px]"
                inputMode="decimal"
                placeholder="Latitude"
                aria-label="Latitude"
                value={latText}
                onChange={(e) => setLatText(e.target.value)}
              />
              <input
                className="field py-1.5 text-[13.5px]"
                inputMode="decimal"
                placeholder="Longitude"
                aria-label="Longitude"
                value={lngText}
                onChange={(e) => setLngText(e.target.value)}
              />
            </div>
            {coordError && <p className="mt-1 text-[11.5px] text-amber">{coordError}</p>}
            <button
              type="submit"
              className="mt-1.5 flex items-center gap-1.5 text-[12px] font-medium text-accent hover:underline"
            >
              <Crosshair size={12} /> Use this point
            </button>
          </form>

          {/* Option B — draw */}
          <div className="mt-4">
            <span className="label">Or draw on the map</span>
            <div className="mt-1.5 flex items-center gap-2">
              <button
                type="button"
                className={`btn flex-1 justify-center py-1.5 ${drawMode ? "btn-primary" : ""}`}
                onClick={() => {
                  setDrawMode((m) => !m);
                  setFirstCorner(null);
                }}
              >
                <Square size={13} />
                {drawMode ? "Click two corners…" : "Draw rectangle"}
              </button>
              {selection && (
                <button
                  type="button"
                  className="btn py-1.5"
                  title="Remove the selected area"
                  onClick={clearSelection}
                >
                  <Eraser size={13} /> Clear
                </button>
              )}
            </div>
            <p className="mt-1 text-[11.5px] leading-4 text-muted">
              {drawMode
                ? firstCorner
                  ? "Now click the opposite corner."
                  : "Click the first corner on the map."
                : "Click two opposite corners to select a rectangular area."}
            </p>
          </div>

          {/* confirmation panel */}
          {selection && (
            <div className="mt-4 rounded-xl border border-cyan-200/70 bg-cyan-50/50 p-3">
              <div className="flex items-start gap-2">
                <MapPin size={15} className="mt-0.5 shrink-0 text-accent" />
                <div className="min-w-0 text-[12.5px] leading-5">
                  <p className="font-medium text-paper">
                    {selection.name ?? "Selected area"}
                  </p>
                  <p className="num text-[11.5px] text-muted">
                    {fmtCoord(selection.bbox[1], "lat")} {fmtCoord(selection.bbox[0], "lng")} →{" "}
                    {fmtCoord(selection.bbox[3], "lat")} {fmtCoord(selection.bbox[2], "lng")}
                  </p>
                  <p className="text-[11.5px] text-muted">
                    Rectangle {(selection.bbox[2] - selection.bbox[0]).toFixed(2)}° ×{" "}
                    {(selection.bbox[3] - selection.bbox[1]).toFixed(2)}° · ≈ {fmtArea(area ?? 0)}
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* Example regions */}
          <div className="mt-4">
            <span className="label">Try an example region</span>
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {EXAMPLES.map((ex) => (
                <button
                  key={ex.name}
                  type="button"
                  onClick={() => {
                    setFirstCorner(null);
                    setDrawMode(false);
                    setSelection({ name: ex.name, bbox: ex.bbox });
                    setFitBounds(bboxToBounds(ex.bbox));
                    setFitKey(`example-${ex.name}`);
                    setStart(ex.start);
                    setEnd(ex.end);
                    setHint(null);
                  }}
                  className="rounded-full border border-line bg-white px-2.5 py-1 text-[11.5px] text-paper hover:border-accent hover:text-accent"
                >
                  {ex.name}
                </button>
              ))}
            </div>
            <p className="mt-1 text-[11px] leading-4 text-muted">
              Preset areas that exercise different agents. Each runs on real NASA observations.
            </p>
          </div>
          {/* observation period */}
          <div className="mt-4">
            <span className="label">Observation period</span>
            <div className="mt-1.5 grid grid-cols-2 gap-2">
              <label className="block">
                <span className="sr-only">Start date</span>
                <input
                  type="date"
                  className="field py-1.5 text-[13px]"
                  value={start}
                  max={end}
                  onChange={(e) => setStart(e.target.value)}
                />
              </label>
              <label className="block">
                <span className="sr-only">End date</span>
                <input
                  type="date"
                  className="field py-1.5 text-[13px]"
                  value={end}
                  max={isoDaysAgo(0)}
                  onChange={(e) => setEnd(e.target.value)}
                />
              </label>
            </div>
          </div>

          {hint && <p className="mt-3 text-[12px] text-amber">{hint}</p>}
          {submitError && (
            <div className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[12px] leading-5 text-danger">
              {submitError}
            </div>
          )}

          {/* primary action */}
          <button
            type="button"
            onClick={() => void runAnalysis()}
            disabled={submitting}
            className="mt-4 flex w-full items-center justify-center gap-2 rounded-xl bg-accent py-3 text-[14.5px] font-semibold text-white shadow-sm transition hover:bg-cyan-800 disabled:cursor-not-allowed disabled:opacity-55"
          >
            {submitting && <Spinner size={15} />}
            {submitting ? "Submitting…" : "Analyze this area"}
          </button>
          <p className="mt-2 text-center text-[11px] leading-4 text-muted">
            The 12 agents run on real NASA satellite observations for the selected area and period.
          </p>
        </div>
      </div>

      {/* drawing hint overlay */}
      {drawMode && (
        <div className="no-print pointer-events-none absolute bottom-4 left-1/2 z-[1000] -translate-x-1/2 rounded-full border border-line bg-white/95 px-4 py-2 text-[12.5px] text-paper shadow-card">
          <Crosshair size={13} className="mr-1.5 inline text-accent" />
          {firstCorner ? "Click the opposite corner of the rectangle" : "Click the first corner on the map"}
        </div>
      )}
    </div>
  );
}
