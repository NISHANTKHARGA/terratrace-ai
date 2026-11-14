// Shared Leaflet map: light CARTO basemap, lat/lon readout, fit-to-bounds.

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { MapContainer, TileLayer, useMap, useMapEvents, ZoomControl } from "react-leaflet";
import type { LatLngBoundsExpression, LeafletMouseEvent } from "leaflet";
import { fmtCoord } from "../lib/geo";

export const LIGHT_TILES = "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png";
export const DARK_TILES = LIGHT_TILES;
export const DARK_ATTRIBUTION = "© OpenStreetMap contributors © CARTO";
export const NASA_ATTRIBUTION = "Imagery © NASA EOSDIS GIBS (MODIS Terra)";

/** Most recent day likely to have MODIS Terra true-color imagery on GIBS. */
export function nasaGibsDate(): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() - 1);
  return d.toISOString().slice(0, 10);
}

export function nasaGibsUrl(): string {
  return `https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/MODIS_Terra_CorrectedReflectance_TrueColor/default/${nasaGibsDate()}/GoogleMapsCompatible_Level9/{z}/{y}/{x}.jpeg`;
}

interface FitBoundsProps {
  bounds: LatLngBoundsExpression | null | undefined;
  fitKey: string;
}

function FitBounds({ bounds, fitKey }: FitBoundsProps) {
  const map = useMap();
  useEffect(() => {
    if (!bounds) return;
    try {
      map.fitBounds(bounds, { padding: [24, 24], animate: false });
    } catch {
      /* degenerate bounds — ignore */
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fitKey, bounds]);
  return null;
}

interface EventsProps {
  onClick?: (lat: number, lng: number, event: LeafletMouseEvent) => void;
  onCursor?: (pos: { lat: number; lng: number } | null) => void;
}

function Events({ onClick, onCursor }: EventsProps) {
  useMapEvents({
    click: (e) => onClick?.(e.latlng.lat, e.latlng.lng, e),
    mousemove: (e) => onCursor?.({ lat: e.latlng.lat, lng: e.latlng.lng }),
    mouseout: () => onCursor?.(null),
  });
  return null;
}

function Readout() {
  const map = useMap();
  const [cursor, setCursor] = useState<{ lat: number; lng: number } | null>(null);
  const [center, setCenter] = useState<{ lat: number; lng: number }>({ lat: 0, lng: 0 });
  const [zoom, setZoom] = useState<number>(map.getZoom());

  useMapEvents({
    mousemove: (e) => setCursor({ lat: e.latlng.lat, lng: e.latlng.lng }),
    mouseout: () => setCursor(null),
    moveend: () => {
      const c = map.getCenter();
      setCenter({ lat: c.lat, lng: c.lng });
    },
    zoomend: () => setZoom(map.getZoom()),
  });

  const shown = cursor ?? center;
  return (
    <div
      className="pointer-events-none absolute bottom-2 left-2 z-[1000] flex items-center gap-3 rounded-lg border border-line bg-white/92 px-3 py-1.5 font-mono text-[11px] tracking-wide text-paper/85 shadow-sm"
      style={{ zIndex: 1000 }}
    >
      <span>
        {fmtCoord(shown.lat, "lat")} {fmtCoord(shown.lng, "lng")}
      </span>
      <span className="text-muted">z{zoom}</span>
      <span className="text-muted">{cursor ? "cursor" : "center"}</span>
    </div>
  );
}

export interface MapCanvasProps {
  children?: ReactNode;
  /** Leaflet bounds to fit on mount / when fitKey changes. */
  bounds?: LatLngBoundsExpression | null;
  fitKey?: string;
  onClick?: (lat: number, lng: number, event: LeafletMouseEvent) => void;
  onCursor?: (pos: { lat: number; lng: number } | null) => void;
  className?: string;
  attribution?: string;
  minZoom?: number;
  maxBounds?: LatLngBoundsExpression | null;
  /** Starting basemap. Defaults to "nasa" (real NASA GIBS imagery). */
  basemap?: "nasa" | "light";
}

export default function MapCanvas({
  children,
  bounds,
  fitKey,
  onClick,
  onCursor,
  className = "",
  attribution,
  minZoom = 2,
  maxBounds = null,
  basemap: initialBasemap = "nasa",
}: MapCanvasProps) {
  const [basemap, setBasemap] = useState<"nasa" | "light">(initialBasemap);
  const autoKey = useMemo(() => JSON.stringify(bounds ?? null), [bounds]);
  const key = fitKey ?? autoKey;

  const tileUrl = basemap === "nasa" ? nasaGibsUrl() : LIGHT_TILES;
  const attr = attribution ?? (basemap === "nasa" ? NASA_ATTRIBUTION : DARK_ATTRIBUTION);

  return (
    <div className={`relative overflow-hidden ${className}`}>
      <MapContainer
        center={[18, 4]}
        zoom={2}
        minZoom={minZoom}
        maxBounds={maxBounds ?? undefined}
        maxBoundsViscosity={0.6}
        zoomControl={false}
        scrollWheelZoom
        className="h-full w-full"
        style={{ height: "100%", width: "100%" }}
      >
        <TileLayer url={tileUrl} attribution={attr} maxZoom={basemap === "nasa" ? 9 : 19} />
        <ZoomControl position="topright" />
        <FitBounds bounds={bounds} fitKey={key} />
        <Events onClick={onClick} onCursor={onCursor} />
        <Readout />
        {children}
      </MapContainer>
      {/* tiny basemap toggle */}
      <div className="no-print absolute left-2 top-2 z-[1000] flex overflow-hidden rounded-lg border border-white/40 bg-white/90 shadow-sm backdrop-blur">
        <button
          type="button"
          onClick={() => setBasemap("nasa")}
          className={`px-2.5 py-1 text-[11px] font-medium transition ${
            basemap === "nasa" ? "bg-accent text-white" : "text-slate-600 hover:bg-raised"
          }`}
        >
          NASA
        </button>
        <button
          type="button"
          onClick={() => setBasemap("light")}
          className={`px-2.5 py-1 text-[11px] font-medium transition ${
            basemap === "light" ? "bg-accent text-white" : "text-slate-600 hover:bg-raised"
          }`}
        >
          Light
        </button>
      </div>
    </div>
  );
}
