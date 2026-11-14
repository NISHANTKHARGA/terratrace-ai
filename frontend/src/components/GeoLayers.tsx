// Reusable vector layers for observation footprints and findings.

import { GeoJSON } from "react-leaflet";
import { CircleMarker, type LeafletMouseEvent } from "leaflet";
import type { Feature, FeatureCollection } from "../types";
import { featureFindingId, humanize } from "../lib/geo";
export const OBSERVATION_STYLE = {
  color: "#3E6FB0",
  weight: 1,
  opacity: 0.85,
  fillColor: "#3E6FB0",
  fillOpacity: 0.07,
};

export const CHANGE_POLYGON_STYLE = {
  color: "#E0A458",
  weight: 1.5,
  opacity: 0.9,
  fillColor: "#E0A458",
  fillOpacity: 0.14,
};

function propString(props: Record<string, unknown> | null | undefined, ...keys: string[]): string | null {
  if (!props) return null;
  for (const key of keys) {
    const value = props[key];
    if (typeof value === "string" && value) return value;
    if (typeof value === "number") return String(value);
  }
  return null;
}

interface ObservationLayerProps {
  data: FeatureCollection;
  layerKey: string;
  visible: boolean;
}

/** Observation footprints (blue outlines). Non-interactive apart from tooltips. */
export function ObservationLayer({ data, layerKey, visible }: ObservationLayerProps) {
  if (!visible) return null;
  return (
    <GeoJSON
      key={`obs-${layerKey}`}
      data={data}
      style={() => OBSERVATION_STYLE}
      onEachFeature={(feature, layer) => {
        const props = (feature.properties ?? {}) as Record<string, unknown>;
        const label = [
          propString(props, "platform", "mission"),
          propString(props, "product_type"),
          propString(props, "datetime", "date"),
        ]
          .filter(Boolean)
          .join(" · ");
        if (label) layer.bindTooltip(label, { sticky: true, direction: "top" });
      }}
    />
  );
}

interface FindingLayerProps {
  data: FeatureCollection;
  layerKey: string;
  visible: boolean;
  /** Called when a feature is clicked (marker or polygon). */
  onSelect?: (feature: Feature) => void;
  /** Draw point features as circle markers (default true). */
  pointsAsMarkers?: boolean;
}

/**
 * Findings layer: point features become cyan circle markers, polygon features
 * are drawn as amber "change region" outlines.
 */
export function FindingLayer({
  data,
  layerKey,
  visible,
  onSelect,
  pointsAsMarkers = true,
}: FindingLayerProps) {
  if (!visible) return null;
  return (
    <GeoJSON
      key={`find-${layerKey}`}
      data={data}
      style={() => CHANGE_POLYGON_STYLE}
      pointToLayer={
        pointsAsMarkers
          ? (feature, latlng) => {
              const marker = new CircleMarker(latlng, {
                radius: 5,
                color: "#0B1220",
                weight: 1,
                fillColor: "#5FD0D6",
                fillOpacity: 0.95,
              });
              const props = (feature.properties ?? {}) as Record<string, unknown>;
              const label = propString(props, "title", "name");
              if (label) marker.bindTooltip(label, { direction: "top", sticky: true });
              return marker;
            }
          : undefined
      }
      onEachFeature={(feature, layer) => {
        if (!onSelect) return;
        layer.on("click", (e: LeafletMouseEvent) => {
          e.originalEvent?.stopPropagation();
          onSelect(feature);
        });
      }}
    />
  );
}

/** Analysis/discovery bounding regions supplied by the map API. */
export function AnalysisRegionLayer({ data, layerKey, visible }: ObservationLayerProps) {
  if (!visible) return null;
  return (
    <GeoJSON
      key={`analysis-${layerKey}`}
      data={data}
      style={() => ({
        color: "#0F766E",
        weight: 1.2,
        opacity: 0.9,
        fillColor: "#0F766E",
        fillOpacity: 0.05,
      })}
      onEachFeature={(feature, layer) => {
        const props = (feature.properties ?? {}) as Record<string, unknown>;
        const label = [
          propString(props, "label"),
          propString(props, "kind"),
          propString(props, "status"),
        ]
          .filter(Boolean)
          .join(" · ");
        if (label) layer.bindTooltip(label, { sticky: true, direction: "top" });
      }}
    />
  );
}

/** Compact human-readable label for a finding feature's properties. */
export function findingFeatureLabel(feature: Feature): string {
  const props = (feature.properties ?? {}) as Record<string, unknown>;
  return (
    propString(props, "title", "name") ??
    (propString(props, "category") ? humanize(propString(props, "category")!) : null) ??
    featureFindingId(feature) ??
    "Unnamed feature"
  );
}
