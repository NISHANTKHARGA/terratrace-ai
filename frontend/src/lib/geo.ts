// Geometry / formatting helpers shared across pages.

import type { GeoJSON } from "../types";

export type LatLon = [number, number]; // [lat, lng]

/** Parse a "w,s,e,n" bbox string into a tuple, or null when invalid. */
export function parseBbox(text: string): [number, number, number, number] | null {
  const parts = text
    .split(/[\s,;]+/)
    .map((p) => p.trim())
    .filter(Boolean)
    .map(Number);
  if (parts.length !== 4 || parts.some((n) => Number.isNaN(n))) return null;
  const [w, s, e, n] = parts;
  if (s < -90 || n > 90 || w < -180 || e > 180 || s > n || w > e) return null;
  return [w, s, e, n];
}

/** bbox [w,s,e,n] → leaflet bounds [[south, west], [north, east]]. */
export function bboxToBounds(bbox: number[]): [[number, number], [number, number]] {
  const [w, s, e, n] = bbox;
  return [
    [s, w],
    [n, e],
  ];
}

/** Recursively walk GeoJSON coordinates and return the WGS84 extent. */
export function geojsonExtent(
  fc: GeoJSON.FeatureCollection | null | undefined
): [[number, number], [number, number]] | null {
  if (!fc || !Array.isArray(fc.features)) return null;
  let minLat = Infinity,
    minLng = Infinity,
    maxLat = -Infinity,
    maxLng = -Infinity;

  const visit = (node: unknown): void => {
    if (!Array.isArray(node)) return;
    if (node.length >= 2 && typeof node[0] === "number" && typeof node[1] === "number") {
      const lng = node[0];
      const lat = node[1];
      if (lat < minLat) minLat = lat;
      if (lat > maxLat) maxLat = lat;
      if (lng < minLng) minLng = lng;
      if (lng > maxLng) maxLng = lng;
      return;
    }
    node.forEach(visit);
  };

  const visitGeometry = (geometry: GeoJSON.Geometry): void => {
    if ("coordinates" in geometry) visit(geometry.coordinates);
    else if ("geometries" in geometry) geometry.geometries.forEach(visitGeometry);
  };

  for (const feature of fc.features) {
    if (feature.geometry) visitGeometry(feature.geometry);
  }
  if (!Number.isFinite(minLat)) return null;
  return [
    [minLat, minLng],
    [maxLat, maxLng],
  ];
}

/** Read a stable id off a GeoJSON feature (feature.id or common property names). */
export function featureFindingId(
  feature: GeoJSON.Feature
): string | null {
  const props = (feature.properties ?? {}) as Record<string, unknown>;
  const candidate =
    (typeof feature.id === "string" && feature.id) ||
    (typeof props.id === "string" && props.id) ||
    (typeof props.finding_id === "string" && props.finding_id) ||
    null;
  return candidate;
}

export function isGeometryType(
  geometry: GeoJSON.Geometry | null | undefined,
  type: GeoJSON.Geometry["type"]
): boolean {
  return geometry?.type === type;
}

export function fmtNum(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  });
}

export function fmtPct01(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "not measured";
  return `${(value * 100).toFixed(1)}%`;
}

export function fmtCoord(value: number, axis: "lat" | "lng"): string {
  const hemi = axis === "lat" ? (value >= 0 ? "N" : "S") : value >= 0 ? "E" : "W";
  return `${Math.abs(value).toFixed(4)}°${hemi}`;
}

export function fmtDate(iso: string | null | undefined, withTime = false): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const date = d.toISOString().slice(0, 10);
  if (!withTime) return date;
  return `${date} ${d.toISOString().slice(11, 19)}Z`;
}

export function fmtDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || Number.isNaN(ms)) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  const min = Math.floor(ms / 60_000);
  const sec = Math.round((ms % 60_000) / 1000);
  return `${min}m ${sec}s`;
}

export function fmtBytesMb(mb: number | null | undefined): string {
  if (mb === null || mb === undefined) return "—";
  if (mb < 1024) return `${mb.toFixed(1)} MB`;
  return `${(mb / 1024).toFixed(2)} GB`;
}

/** Human readable version of an enum-ish string: "GROUND_DEFORMATION" → "Ground deformation". */
export function humanize(value: string): string {
  return value
    .toLowerCase()
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export function truncate(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

/** Group findings by calendar month (YYYY-MM) in chronological order. */
export function groupByMonth(dates: (string | null)[]): { month: string; count: number }[] {
  const counts = new Map<string, number>();
  for (const iso of dates) {
    if (!iso) continue;
    const month = iso.slice(0, 7);
    if (!/^\d{4}-\d{2}$/.test(month)) continue;
    counts.set(month, (counts.get(month) ?? 0) + 1);
  }
  return [...counts.entries()]
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([month, count]) => ({ month, count }));
}

/** Trigger a client-side file download of the given text content. */
export function downloadText(filename: string, content: string, mime: string): void {
  const blob = new Blob([content], { type: mime });
  const href = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = href;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(href);
}
