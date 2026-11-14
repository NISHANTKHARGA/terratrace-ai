# TerraTrace AI — Backend API Contract (v1)

Base URL: `http://127.0.0.1:8000` (dev). All endpoints are JSON unless stated.
Errors: `{ "error": { "code": string, "message": string, "detail"?: any } }` with proper HTTP status.
Pagination: `?page=1&page_size=50` → `{ "items": T[], "page": number, "page_size": number, "total": number }`.

Geometry convention: GeoJSON, WGS84 (EPSG:4326). Areas in square kilometres unless stated.

---

## Types

```ts
type SourceStatus = "operational" | "degraded" | "requires_credentials" | "unavailable" | "unknown";

interface DataSourceStatus {
  id: string;                 // "nasa_cmr" | "planetary_computer" | "earth_search" | "copernicus_dataspace" | "earthdata_login"
  name: string;               // "NASA Earthdata CMR"
  description: string;
  provider: string;           // "NASA" | "Microsoft" | "AWS/Element84" | "ESA/Copernicus"
  status: SourceStatus;
  detail: string;             // human readable reason, e.g. "Anonymous metadata access OK"
  checked_at: string | null;  // ISO8601
  auth_required: boolean;
}

interface HealthResponse {
  status: "ok" | "degraded";
  version: string;
  time: string;
  database: "ok" | "error";
  sources: DataSourceStatus[];
  counts: { observations: number; findings: number; jobs: number; agents: number };
}

type MissionId = "NISAR" | "SENTINEL-1" | "OPERA" | "OTHER";

interface Observation {
  id: string;                 // internal stable id (sha1 of provider+granule id)
  provider_id: string;        // native identifier (e.g. CMR concept-id / granule id / STAC id)
  mission: MissionId;         // NISAR | SENTINEL-1 | OPERA | OTHER
  platform: string;           // "NISAR", "Sentinel-1A", ...
  source: string;             // connector id that produced it
  product_type: string;       // "L1_RSLC", "GRD", "RTC-S1", "DSWx-S1", ...
  processing_level: string;   // "L1" | "L2" | "L3"
  datetime: string;           // acquisition start ISO8601
  datetime_end: string | null;
  polarizations: string[];    // ["VV","VH"] or ["HH","HV"]
  orbit_direction: string | null;  // "ASCENDING" | "DESCENDING" | null
  bbox: number[] | null;      // [west, south, east, north]
  footprint: GeoJSON.Polygon | null;
  url: string | null;         // primary download/landing url
  browse_url: string | null;  // quicklook image url if any
  requires_credentials: boolean;
  size_mb: number | null;
  quality: {
    valid_coverage: number | null;   // 0..1 inside requested bbox
    notes: string[];
  };
}

interface ObservationListResponse { items: Observation[]; page: number; page_size: number; total: number; }
```

```ts
// POST /api/analysis
interface AnalysisRequest {
  bbox?: [number, number, number, number];          // west,south,east,north
  polygon?: GeoJSON.Polygon;                        // alternative to bbox
  start: string;                                    // ISO date
  end: string;                                      // ISO date
  label?: string;                                   // optional user label
  max_observations?: number;                        // default 6
  include_browse?: boolean;                         // fetch quicklook pngs (default true)
  source_preference?: ("planetary_computer" | "nasa_cmr" | "earth_search" | "copernicus_dataspace")[];
}

type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";

interface AgentDecision {
  agent_id: string;
  agent_name: string;
  selected: boolean;
  reason: string;                 // why selected/skipped (machine-readable reason code + text)
  reason_code: string;            // e.g. "MULTI_DATE_OVERLAP", "NO_WATER_SENSING_POL", "SINGLE_DATE_ONLY"
}

interface OrchestrationStep {
  step: number;
  name: string;                   // "global_data_scout" | "sar_processing" | "change_detection" | "agent_routing" | "agent_execution" | "evidence_validation" | "finding_publisher"
  status: "pending" | "running" | "succeeded" | "failed" | "skipped";
  started_at?: string;
  ended_at?: string;
  detail?: string;
}

interface AgentRunRecord {
  agent_id: string;
  status: "succeeded" | "failed" | "skipped" | "timeout" | "no_candidates";
  duration_ms: number;
  model_version: string;
  datasets: string[];
  candidates: number;
  log: string[];                  // structured log lines
  error?: string;
  reason?: string;                // agent's own explanation (e.g. why no candidates)
}

interface AnalysisJob {
  id: string;
  label: string | null;
  status: JobStatus;
  created_at: string;
  started_at: string | null;
  ended_at: string | null;
  request: AnalysisRequest;
  bbox: number[];
  progress: number;               // 0..1
  current_stage: string | null;
  steps: OrchestrationStep[];
  observations: Observation[];        // discovered (possibly truncated to relevant subset)
  agents_selected: AgentDecision[];
  agent_runs: AgentRunRecord[];
  findings: string[];                 // finding ids produced
  error: string | null;
  logs: string[];                     // global job log lines
  metrics: {
    change_pixels: number | null;
    changed_area_km2: number | null;
    overlap_ratio: number | null;
    processing_ms: number | null;
  } | null;
}
```

```ts
type FindingCategory =
  | "FLOOD_INUNDATION" | "WETLAND_WATER" | "FOREST_LOSS" | "WILDFIRE_BURNED"
  | "GROUND_DEFORMATION" | "GLACIER_CRYOSPHERE" | "LANDSLIDE_SLOPE"
  | "AGRICULTURE" | "URBAN_INFRASTRUCTURE" | "MINING_DISTURBANCE"
  | "COASTAL_SHORELINE" | "UNCASSIFIED_CHANGE";

type VerificationStatus =
  | "candidate_detected" | "under_investigation" | "corroborated"
  | "requires_verification" | "insufficient_data" | "rejected_poor_quality";

interface FindingEvidence {
  summary: string;                     // plain language explanation
  measurements: Record<string, number | string | null>;  // e.g. {"mean_log_ratio_db": -6.2}
  supporting: string[];                // evidence statements
  conflicting: string[];               // conflict statements (may be empty)
  uncertainty: string;                 // description of uncertainty sources
  limitations: string[];
  method: { name: string; version: string };
  persistence: { dates_supporting: string[]; days_between: number | null; persistent: boolean };
  context_datasets: { id: string; note: string; status: "available" | "not_configured" | "unavailable" }[];
}

interface Finding {
  id: string;
  title: string;
  category: FindingCategory;
  agent_id: string;
  job_id: string | null;
  location: { name: string | null; bbox: number[]; centroid: [number, number] };
  geometry: GeoJSON.Polygon | MultiPolygon | null;   // change region polygon
  geometry_source: "raster_vectorize" | "observation_footprint" | "point";
  observation_dates: [string, string] | [string, string, string];
  sources: { mission: MissionId; provider_id: string; source: string; product_type: string }[];
  area_km2: number;
  detection_confidence: number;        // 0..1 heuristic score (NOT a probability)
  evidence_completeness: number;       // 0..1
  data_quality: number;                // 0..1
  severity: "low" | "moderate" | "high" | "unknown";
  verification_status: VerificationStatus;
  first_observed: string | null;
  method: string;
  model_version: string;
  created_at: string;
  updated_at: string;
  assets: { before_png: string | null; after_png: string | null; change_png: string | null };  // API-relative urls
  explanation: string;
}

interface FindingListResponse { items: Finding[]; page: number; page_size: number; total: number; }

interface FindingDetail extends Finding {
  evidence: FindingEvidence;
  agent: { id: string; name: string; status: string };
  job: { id: string; created_at: string; status: string } | null;
  source_observations: Observation[];
}
```

```ts
type AgentStatus = "operational" | "experimental" | "not_configured" | "insufficient_data" | "failed";

interface AgentSummary {
  id: string;                    // "flood" | "wetlands" | ... | "unknown_change"
  name: string;                  // "Flood & Inundation Intelligence"
  ordinal: number;               // 1..12
  purpose: string;
  status: AgentStatus;
  status_reason: string;         // honest reason, e.g. "Baseline operational on calibrated S1 RTC backscatter; no labelled flood dataset configured"
  model_version: string;
  baseline_method: string;       // "dB log-ratio + Otsu water segmentation"
  capabilities: string[];
  datasets: { id: string; name: string; status: "registered" | "available" | "not_configured" | "interface_only"; note: string }[];
  evaluation: { metric: string; value: number | null; note: string }[];  // value null = never measured
  last_execution: { at: string; job_id: string; duration_ms: number; candidates: number; status: string } | null;
  supported_inputs: string[];    // ["S1_RTC_VV_VH", "S1_GRD", "BROWSE_QUICKLOOK", ...]
}

interface AgentDetail extends AgentSummary {
  config: Record<string, unknown>;
  output_schema: Record<string, string>;   // field -> description
  processing_logs_last_run: string[];
  known_limitations: string[];
}
```

```ts
interface MapLayerDef {
  id: string;                    // "observation_footprints" | "findings" | "change_polygons" | "analysis_regions"
  name: string;
  type: "vector" | "raster" | "geojson_url";
  default_on: boolean;
  endpoint?: string;             // for geojson_url layers
}

interface MapLayersResponse {
  layers: MapLayerDef[];
  findings_geojson: GeoJSON.FeatureCollection;         // points/polygons for markers
  observations_geojson: GeoJSON.FeatureCollection;     // footprints (recent, capped)
  change_polygons_geojson: GeoJSON.FeatureCollection;  // vectorised change-mask artifacts
  analysis_regions_geojson: GeoJSON.FeatureCollection; // actual analysis/discovery regions
  basemap_attribution: string;
}

interface DatasetInfo {
  id: string;                    // "sen1floods11", "jrc_global_surface_water", "global_forest_change", ...
  name: string;
  agent_ids: string[];
  status: "available" | "registered" | "interface_only" | "not_configured";
  access: string;                // how to access
  url: string | null;
  note: string;
}

interface ModelInfo {
  id: string;                    // "{agent_id}:{model_id}"
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

interface TrainingRun {
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
```

---

## Endpoints

| Method | Path | Notes |
|---|---|---|
| GET | `/api/health` | `HealthResponse` |
| GET | `/api/datasets` | `{ items: DatasetInfo[] }` |
| GET | `/api/observations?bbox&w,s,e,n&start&end&mission&source&page&page_size` | `ObservationListResponse` |
| GET | `/api/observations/{id}` | `Observation` |
| GET | `/api/observations/{id}/browse` | returns `image/png` quicklook (proxied, cached) |
| POST | `/api/analysis` | `AnalysisRequest` → `AnalysisJob` (202) |
| GET | `/api/analysis` | `{ items: AnalysisJob[] }` (history, newest first) |
| GET | `/api/analysis/{job_id}` | `AnalysisJob` (poll this for progress) |
| POST | `/api/analysis/{job_id}/cancel` | `{ status }` |
| GET | `/api/agents` | `{ items: AgentSummary[] }` |
| GET | `/api/agents/{agent_id}` | `AgentDetail` |
| GET | `/api/findings?page&page_size&category&status&job_id&bbox` | `FindingListResponse` |
| GET | `/api/findings/{finding_id}` | `FindingDetail` |
| GET | `/api/findings/{finding_id}/evidence` | `{ finding_id, evidence: FindingEvidence }` |
| GET | `/api/findings/{finding_id}/export.geojson` | `application/geo+json` |
| GET | `/api/findings/{finding_id}/report` | `text/html` report |
| GET | `/api/map-layers` | `MapLayersResponse` |
| GET | `/api/map-layers/findings.geojson` | findings as `application/geo+json` |
| GET | `/api/map-layers/change.geojson` | vectorised change-mask polygons as `application/geo+json` |
| GET | `/api/map-layers/analysis.geojson` | analysis/discovery regions as `application/geo+json` |
| GET | `/api/history?page&page_size` | `{ items: HistoryEntry[] }` where `HistoryEntry = { kind: "analysis"|"discovery", id, label, status, created_at, findings_count, bbox }` |
| GET | `/api/models` | `{ items: ModelInfo[] }` |
| GET | `/api/models/{model_id}` | `ModelInfo` |
| GET | `/api/training/runs` | `{ items: TrainingRun[] }` |
| GET | `/api/sources` | `{ items: DataSourceStatus[] }` |
| POST | `/api/sources/{source_id}/check` | re-probe source, returns `DataSourceStatus` |
| POST | `/api/discovery/run` | global discovery: `{ bbox?, start?, end?, limit? }` → `{ job_id, observations }` (metadata-only, no rasters) |
| GET | `/api/jobs/{job_id}/assets/{asset_name}` | serves derived PNG/GeoJSON artifacts of a job (e.g. `before.png`, `after.png`, `change.png`, `change.geojson`) |

### Polling pattern for the frontend
`POST /api/analysis` → returns job with `status:"queued"`; poll `GET /api/analysis/{id}` every 1200 ms until `succeeded|failed|cancelled`. Progress is `progress` (0..1) and `current_stage`.

### Asset URLs inside findings
`Finding.assets` fields are API-relative strings like `/api/jobs/{job_id}/assets/before.png`. Prefix with the API base URL.

---

## Reason codes used by `AgentDecision.reason_code`

`MULTI_DATE_OVERLAP`, `SINGLE_DATE_ONLY`, `SUFFICIENT_VALID_PIXELS`, `INSUFFICIENT_VALID_PIXELS`,
`NO_OVERLAP`, `UNSUPPORTED_PRODUCT`, `NEEDS_INSAR`, `NEEDS_CONTEXT_DATASET`,
`ALWAYS_ELIGIBLE_UNKNOWN_SCREEN`, `USER_EXCLUDED`, `EARLIER_FAILURE`.

## Categories ↔ agents
`flood→FLOOD_INUNDATION`, `wetlands→WETLAND_WATER`, `forest→FOREST_LOSS`, `wildfire→WILDFIRE_BURNED`,
`deformation→GROUND_DEFORMATION`, `glacier→GLACIER_CRYOSPHERE`, `landslide→LANDSLIDE_SLOPE`,
`agriculture→AGRICULTURE`, `urban→URBAN_INFRASTRUCTURE`, `mining→MINING_DISTURBANCE`,
`coastal→COASTAL_SHORELINE`, `unknown_change→UNCASSIFIED_CHANGE`.
