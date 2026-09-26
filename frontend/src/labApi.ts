/** Phase 102 Experiment Lab API calls (kept apart from api.ts, which stays topology/attribution only). */
import { ApiError, type ApiOptions } from "./api";

export interface ExperimentRow {
  experiment_id: string;
  dataset_version: string;
  random_seed: number;
  timestamp: string;
  configuration: Record<string, unknown>;
}
export interface ExperimentMetric {
  metric_id: string;
  context: string;
  [field: string]: unknown;
}
export interface ExperimentDetail {
  experiment: { experiment_id: string; dataset_version: string; code_version: string; random_seed: number; timestamp: string; environment: string };
  hypothesis: string | null;
  setup: { configuration: Record<string, unknown>; parameters: Record<string, unknown> };
  result: Record<string, unknown>;
  metrics: ExperimentMetric[];
}
export interface CompareRow {
  context: string;
  metric: string;
  a: number;
  b: number;
  delta: number;
}
export interface RunRequest {
  topology_level: string;
  completeness: number;
  ablation: string | null;
  seed: number;
}
export interface RunEvent {
  event: string;
  data: Record<string, unknown>;
}

function headersFor(opt: ApiOptions, json = false): Record<string, string> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (json) headers["Content-Type"] = "application/json";
  if (opt.token) headers.Authorization = `Bearer ${opt.token}`;
  if (opt.tenantKey) headers["X-Tenant-Key"] = opt.tenantKey;
  return headers;
}

async function failure(resp: Response, code: string): Promise<ApiError> {
  let body: { detail?: unknown; error?: string } = {};
  try {
    body = await resp.json();
  } catch {
    /* non-JSON error */
  }
  const retry = resp.headers.get("Retry-After");
  const text = typeof body.detail === "string" ? body.detail : resp.statusText;
  return new ApiError(resp.status, body.error ?? code, retry ? `${text} (retry in ${retry}s)` : text);
}

async function getJson<T>(path: string, query: Record<string, string | number>, opt: ApiOptions): Promise<T> {
  const url = new URL((opt.base ?? "") + "/api/v1" + path, window.location.origin);
  for (const [k, v] of Object.entries(query)) url.searchParams.set(k, String(v));
  const resp = await fetch(url.toString(), { headers: headersFor(opt) });
  if (!resp.ok) throw await failure(resp, "http_error");
  return (await resp.json()) as T;
}

export async function listExperiments(opt: ApiOptions): Promise<ExperimentRow[]> {
  return (await getJson<{ items: ExperimentRow[] }>("/experiments", { limit: 200 }, opt)).items;
}
export const experimentDetail = (id: string, opt: ApiOptions): Promise<ExperimentDetail> =>
  getJson(`/experiments/${encodeURIComponent(id)}`, {}, opt);
export async function compareExperiments(a: string, b: string, opt: ApiOptions): Promise<CompareRow[]> {
  return (await getJson<{ rows: CompareRow[] }>("/experiments/compare", { a, b }, opt)).rows;
}

/** Starts a run; returns the job id. 403 (disabled), 422 (bad request) and 429 (busy / rate limited) surface as ApiError. */
export async function startExperimentRun(req: RunRequest, opt: ApiOptions): Promise<string> {
  const resp = await fetch((opt.base ?? "") + "/api/v1/experiments", { method: "POST", headers: headersFor(opt, true), body: JSON.stringify(req) });
  if (!resp.ok) throw await failure(resp, "run_rejected");
  return ((await resp.json()) as { job_id: string }).job_id;
}

/** Reads the SSE stream with fetch (EventSource cannot send auth/tenant headers). Resolves when the server closes it. */
export async function streamRunEvents(jobId: string, opt: ApiOptions, onEvent: (e: RunEvent) => void, signal?: AbortSignal): Promise<void> {
  const resp = await fetch(`${opt.base ?? ""}/api/v1/experiments/jobs/${jobId}/events`, {
    headers: { ...headersFor(opt), Accept: "text/event-stream" },
    signal,
  });
  if (!resp.ok || !resp.body) throw await failure(resp, "stream_failed");
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) return;
    buf += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const block = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      let event = "message";
      let data = "{}";
      for (const line of block.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice(7);
        else if (line.startsWith("data: ")) data = line.slice(6);
      }
      onEvent({ event, data: JSON.parse(data) as Record<string, unknown> });
    }
  }
}
