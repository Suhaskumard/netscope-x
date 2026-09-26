/** Typed access to the versioned REST API (/api/v1). Only what the topology explorer needs. */

export interface Snapshot {
  snapshot_id: string;
  graph_id: string;
  captured_at: string;
  version: number;
}
export interface TopoNode {
  node_id: string;
  ip_addresses: string[];
  first_observed: string;
  last_observed: string;
}
export interface TopoEdge {
  edge_id: string;
  source_node_id: string;
  target_node_id: string;
  confidence: number;
  evidence: string[];
  observation_count: number;
  first_observed: string;
  last_observed: string;
  protocols: string[];
}
export interface TopologyGraph {
  graph_id: string;
  generated_at: string;
  nodes: TopoNode[];
  edges: TopoEdge[];
}
export interface ChangeEvent {
  event_id: string;
  from_snapshot_id: string;
  to_snapshot_id: string;
  occurred_at: string;
  change_type: string;
  affected_node_id: string | null;
  affected_edge_id: string | null;
  attribute_name: string | null;
  previous_value: string | null;
  new_value: string | null;
  evidence: string[];
}
interface Page<T> {
  items: T[];
  total: number;
}

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
  }
}

export interface ApiOptions {
  base?: string;
  token?: string;
  tenantKey?: string;
}

async function get<T>(path: string, params: Record<string, string | number>, opt: ApiOptions): Promise<T> {
  const url = new URL((opt.base ?? "") + "/api/v1" + path, window.location.origin);
  for (const [k, v] of Object.entries(params)) url.searchParams.set(k, String(v));
  const headers: Record<string, string> = { Accept: "application/json" };
  if (opt.token) headers.Authorization = `Bearer ${opt.token}`;
  if (opt.tenantKey) headers["X-Tenant-Key"] = opt.tenantKey;
  const resp = await fetch(url.toString(), { headers });
  if (!resp.ok) {
    let body: { error?: string; detail?: string } = {};
    try {
      body = await resp.json();
    } catch {
      /* non-JSON error */
    }
    throw new ApiError(resp.status, body.error ?? "http_error", body.detail ?? resp.statusText);
  }
  return (await resp.json()) as T;
}

export async function listSnapshots(captureId: string, opt: ApiOptions): Promise<Snapshot[]> {
  const out: Snapshot[] = [];
  for (let offset = 0; ; ) {
    const page = await get<Page<Snapshot>>("/history/snapshots", { capture_id: captureId, limit: 500, offset }, opt);
    out.push(...page.items);
    offset += page.items.length;
    if (page.items.length === 0 || offset >= page.total) return out;
  }
}

export const snapshotTopology = (captureId: string, version: number, opt: ApiOptions): Promise<TopologyGraph> =>
  get<TopologyGraph>(`/history/snapshots/${version}/topology`, { capture_id: captureId }, opt);

/** Change events recorded between two consecutive snapshots (the timeline is per consecutive pair). */
export async function eventsBetween(captureId: string, toSnapshotId: string, opt: ApiOptions): Promise<ChangeEvent[]> {
  const out: ChangeEvent[] = [];
  for (let offset = 0; ; ) {
    const page = await get<Page<ChangeEvent>>(
      "/history",
      { capture_id: captureId, start: "1970-01-01T00:00:00Z", end: "2100-01-01T00:00:00Z", limit: 500, offset },
      opt,
    );
    out.push(...page.items);
    offset += page.items.length;
    if (page.items.length === 0 || offset >= page.total) break;
  }
  return out.filter((e) => e.to_snapshot_id === toSnapshotId);
}
