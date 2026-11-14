// TerraTrace AI — TypeScript types.
// Hand-written mirror of `docs/API_CONTRACT.md` (v1). Keep in sync with the contract.

import type * as GeoJSON from "geojson";

export type { GeoJSON };

/** Convenience aliases for GeoJSON structural types used across the app. */
export type Feature = GeoJSON.Feature;
export type FeatureCollection = GeoJSON.FeatureCollection;
export type Geometry = GeoJSON.Geometry;
export type Position = GeoJSON.Position;

/* ------------------------------------------------------------------ sources */

export type SourceStatus =
  | "operational"
  | "degraded"
  | "requires_credentials"
  | "unavailable"
  | "unknown";

export interface DataSourceStatus {
  id: string;
  name: string;
  description: string;
  provider: string;
  status: SourceStatus;
  detail: string;
  checked_at: string | null;
  auth_required: boolean;
}

export interface HealthResponse {
  status: "ok" | "degraded";
  version: string;
  time: string;
  database: "ok" | "error";
  sources: DataSourceStatus[];
  counts: { observations: number; findings: number; jobs: number; agents: number };
}

/* ------------------------------------------------------------- observations */

export type MissionId = "NISAR" | "SENTINEL-1" | "OPERA" | "UAVSAR" | "OTHER";

export interface Observation {
  id: string;
  provider_id: string;
  mission: MissionId;
  platform: string;
  source: string;
  product_type: string;
  processing_level: string;
  datetime: string;
  datetime_end: string | null;
  polarizations: string[];
  orbit_direction: string | null;
  bbox: number[] | null;
  footprint: GeoJSON.Polygon | null;
  url: string | null;
  browse_url: string | null;
  requires_credentials: boolean;
  size_mb: number | null;
  quality: {
    valid_coverage: number | null;
    notes: string[];
  };
}

export interface ObservationListResponse {
  items: Observation[];
  page: number;
  page_size: number;
  total: number;
}

/* ----------------------------------------------------------------- analysis */

export interface AnalysisRequest {
  bbox?: [number, number, number, number];
  polygon?: GeoJSON.Polygon;
  start: string;
  end: string;
  label?: string;
  max_observations?: number;
  include_browse?: boolean;
  source_preference?: (
    | "planetary_computer"
    | "nasa_cmr"
    | "earth_search"
    | "copernicus_dataspace"
  )[];
}

export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";

export interface AgentDecision {
  agent_id: string;
  agent_name: string;
  selected: boolean;
  reason: string;
  reason_code: string;
}

export interface OrchestrationStep {
  step: number;
  name: string;
  status: "pending" | "running" | "succeeded" | "failed" | "skipped";
  started_at?: string;
  ended_at?: string;
  detail?: string;
}

export interface AgentRunRecord {
  agent_id: string;
  status: "succeeded" | "failed" | "skipped" | "timeout" | "no_candidates";
  duration_ms: number;
  model_version: string;
  datasets: string[];
  candidates: number;
  log: string[];
  error?: string;
  reason?: string;
}

export interface AnalysisJob {
  id: string;
  label: string | null;
  status: JobStatus;
  created_at: string;
  started_at: string | null;
  ended_at: string | null;
  request: AnalysisRequest;
  bbox: number[];
  progress: number;
  current_stage: string | null;
  steps: OrchestrationStep[];
  observations: Observation[];
  agents_selected: AgentDecision[];
  agent_runs: AgentRunRecord[];
  findings: string[];
  error: string | null;
  logs: string[];
  metrics: {
    change_pixels: number | null;
    changed_area_km2: number | null;
    overlap_ratio: number | null;
    processing_ms: number | null;
  } | null;
}

/* ----------------------------------------------------------------- findings */

export type FindingCategory =
  | "FLOOD_INUNDATION"
  | "WETLAND_WATER"
  | "FOREST_LOSS"
  | "WILDFIRE_BURNED"
  | "GROUND_DEFORMATION"
  | "GLACIER_CRYOSPHERE"
  | "LANDSLIDE_SLOPE"
  | "AGRICULTURE"
  | "URBAN_INFRASTRUCTURE"
  | "MINING_DISTURBANCE"
  | "COASTAL_SHORELINE"
  | "UNCASSIFIED_CHANGE";

export type VerificationStatus =
  | "candidate_detected"
  | "under_investigation"
  | "corroborated"
  | "requires_verification"
  | "insufficient_data"
  | "rejected_poor_quality";

export interface FindingEvidence {
  summary: string;
  measurements: Record<string, number | string | null>;
  supporting: string[];
  conflicting: string[];
  uncertainty: string;
  limitations: string[];
  method: { name: string; version: string };
  persistence: {
    dates_supporting: string[];
    days_between: number | null;
    persistent: boolean;
  };
  context_datasets: {
    id: string;
    note: string;
    status: "available" | "not_configured" | "unavailable";
  }[];
}

export interface Finding {
  id: string;
  title: string;
  category: FindingCategory;
  agent_id: string;
  job_id: string | null;
  location: { name: string | null; bbox: number[]; centroid: [number, number] };
  geometry: GeoJSON.Polygon | GeoJSON.MultiPolygon | null;
  geometry_source: "raster_vectorize" | "observation_footprint" | "point";
  observation_dates: string[];
  sources: {
    mission: MissionId;
    provider_id: string;
    source: string;
    product_type: string;
  }[];
  area_km2: number;
  detection_confidence: number;
  evidence_completeness: number;
  data_quality: number;
  severity: "low" | "moderate" | "high" | "unknown";
  verification_status: VerificationStatus;
  first_observed: string | null;
  method: string;
  model_version: string;
  created_at: string;
  updated_at: string;
  assets: { before_png: string | null; after_png: string | null; change_png: string | null };
  explanation: string;
}

export interface FindingListResponse {
  items: Finding[];
  page: number;
  page_size: number;
  total: number;
}

export interface FindingDetail extends Finding {
  evidence: FindingEvidence;
  agent: { id: string; name: string; status: string };
  job: { id: string; created_at: string; status: string } | null;
  source_observations: Observation[];
}

/* ------------------------------------------------------------------- agents */

export type AgentStatus =
  | "operational"
  | "experimental"
  | "not_configured"
  | "insufficient_data"
  | "failed";

export interface AgentSummary {
  id: string;
  name: string;
  ordinal: number;
  purpose: string;
  status: AgentStatus;
  status_reason: string;
  model_version: string;
  baseline_method: string;
  capabilities: string[];
  datasets: {
    id: string;
    name: string;
    status: "registered" | "available" | "not_configured" | "interface_only";
    note: string;
  }[];
  evaluation: { metric: string; value: number | null; note: string }[];
  last_execution: {
    at: string;
    job_id: string;
    duration_ms: number;
    candidates: number;
    status: string;
  } | null;
  supported_inputs: string[];
}

export interface AgentDetail extends AgentSummary {
  config: Record<string, unknown>;
  output_schema: Record<string, string>;
  processing_logs_last_run: string[];
  known_limitations: string[];
}

/* ------------------------------------------------------------------- map UI */

export interface MapLayerDef {
  id: string;
  name: string;
  type: "vector" | "raster" | "geojson_url";
  default_on: boolean;
  endpoint?: string;
}

export interface MapLayersResponse {
  layers: MapLayerDef[];
  findings_geojson: GeoJSON.FeatureCollection;
  observations_geojson: GeoJSON.FeatureCollection;
  change_polygons_geojson: GeoJSON.FeatureCollection;
  analysis_regions_geojson: GeoJSON.FeatureCollection;
  basemap_attribution: string;
}

/* ---------------------------------------------------------------- datasets */

export interface DatasetInfo {
  id: string;
  name: string;
  agent_ids: string[];
  status: "available" | "registered" | "interface_only" | "not_configured";
  access: string;
  url: string | null;
  note: string;
}

/* ------------------------------------------------------------------ models */

export interface ModelInfo {
  id: string;
  agent_id: string;
  name: string;
  kind: "baseline_algorithm" | "trained_model" | "pretrained_adapter";
  version: string;
  status: "active" | "candidate" | "untrained" | "experimental";
  dataset_ids: string[];
  metrics: { name: string; value: number | null; split: string | null }[];
  checkpoint_path: string | null;
  trained_at: string | null;
  sample_count: number | null;
  limitations: string[];
}

export interface TrainingRun {
  id: string;
  agent_id: string;
  model_id: string;
  status: "completed" | "failed" | "registered_only";
  started_at: string;
  ended_at: string | null;
  dataset_ids: string[];
  config: Record<string, unknown>;
  metrics: Record<string, number>;
  notes: string;
}

/* ----------------------------------------------------------------- history */

export interface HistoryEntry {
  kind: "analysis" | "discovery";
  id: string;
  label: string;
  status: string;
  created_at: string;
  findings_count: number;
  bbox: number[];
}

/* ------------------------------------------------------------- discovery run */

export interface DiscoveryRunResponse {
  job_id: string;
  observations: Observation[];
}

/* --------------------------------------------------------------- pagination */

export interface Paginated<T> {
  items: T[];
  page: number;
  page_size: number;
  total: number;
}
