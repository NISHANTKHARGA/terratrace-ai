// TEMPORARY mock backend for manual frontend verification.
// DELETE THIS FILE BEFORE FINISHING — the shipped app must call only the real API.
import http from "node:http";

const PORT = Number(process.env.PORT ?? 8123);

const agents = [
  ["flood", "Flood & Inundation Intelligence", 1, "operational"],
  ["wetlands", "Wetland Water Intelligence", 2, "operational"],
  ["forest", "Forest Loss Intelligence", 3, "experimental"],
  ["wildfire", "Wildfire Burn Intelligence", 4, "operational"],
  ["deformation", "Ground Deformation Intelligence", 5, "insufficient_data"],
  ["glacier", "Glacier & Cryosphere Intelligence", 6, "not_configured"],
  ["landslide", "Landslide & Slope Intelligence", 7, "experimental"],
  ["agriculture", "Agriculture Intelligence", 8, "operational"],
  ["urban", "Urban & Infrastructure Intelligence", 9, "experimental"],
  ["mining", "Mining Disturbance Intelligence", 10, "not_configured"],
  ["coastal", "Coastal & Shoreline Intelligence", 11, "insufficient_data"],
  ["unknown_change", "Unclassified Change Screen", 12, "operational"],
].map(([id, name, ordinal, status]) => ({
  id,
  name,
  ordinal,
  purpose: `Detects and characterises ${id}-related surface change from multi-temporal SAR and optical records.`,
  status,
  status_reason:
    status === "operational"
      ? "Baseline operational on calibrated S1 RTC backscatter; no labelled dataset configured."
      : status === "experimental"
        ? "Prototype threshold tuning only; evaluation pending labelled samples."
        : status === "not_configured"
          ? "No context dataset wired yet — agent registers capability but never runs."
          : "Insufficient valid acquisitions in the historical archive to score this agent.",
  model_version: `baseline-1.4.${ordinal}`,
  baseline_method: "dB log-ratio + Otsu segmentation",
  capabilities: ["change detection", "multi-date compositing", "confidence scoring"],
  datasets: [
    { id: "sen1floods11", name: "SEN1FLOODS11", status: "available", note: "labels used for evaluation" },
    { id: "jrc_global_surface_water", name: "JRC Global Surface Water", status: "registered", note: "context layer" },
  ],
  evaluation: [
    { metric: "f1_score", value: status === "not_configured" ? null : 0.71, note: "held-out split" },
    { metric: "precision", value: status === "insufficient_data" ? null : 0.83, note: "held-out split" },
    { metric: "recall", value: null, note: "never measured" },
  ],
  last_execution:
    status === "not_configured"
      ? null
      : {
          at: "2026-11-07T09:12:44Z",
          job_id: "job-2211",
          duration_ms: 4210,
          candidates: 3,
          status: "succeeded",
        },
  supported_inputs: ["S1_RTC_VV_VH", "S1_GRD", "BROWSE_QUICKLOOK"],
}));

const agentDetails = Object.fromEntries(
  agents.map((a) => [
    a.id,
    {
      ...a,
      config: { threshold: 0.62, min_valid_pixels: 400, window: 5, enable_context_datasets: true },
      output_schema: {
        change_mask: "binary raster of changed pixels",
        area_km2: "changed area in square kilometres",
        confidence: "heuristic score in [0,1], not a probability",
      },
      processing_logs_last_run: [
        "[scout] catalog query ok · 6 granules",
        "[router] eligible inputs: S1_RTC_VV_VH",
        "[exec] candidates: 3 · threshold 0.62",
      ],
      known_limitations: [
        "Single-pass geometry offsets can mimic deformation.",
        "No labelled flood dataset configured for calibration.",
      ],
    },
  ])
);

const findings = [
  {
    id: "fnd-88213",
    title: "Koshi river floodplain inundation expansion",
    category: "FLOOD_INUNDATION",
    agent_id: "flood",
    job_id: "job-2211",
    location: { name: "Koshi floodplain, Nepal", bbox: [86.85, 26.4, 87.35, 26.75], centroid: [26.57, 87.1] },
    geometry: {
      type: "Polygon",
      coordinates: [
        [
          [86.9, 26.45],
          [87.3, 26.45],
          [87.3, 26.7],
          [86.9, 26.7],
          [86.9, 26.45],
        ],
      ],
    },
    geometry_source: "raster_vectorize",
    observation_dates: ["2026-07-02T05:41:00Z", "2026-07-26T05:41:00Z"],
    sources: [
      { mission: "SENTINEL-1", provider_id: "S1A_IW_GRDH_1SDV_20260702", source: "planetary_computer", product_type: "GRD" },
    ],
    area_km2: 412.7,
    detection_confidence: 0.81,
    evidence_completeness: 0.74,
    data_quality: 0.9,
    severity: "high",
    verification_status: "corroborated",
    first_observed: "2026-07-02",
    method: "dB log-ratio + Otsu",
    model_version: "baseline-1.4.1",
    created_at: "2026-07-27T11:03:12Z",
    updated_at: "2026-08-02T08:15:00Z",
    assets: {
      before_png: "/api/jobs/job-2211/assets/before.png",
      after_png: "/api/jobs/job-2211/assets/after.png",
      change_png: "/api/jobs/job-2211/assets/change.png",
    },
    explanation:
      "Backscatter depression across 412 km² of the Koshi floodplain between the two acquisitions is consistent with open-water inundation; JRC surface water context agrees along the main channel.",
  },
  {
    id: "fnd-88199",
    title: "Tailings pond expansion, Mustang district",
    category: "MINING_DISTURBANCE",
    agent_id: "mining",
    job_id: "job-2209",
    location: { name: "Mustang, Nepal", bbox: [83.6, 29.1, 83.9, 29.35], centroid: [29.22, 83.75] },
    geometry: null,
    geometry_source: "point",
    observation_dates: ["2026-03-11T06:02:00Z", "2026-06-19T06:02:00Z"],
    sources: [
      { mission: "NISAR", provider_id: "NISAR_L1_RSLC_00311", source: "nasa_cmr", product_type: "L1_RSLC" },
    ],
    area_km2: 3.4,
    detection_confidence: 0.52,
    evidence_completeness: 0.4,
    data_quality: 0.66,
    severity: "moderate",
    verification_status: "requires_verification",
    first_observed: "2026-03-11",
    method: "coherence delta",
    model_version: "baseline-1.4.10",
    created_at: "2026-06-21T14:40:00Z",
    updated_at: "2026-06-21T14:40:00Z",
    assets: { before_png: null, after_png: null, change_png: null },
    explanation:
      "Persistent coherence loss over 100 days suggests continued earthworks; only two acquisitions available, so the record stays under investigation.",
  },
  {
    id: "fnd-88104",
    title: "Glacier terminus retreat, Khumbu",
    category: "GLACIER_CRYOSPHERE",
    agent_id: "glacier",
    job_id: null,
    location: { name: "Khumbu, Nepal", bbox: [86.75, 27.85, 86.95, 28.05], centroid: [27.95, 86.85] },
    geometry: null,
    geometry_source: "observation_footprint",
    observation_dates: ["2025-10-04T05:52:00Z", "2026-04-18T05:52:00Z"],
    sources: [
      { mission: "OPERA", provider_id: "OPERA_DSWX_S1_20260418", source: "earth_search", product_type: "DSWx-S1" },
    ],
    area_km2: 1.9,
    detection_confidence: 0.44,
    evidence_completeness: 0.35,
    data_quality: 0.58,
    severity: "low",
    verification_status: "under_investigation",
    first_observed: "2025-10-04",
    method: "NDSW threshold",
    model_version: "baseline-1.4.6",
    created_at: "2026-04-20T07:11:00Z",
    updated_at: "2026-05-01T07:11:00Z",
    assets: {
      before_png: "/api/jobs/job-2209/assets/before.png",
      after_png: "/api/jobs/job-2209/assets/after.png",
      change_png: null,
    },
    explanation: "Seasonal snow-line migration detected; not yet separated from annual snow variability.",
  },
];

const evidenceFor = (f) => ({
  summary: "Multi-temporal backscatter comparison indicates a consistent surface change inside the outlined region.",
  measurements: { mean_log_ratio_db: -6.2, valid_pixel_ratio: 0.87, changed_area_km2: f.area_km2 },
  supporting: ["Change persists across both dates.", "Direction of change matches the expected physical signature."],
  conflicting: ["Cloud-free optical browse unavailable for the second date."],
  uncertainty: "Speckle and wind-roughened water can depress backscatter without standing water.",
  limitations: ["Single sensor pair.", "No ground truth available."],
  method: { name: f.method, version: f.model_version },
  persistence: { dates_supporting: f.observation_dates, days_between: 24, persistent: true },
  context_datasets: [
    { id: "jrc_global_surface_water", note: "context layer", status: "available" },
    { id: "global_foreorest_change", note: "not wired", status: "not_configured" },
  ],
});

const observations = Array.from({ length: 9 }, (_, i) => ({
  id: `obs-${1000 + i}`,
  provider_id: `S1A_IW_GRDH_1SDV_2026070${i}T0541`,
  mission: ["SENTINEL-1", "NISAR", "OPERA", "OTHER"][i % 4],
  platform: i % 2 ? "Sentinel-1A" : "NISAR",
  source: ["planetary_computer", "nasa_cmr", "earth_search", "copernicus_dataspace"][i % 4],
  product_type: ["GRD", "L1_RSLC", "RTC-S1", "DSWx-S1"][i % 4],
  processing_level: i % 2 ? "L1" : "L2",
  datetime: `2026-0${(i % 6) + 1}-1${i}T05:41:00Z`,
  datetime_end: null,
  polarizations: i % 2 ? ["VV", "VH"] : ["HH", "HV"],
  orbit_direction: i % 2 ? "ASCENDING" : "DESCENDING",
  bbox: [86.5 + i * 0.05, 26.3 + i * 0.03, 86.9 + i * 0.05, 26.6 + i * 0.03],
  footprint: {
    type: "Polygon",
    coordinates: [
      [
        [86.5 + i * 0.05, 26.3 + i * 0.03],
        [86.9 + i * 0.05, 26.3 + i * 0.03],
        [86.9 + i * 0.05, 26.6 + i * 0.03],
        [86.5 + i * 0.05, 26.6 + i * 0.03],
        [86.5 + i * 0.05, 26.3 + i * 0.03],
      ],
    ],
  },
  url: "https://example.invalid/product",
  browse_url: null,
  requires_credentials: i % 3 === 0,
  size_mb: 800 + i * 40,
  quality: { valid_coverage: 0.6 + (i % 4) * 0.1, notes: i % 2 ? ["edge noise"] : [] },
}));

const jobFetchCounts = new Map();

const stepsFor = (status) => {
  const names = [
    "global_data_scout",
    "sar_processing",
    "change_detection",
    "agent_routing",
    "agent_execution",
    "evidence_validation",
    "finding_publisher",
  ];
  return names.map((name, i) => {
    const idx = names.indexOf(name);
    let s = "pending";
    if (status === "succeeded") s = "succeeded";
    else if (status === "failed" && idx === 4) s = "failed";
    else if (idx < 4) s = "succeeded";
    else if (idx === 4 && status === "running") s = "running";
    return {
      step: i + 1,
      name,
      status: s,
      started_at: "2026-11-08T10:00:00Z",
      ended_at: s === "succeeded" ? "2026-11-08T10:00:30Z" : undefined,
      detail: s === "running" ? "executing routed agents" : undefined,
    };
  });
};

const makeJob = (id, status) => ({
  id,
  label: "Mock analysis",
  status,
  created_at: "2026-11-08T10:00:00Z",
  started_at: status === "queued" ? null : "2026-11-08T10:00:05Z",
  ended_at: status === "succeeded" ? "2026-11-08T10:02:41Z" : null,
  request: { start: "2026-06-01", end: "2026-08-01", max_observations: 6, include_browse: true },
  bbox: [86.8, 26.4, 87.4, 26.8],
  progress: status === "queued" ? 0.05 : status === "running" ? 0.55 : status === "failed" ? 0.6 : 1,
  current_stage: status === "queued" ? null : status === "running" ? "agent_execution" : "finding_publisher",
  steps: stepsFor(status),
  observations: observations.slice(0, 4),
  agents_selected: agents.slice(0, 6).map((a, i) => ({
    agent_id: a.id,
    agent_name: a.name,
    selected: i < 3,
    reason: i < 3 ? "sufficient valid pixels over overlap" : "no supporting acquisition pair",
    reason_code: i < 3 ? "SUFFICIENT_VALID_PIXELS" : "NO_OVERLAP",
  })),
  agent_runs:
    status === "queued"
      ? []
      : agents.slice(0, 3).map((a) => ({
          agent_id: a.id,
          status: status === "failed" && a.id === "wetlands" ? "failed" : "succeeded",
          duration_ms: 3000 + a.ordinal * 700,
          model_version: a.model_version,
          datasets: ["sen1floods11"],
          candidates: a.ordinal,
          log: ["[load] inputs ready", "[run] baseline executed", "[done] candidates emitted"],
          error: status === "failed" && a.id === "wetlands" ? "nodata over overlap" : undefined,
        })),
  findings: status === "succeeded" ? ["fnd-88213"] : [],
  error: status === "failed" ? "sar_processing failed: no valid pixels in bbox" : null,
  logs: ["[queue] accepted", "[scout] 9 granules matched", "[router] 3 of 6 agents selected"],
  metrics:
    status === "succeeded"
      ? { change_pixels: 1842213, changed_area_km2: 412.7, overlap_ratio: 0.87, processing_ms: 94210 }
      : null,
});

const svg = (label, bg, fg) =>
  `<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512"><rect width="512" height="512" fill="${bg}"/><circle cx="256" cy="256" r="150" fill="${fg}" opacity="0.75"/><text x="24" y="44" font-family="monospace" font-size="34" fill="#fff">${label}</text></svg>`;

const assets = {
  "before.png": svg("BEFORE", "#20304a", "#3E6FB0"),
  "after.png": svg("AFTER", "#20304a", "#E0A458"),
  "change.png": svg("MASK", "transparent", "#E05B5B"),
};

function send(res, code, body, type = "application/json") {
  const data = typeof body === "string" ? body : JSON.stringify(body);
  res.writeHead(code, { "content-type": type, "content-length": Buffer.byteLength(data) });
  res.end(data);
}

function err(res, code, status, message) {
  send(res, status, { error: { code, message } });
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);
  const p = url.pathname;
  const parts = p.split("/").filter(Boolean); // ["api", ...]

  res.setHeader("access-control-allow-origin", "*");
  res.setHeader("access-control-allow-headers", "*");
  res.setHeader("access-control-allow-methods", "GET,POST,OPTIONS");
  if (req.method === "OPTIONS") return res.writeHead(204).end();

  if (parts[0] !== "api") return err(res, "not_found", 404, `no route ${p}`);

  const tail = parts.slice(1);

  // health
  if (tail[0] === "health" && req.method === "GET") {
    return send(res, 200, {
      status: "ok",
      version: "0.3.0-mock",
      time: new Date().toISOString(),
      database: "ok",
      sources: [
        { id: "nasa_cmr", name: "NASA Earthdata CMR", description: "d", provider: "NASA", status: "operational", detail: "Anonymous metadata access OK", checked_at: "2026-11-08T09:00:00Z", auth_required: false },
        { id: "planetary_computer", name: "Microsoft Planetary Computer", description: "d", provider: "Microsoft", status: "operational", detail: "STAC search OK", checked_at: "2026-11-08T09:00:00Z", auth_required: false },
        { id: "earth_search", name: "AWS Earth Search", description: "d", provider: "AWS/Element84", status: "degraded", detail: "rate limited", checked_at: "2026-11-08T08:40:00Z", auth_required: false },
        { id: "copernicus_dataspace", name: "Copernicus Data Space", description: "d", provider: "ESA/Copernicus", status: "requires_credentials", detail: "token missing", checked_at: null, auth_required: true },
        { id: "earthdata_login", name: "Earthdata Login", description: "d", provider: "NASA", status: "unknown", detail: "not probed", checked_at: null, auth_required: true },
      ],
      counts: { observations: observations.length, findings: findings.length, jobs: 4, agents: agents.length },
    });
  }

  if (tail[0] === "datasets" && req.method === "GET") {
    return send(res, 200, {
      items: [
        { id: "sen1floods11", name: "SEN1FLOODS11", agent_ids: ["flood"], status: "available", access: "public download", url: "https://example.invalid", note: "labels" },
        { id: "jrc_global_surface_water", name: "JRC Global Surface Water", agent_ids: ["wetlands", "flood"], status: "registered", access: "STAC", url: null, note: "context" },
        { id: "global_forest_change", name: "Global Forest Change", agent_ids: ["forest"], status: "not_configured", access: "not wired", url: null, note: "pending" },
      ],
    });
  }

  if (tail[0] === "observations") {
    if (req.method === "GET" && tail.length === 1) {
      const page = Number(url.searchParams.get("page") ?? 1);
      return send(res, 200, { items: observations, page, page_size: 25, total: observations.length });
    }
    if (tail[0] === "observations" && tail[2] === "browse") {
      return send(res, 200, svg("QUICKLOOK", "#20304a", "#5FD0D6"), "image/svg+xml");
    }
    const found = observations.find((o) => o.id === tail[1]);
    if (found) return send(res, 200, found);
    return err(res, "not_found", 404, "observation not found");
  }

  if (tail[0] === "analysis") {
    if (req.method === "POST" && tail.length === 1) {
      const id = `job-${Date.now()}`;
      jobFetchCounts.set(id, 0);
      return send(res, 202, makeJob(id, "queued"));
    }
    if (tail.length === 1) {
      return send(res, 200, {
        items: [
          makeJob("job-2211", "succeeded"),
          makeJob("job-2209", "succeeded"),
          makeJob("job-2207", "failed"),
          makeJob("job-2205", "running"),
        ],
      });
    }
    if (tail[2] === "cancel") return send(res, 200, { status: "cancelled" });
    const id = tail[1];
    if (!jobFetchCounts.has(id)) jobFetchCounts.set(id, 0);
    const n = jobFetchCounts.get(id) + 1;
    jobFetchCounts.set(id, n);
    const status = n < 2 ? "queued" : n < 5 ? "running" : "succeeded";
    return send(res, 200, makeJob(id, status));
  }

  if (tail[0] === "jobs" && tail[2] === "assets") {
    const file = assets[tail[3]];
    if (file) return send(res, 200, file, "image/svg+xml");
    return err(res, "not_found", 404, "asset not generated");
  }

  if (tail[0] === "agents") {
    if (tail.length === 1) return send(res, 200, { items: agents });
    const d = agentDetails[tail[1]];
    if (d) return send(res, 200, d);
    return err(res, "not_found", 404, "agent not found");
  }

  if (tail[0] === "findings") {
    if (tail.length === 1) {
      return send(res, 200, { items: findings, page: 1, page_size: 25, total: findings.length });
    }
    const f = findings.find((x) => x.id === tail[1]);
    if (!f) return err(res, "not_found", 404, "finding not found");
    if (tail[2] === "evidence") return send(res, 200, { finding_id: f.id, evidence: evidenceFor(f) });
    if (tail[2] === "export.geojson")
      return send(res, 200, JSON.stringify({ type: "Feature", id: f.id, geometry: f.geometry, properties: f }), "application/geo+json");
    if (tail[2] === "report") return send(res, 200, `<html><body><h1>${f.title}</h1></body></html>`, "text/html");
    return send(res, 200, {
      ...f,
      evidence: evidenceFor(f),
      agent: { id: f.agent_id, name: agents.find((a) => a.id === f.agent_id)?.name ?? f.agent_id, status: "operational" },
      job: f.job_id ? { id: f.job_id, created_at: "2026-11-08T10:00:00Z", status: "succeeded" } : null,
      source_observations: observations.slice(0, 3),
    });
  }

  if (tail[0] === "map-layers") {
    const feature = (f) => ({
      type: "Feature",
      id: f.id,
      geometry: f.geometry ?? { type: "Point", coordinates: [f.location.centroid[1], f.location.centroid[0]] },
      properties: {
        id: f.id,
        title: f.title,
        category: f.category,
        verification_status: f.verification_status,
        area_km2: f.area_km2,
        centroid: f.location.centroid,
        created_at: f.created_at,
        agent_id: f.agent_id,
      },
    });
    return send(res, 200, {
      layers: [
        { id: "observation_footprints", name: "Observation footprints", type: "vector", default_on: true },
        { id: "findings", name: "Published findings", type: "vector", default_on: true },
        { id: "change_polygons", name: "Change polygons", type: "vector", default_on: true },
        { id: "analysis_bbox", name: "Analysis bbox", type: "vector", default_on: false },
      ],
      findings_geojson: { type: "FeatureCollection", features: findings.map(feature) },
      observations_geojson: {
        type: "FeatureCollection",
        features: observations.map((o) => ({ type: "Feature", geometry: o.footprint, properties: { platform: o.platform, product_type: o.product_type, datetime: o.datetime } })),
      },
      basemap_attribution: "© OpenStreetMap contributors © CARTO",
    });
  }

  if (tail[0] === "history") {
    return send(res, 200, {
      items: [
        { kind: "analysis", id: "job-2211", label: "Koshi floodplain", status: "succeeded", created_at: "2026-11-08T10:00:00Z", findings_count: 1, bbox: [86.8, 26.4, 87.4, 26.8] },
        { kind: "discovery", id: "job-2209", label: "global discovery", status: "succeeded", created_at: "2026-11-06T08:00:00Z", findings_count: 2, bbox: [-180, -90, 180, 90] },
      ],
    });
  }

  if (tail[0] === "models") {
    if (tail.length === 1)
      return send(res, 200, {
        items: agents.slice(0, 5).map((a) => ({
          id: `${a.id}:baseline`,
          agent_id: a.id,
          name: `${a.name} baseline`,
          kind: "baseline_algorithm",
          version: a.model_version,
          status: a.status === "operational" ? "active" : "candidate",
          dataset_ids: ["sen1floods11"],
          metrics: [
            { name: "f1", value: 0.71, split: "heldout" },
            { name: "roc_auc", value: null, split: null },
          ],
          checkpoint_path: null,
          trained_at: null,
          sample_count: null,
          limitations: ["No labelled data for calibration."],
        })),
      });
    return send(res, 200, { id: tail[1], agent_id: "flood", name: "m", kind: "baseline_algorithm", version: "1", status: "active", dataset_ids: [], metrics: [], checkpoint_path: null, trained_at: null, sample_count: null, limitations: [] });
  }

  if (tail[0] === "training" && tail[1] === "runs") {
    return send(res, 200, {
      items: [
        { id: "run-1", agent_id: "flood", model_id: "flood:baseline", status: "completed", started_at: "2026-10-01T10:00:00Z", ended_at: "2026-10-01T11:00:00Z", dataset_ids: ["sen1floods11"], config: { lr: 0.01 }, metrics: { f1: 0.71 }, notes: "threshold sweep" },
        { id: "run-2", agent_id: "forest", model_id: "forest:baseline", status: "failed", started_at: "2026-10-05T10:00:00Z", ended_at: "2026-10-05T10:12:00Z", dataset_ids: [], config: {}, metrics: {}, notes: "dataset missing" },
      ],
    });
  }

  if (tail[0] === "sources") {
    if (tail.length === 1)
      return send(res, 200, {
        items: [
          { id: "nasa_cmr", name: "NASA Earthdata CMR", description: "d", provider: "NASA", status: "operational", detail: "Anonymous metadata access OK", checked_at: "2026-11-08T09:00:00Z", auth_required: false },
          { id: "planetary_computer", name: "Microsoft Planetary Computer", description: "d", provider: "Microsoft", status: "operational", detail: "STAC search OK", checked_at: "2026-11-08T09:00:00Z", auth_required: false },
          { id: "earth_search", name: "AWS Earth Search", description: "d", provider: "AWS/Element84", status: "degraded", detail: "rate limited", checked_at: "2026-11-08T08:40:00Z", auth_required: false },
          { id: "copernicus_dataspace", name: "Copernicus Data Space", description: "d", provider: "ESA/Copernicus", status: "requires_credentials", detail: "token missing", checked_at: null, auth_required: true },
          { id: "earthdata_login", name: "Earthdata Login", description: "d", provider: "NASA", status: "unknown", detail: "not probed", checked_at: null, auth_required: true },
        ],
      });
    if (tail[2] === "check")
      return send(res, 200, { id: tail[1], name: tail[1], description: "d", provider: "NASA", status: "operational", detail: "re-checked just now", checked_at: new Date().toISOString(), auth_required: false });
  }

  if (tail[0] === "discovery" && tail[1] === "run" && req.method === "POST") {
    return send(res, 200, { job_id: "job-discovery", observations });
  }

  return err(res, "not_found", 404, `no route ${p}`);
});

server.listen(PORT, "127.0.0.1", () => console.log(`mock backend on http://127.0.0.1:${PORT}`));
