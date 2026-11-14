// TerraTrace AI — typed API client for the FastAPI backend (docs/API_CONTRACT.md).
// Every endpoint in the contract has a typed request function here.

import { useCallback, useEffect, useRef, useState } from "react";
import type {
  AgentDetail,
  AgentSummary,
  AnalysisJob,
  AnalysisRequest,
  DataSourceStatus,
  DatasetInfo,
  DiscoveryRunResponse,
  FindingDetail,
  FindingEvidence,
  FindingListResponse,
  HealthResponse,
  HistoryEntry,
  MapLayersResponse,
  ModelInfo,
  Observation,
  ObservationListResponse,
} from "../types";

/**
 * Backend origin. Defaults to the local FastAPI dev server; override with the
 * `VITE_API_BASE` environment variable (set it to `""` or `"/api"` to route
 * through the Vite dev proxy instead of calling the origin directly).
 */
export const API_BASE = (import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000").replace(
  /\/+$/,
  ""
);

/** Prefix an API-relative path (e.g. finding asset urls) with the backend origin. */
export function apiUrl(path: string): string {
  if (/^https?:\/\//i.test(path)) return path;
  return `${API_BASE}${path.startsWith("/") ? "" : "/"}${path}`;
}

export class ApiError extends Error {
  code: string;
  status: number;
  detail: unknown;

  constructor(message: string, code = "unknown", status = 0, detail?: unknown) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.detail = detail;
  }
}

function isAbort(err: unknown): boolean {
  return err instanceof DOMException && err.name === "AbortError";
}

type QueryValue = string | number | boolean | undefined | null;

/** Build a `?a=b&c=d` string, skipping null/undefined values. */
export function qs(params: Record<string, QueryValue>): string {
  const parts: string[] = [];
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    parts.push(`${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`);
  }
  return parts.length ? `?${parts.join("&")}` : "";
}

interface RequestOptions {
  method?: "GET" | "POST" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, signal } = options;
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";

  let res: Response;
  try {
    res = await fetch(apiUrl(path), {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  } catch (err) {
    if (isAbort(err)) throw err;
    throw new ApiError(
      `Backend unreachable at ${API_BASE || window.location.origin} — is the API running?`,
      "network",
      0
    );
  }

  const text = await res.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = null;
    }
  }

  const rawError = payload && typeof payload === "object" ? (payload as Record<string, unknown>).error : null;
  const errEnvelope =
    rawError && typeof rawError === "object"
      ? (rawError as { code?: string; message?: string; detail?: unknown })
      : null;

  if (!res.ok || errEnvelope) {
    const message =
      errEnvelope?.message ??
      (typeof payload === "string" && payload
        ? payload
        : `${res.status} ${res.statusText || "Request failed"}`);
    const code = errEnvelope?.code ?? `http_${res.status}`;
    throw new ApiError(message, code, res.status, errEnvelope?.detail ?? payload);
  }

  if (payload === null) return undefined as T;
  return payload as T;
}

/* ------------------------------------------------------- endpoint functions */

export const api = {
  // GET /api/health
  health: (signal?: AbortSignal) => request<HealthResponse>("/api/health", { signal }),

  // GET /api/datasets
  datasets: (signal?: AbortSignal) =>
    request<{ items: DatasetInfo[] }>("/api/datasets", { signal }),

  // GET /api/observations
  observations: (
    params: {
      bbox?: string;
      start?: string;
      end?: string;
      mission?: string;
      source?: string;
      page?: number;
      page_size?: number;
    } = {},
    signal?: AbortSignal
  ) => request<ObservationListResponse>(`/api/observations${qs(params)}`, { signal }),

  // GET /api/observations/{id}
  observation: (id: string, signal?: AbortSignal) =>
    request<Observation>(`/api/observations/${encodeURIComponent(id)}`, { signal }),

  // GET /api/observations/{id}/browse → image/png (handled via apiUrl())
  observationBrowseUrl: (id: string) =>
    apiUrl(`/api/observations/${encodeURIComponent(id)}/browse`),

  // POST /api/analysis
  createAnalysis: (body: AnalysisRequest, signal?: AbortSignal) =>
    request<AnalysisJob>("/api/analysis", { method: "POST", body, signal }),

  // GET /api/analysis
  analysisList: (signal?: AbortSignal) =>
    request<{ items: AnalysisJob[] }>("/api/analysis", { signal }),

  // GET /api/analysis/{job_id}
  job: (jobId: string, signal?: AbortSignal) =>
    request<AnalysisJob>(`/api/analysis/${encodeURIComponent(jobId)}`, { signal }),

  // POST /api/analysis/{job_id}/cancel
  cancelJob: (jobId: string, signal?: AbortSignal) =>
    request<{ status: string }>(`/api/analysis/${encodeURIComponent(jobId)}/cancel`, {
      method: "POST",
      signal,
    }),

  // GET /api/agents
  agents: (signal?: AbortSignal) => request<{ items: AgentSummary[] }>("/api/agents", { signal }),

  // GET /api/agents/{agent_id}
  agent: (agentId: string, signal?: AbortSignal) =>
    request<AgentDetail>(`/api/agents/${encodeURIComponent(agentId)}`, { signal }),

  // GET /api/findings
  findings: (
    params: {
      page?: number;
      page_size?: number;
      category?: string;
      status?: string;
      job_id?: string;
      bbox?: string;
    } = {},
    signal?: AbortSignal
  ) => request<FindingListResponse>(`/api/findings${qs(params)}`, { signal }),

  // GET /api/findings/{finding_id}
  finding: (findingId: string, signal?: AbortSignal) =>
    request<FindingDetail>(`/api/findings/${encodeURIComponent(findingId)}`, { signal }),

  // GET /api/findings/{finding_id}/evidence
  findingEvidence: (findingId: string, signal?: AbortSignal) =>
    request<{ finding_id: string; evidence: FindingEvidence }>(
      `/api/findings/${encodeURIComponent(findingId)}/evidence`,
      { signal }
    ),

  // GET /api/findings/{finding_id}/export.geojson → application/geo+json (browser download)
  findingGeoJsonUrl: (findingId: string) =>
    apiUrl(`/api/findings/${encodeURIComponent(findingId)}/export.geojson`),

  // GET /api/findings/{finding_id}/report → text/html (open in new tab)
  findingReportUrl: (findingId: string) =>
    apiUrl(`/api/findings/${encodeURIComponent(findingId)}/report`),

  // GET /api/map-layers
  mapLayers: (signal?: AbortSignal) => request<MapLayersResponse>("/api/map-layers", { signal }),

  // GET /api/history
  history: (params: { page?: number; page_size?: number } = {}, signal?: AbortSignal) =>
    request<{ items: HistoryEntry[] }>(`/api/history${qs(params)}`, { signal }),

  // GET /api/models
  models: (signal?: AbortSignal) => request<{ items: ModelInfo[] }>("/api/models", { signal }),

  // GET /api/models/{model_id}
  model: (modelId: string, signal?: AbortSignal) =>
    request<ModelInfo>(`/api/models/${encodeURIComponent(modelId)}`, { signal }),

  // GET /api/training/overview
  trainingOverview: (signal?: AbortSignal) =>
    request<any>("/api/training/overview", { signal }),

  // GET /api/training/agents
  trainingAgents: (signal?: AbortSignal) =>
    request<any[]>("/api/training/agents", { signal }),

  // GET /api/training/agents/{id}
  trainingAgent: (agentId: string, signal?: AbortSignal) =>
    request<any>(`/api/training/agents/${encodeURIComponent(agentId)}`, { signal }),

  // POST /api/training/datasets/discover
  discoverDatasets: (signal?: AbortSignal) =>
    request<any>("/api/training/datasets/discover", { method: "POST", signal }),

  // POST /api/training/datasets/prepare
  prepareDataset: (body: { dataset_id: string }, signal?: AbortSignal) =>
    request<any>("/api/training/datasets/prepare", { method: "POST", body, signal }),

  // POST /api/training/agents/{id}/start
  startTraining: (agentId: string, body: { dataset_id?: string; config?: Record<string, unknown> }, signal?: AbortSignal) =>
    request<any>(`/api/training/agents/${encodeURIComponent(agentId)}/start`, { method: "POST", body, signal }),

  // GET /api/training/jobs/{id}
  trainingJob: (jobId: string, signal?: AbortSignal) =>
    request<any>(`/api/training/jobs/${encodeURIComponent(jobId)}`, { signal }),

  // POST /api/training/jobs/{id}/cancel
  cancelTrainingJob: (jobId: string, signal?: AbortSignal) =>
    request<any>(`/api/training/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST", signal }),

  // POST /api/training/agents/{id}/evaluate
  evaluateAgent: (agentId: string, signal?: AbortSignal) =>
    request<any>(`/api/training/agents/${encodeURIComponent(agentId)}/evaluate`, { method: "POST", signal }),

  // POST /api/models/{id}/deploy
  deployModel: (modelId: string, signal?: AbortSignal) =>
    request<any>(`/api/models/${encodeURIComponent(modelId)}/deploy`, { method: "POST", signal }),

  // POST /api/models/{id}/rollback
  rollbackModel: (modelId: string, signal?: AbortSignal) =>
    request<any>(`/api/models/${encodeURIComponent(modelId)}/rollback`, { method: "POST", signal }),

  // GET /api/training/history
  trainingHistory: (signal?: AbortSignal) =>
    request<any>("/api/training/history", { signal }),

  // GET /api/sources
  sources: (signal?: AbortSignal) =>
    request<{ items: DataSourceStatus[] }>("/api/sources", { signal }),

  // POST /api/sources/{source_id}/check
  checkSource: (sourceId: string, signal?: AbortSignal) =>
    request<DataSourceStatus>(`/api/sources/${encodeURIComponent(sourceId)}/check`, {
      method: "POST",
      signal,
    }),

  // POST /api/discovery/run
  discoveryRun: (
    body: { bbox?: number[]; start?: string; end?: string; limit?: number },
    signal?: AbortSignal
  ) => request<DiscoveryRunResponse>("/api/discovery/run", { method: "POST", body, signal }),

  // GET /api/jobs/{job_id}/assets/{asset_name} → PNG / GeoJSON artifacts (browser url)
  jobAssetUrl: (jobId: string, assetName: string) =>
    apiUrl(`/api/jobs/${encodeURIComponent(jobId)}/assets/${encodeURIComponent(assetName)}`),
};

/* ------------------------------------------------------------------ hooks */

export interface ApiState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

/**
 * Fetch `path` on mount (and on refetch). Pass `null` to disable.
 * `pollMs` re-requests on an interval (used for job progress polling).
 */
export function useApi<T>(path: string | null, options?: { pollMs?: number }): ApiState<T> {
  const pollMs = options?.pollMs;
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState<boolean>(path !== null);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const loadedRef = useRef(false);

  const refetch = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    if (path === null) {
      loadedRef.current = false;
      setData(null);
      setLoading(false);
      setError(null);
      return;
    }

    let alive = true;
    const controller = new AbortController();
    if (!loadedRef.current) setLoading(true);

    const run = async () => {
      try {
        const result = await request<T>(path, { signal: controller.signal });
        if (!alive) return;
        loadedRef.current = true;
        setData(result);
        setError(null);
        setLoading(false);
      } catch (err) {
        if (!alive || isAbort(err)) return;
        const message = err instanceof ApiError ? err.message : String(err);
        setError(message);
        setLoading(false);
      }
    };

    void run();
    let timer: number | undefined;
    if (pollMs && pollMs > 0) {
      timer = window.setInterval(() => void run(), pollMs);
    }

    return () => {
      alive = false;
      controller.abort();
      if (timer !== undefined) window.clearInterval(timer);
    };
  }, [path, nonce, pollMs]);

  return { data, loading, error, refetch };
}
