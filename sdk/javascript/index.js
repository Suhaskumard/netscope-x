// NETSCOPE-X JavaScript client (spec Phase 96). Zero dependencies; needs global fetch (Node >= 18 or a browser).
// Pins the /api/v1 REST surface. Responses are the server's JSON, unmodified.

export const API_PREFIX = "/api/v1";
const RETRY_STATUS = new Set([502, 503, 504]);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export class NetscopeError extends Error {
  constructor(status, error, detail, requestId) {
    super(`${status} ${error}: ${typeof detail === "string" ? detail : JSON.stringify(detail)} (request_id=${requestId})`);
    this.name = this.constructor.name;
    this.status = status;
    this.error = error;
    this.detail = detail;
    this.requestId = requestId;
  }
}
export class ValidationError extends NetscopeError {} // 422
export class AuthenticationError extends NetscopeError {} // 401
export class AuthorizationError extends NetscopeError {} // 403
export class NotFoundError extends NetscopeError {} // 404
export class NotImplementedOnServer extends NetscopeError {} // 501: validated route, backend stage not wired
export class ServerError extends NetscopeError {} // 5xx and anything else

const BY_STATUS = { 422: ValidationError, 401: AuthenticationError, 403: AuthorizationError, 404: NotFoundError, 501: NotImplementedOnServer };

export class NetscopeClient {
  constructor(baseUrl, { token, tenantKey, timeoutMs = 30000, retries = 2, backoffMs = 200 } = {}) {
    this.baseUrl = baseUrl.replace(/\/+$/, "");
    Object.assign(this, { token, tenantKey, timeoutMs, retries, backoffMs });
  }

  async _request(method, path, params, body) {
    let url = this.baseUrl + API_PREFIX + path;
    if (params) {
      const q = new URLSearchParams();
      for (const [k, v] of Object.entries(params)) {
        if (v !== undefined && v !== null) q.set(k, v instanceof Date ? v.toISOString() : String(v));
      }
      if ([...q].length) url += "?" + q.toString();
    }
    const headers = { Accept: "application/json" };
    if (this.token) headers.Authorization = `Bearer ${this.token}`;
    if (this.tenantKey) headers["X-Tenant-Key"] = this.tenantKey;
    let payload;
    if (body !== undefined) {
      payload = JSON.stringify(body);
      headers["Content-Type"] = "application/json";
    }
    const attempts = 1 + (method === "GET" ? this.retries : 0); // only idempotent reads are retried
    for (let attempt = 0; attempt < attempts; attempt++) {
      let resp;
      try {
        resp = await fetch(url, { method, headers, body: payload, signal: AbortSignal.timeout(this.timeoutMs) });
      } catch (err) {
        if (attempt < attempts - 1) {
          await sleep(this.backoffMs * 2 ** attempt);
          continue;
        }
        throw err;
      }
      if (resp.ok) {
        const text = await resp.text();
        return text ? JSON.parse(text) : null;
      }
      if (RETRY_STATUS.has(resp.status) && attempt < attempts - 1) {
        await sleep(this.backoffMs * 2 ** attempt);
        continue;
      }
      let err = {};
      try {
        err = await resp.json();
      } catch {
        /* non-JSON error body */
      }
      if (err === null || typeof err !== "object") err = {};
      const Cls = BY_STATUS[resp.status] || ServerError;
      throw new Cls(resp.status, err.error ?? "http_error", err.detail ?? resp.statusText, err.request_id ?? null);
    }
  }

  capture(source, { pcapFilename, interface: iface, flowFilename, flowFormat } = {}) {
    const body = { source, pcap_filename: pcapFilename, interface: iface, flow_filename: flowFilename, flow_format: flowFormat };
    for (const k of Object.keys(body)) if (body[k] === undefined) delete body[k];
    return this._request("POST", "/capture", undefined, body);
  }
  uploadPcap(pcapFilename) { return this.capture("pcap_upload", { pcapFilename }); }
  uploadNetflow(flowFilename, flowFormat) { return this.capture("netflow_upload", { flowFilename, flowFormat }); }

  flows(captureId, { limit = 50, offset = 0 } = {}) { return this._request("GET", "/flows", { capture_id: captureId, limit, offset }); }
  topology(captureId) { return this._request("GET", "/topology", { capture_id: captureId }); }
  dependencies(captureId, { limit = 50, offset = 0 } = {}) { return this._request("GET", "/dependencies", { capture_id: captureId, limit, offset }); }
  causal(dependencyId, captureId) { return this._request("GET", `/causal/${encodeURIComponent(dependencyId)}`, { capture_id: captureId }); }
  attribution(dependencyId, captureId) { return this._request("GET", `/causal/${encodeURIComponent(dependencyId)}/attribution`, { capture_id: captureId }); }
  history(captureId, start, end, { limit = 50, offset = 0 } = {}) { return this._request("GET", "/history", { capture_id: captureId, start, end, limit, offset }); }
  snapshots(captureId, { limit = 50, offset = 0 } = {}) { return this._request("GET", "/history/snapshots", { capture_id: captureId, limit, offset }); }
  snapshotTopology(captureId, version) { return this._request("GET", `/history/snapshots/${Number(version)}/topology`, { capture_id: captureId }); }
  experiments({ limit = 50, offset = 0 } = {}) { return this._request("GET", "/experiments", { limit, offset }); }
  metrics({ context, limit = 50, offset = 0 } = {}) { return this._request("GET", "/metrics", { context, limit, offset }); }
  anomalies({ nodeId, limit = 50, offset = 0 } = {}) { return this._request("GET", "/anomalies", { node_id: nodeId, limit, offset }); }
  behavior(nodeId) { return this._request("GET", `/behaviors/${encodeURIComponent(nodeId)}`); }

  simulate(scenario) { return this._request("POST", "/simulation", undefined, scenario); }
  counterfactual(scenario) { return this._request("POST", "/counterfactual", undefined, scenario); }
  askCounterfactual(captureId, question) { return this._request("POST", "/counterfactual/ask", undefined, { capture_id: captureId, question }); }
  investigationReport(captureId, dependencyId, failedNodeId) { return this._request("POST", "/investigation/report", undefined, { capture_id: captureId, dependency_id: dependencyId, ...(failedNodeId ? { failed_node_id: failedNodeId } : {}) }); }
  createExperiment(experiment) { return this._request("POST", "/experiments", undefined, experiment); }

  /** Async iterator over every item of a paginated list method, e.g. `client.paginate("flows", captureId)`. */
  async *paginate(method, ...args) {
    const pageSize = 100;
    let offset = 0;
    for (;;) {
      const page = await this[method](...args, { limit: pageSize, offset });
      yield* page.items;
      offset += page.items.length;
      if (page.items.length === 0 || offset >= page.total) return;
    }
  }
}
