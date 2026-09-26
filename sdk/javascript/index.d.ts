export const API_PREFIX: "/api/v1";

export interface ClientOptions { token?: string; tenantKey?: string; timeoutMs?: number; retries?: number; backoffMs?: number }
export interface Page<T = any> { items: T[]; limit: number; offset: number; total: number }
export interface PageOptions { limit?: number; offset?: number }

export class NetscopeError extends Error {
  status: number; error: string; detail: any; requestId: string | null;
}
export class ValidationError extends NetscopeError {}
export class AuthenticationError extends NetscopeError {}
export class AuthorizationError extends NetscopeError {}
export class NotFoundError extends NetscopeError {}
export class NotImplementedOnServer extends NetscopeError {}
export class ServerError extends NetscopeError {}

export class NetscopeClient {
  constructor(baseUrl: string, options?: ClientOptions);
  capture(source: "pcap_upload" | "live_interface" | "netflow_upload",
          opts?: { pcapFilename?: string; interface?: string; flowFilename?: string; flowFormat?: "v5" | "ipfix" }): Promise<{ capture_id: string; status: string; packet_count: number | null }>;
  uploadPcap(pcapFilename: string): Promise<any>;
  uploadNetflow(flowFilename: string, flowFormat: "v5" | "ipfix"): Promise<any>;
  flows(captureId: string, opts?: PageOptions): Promise<Page>;
  topology(captureId: string): Promise<any>;
  dependencies(captureId: string, opts?: PageOptions): Promise<Page>;
  causal(dependencyId: string, captureId: string): Promise<any>;
  attribution(dependencyId: string, captureId: string): Promise<any>;
  history(captureId: string, start: string | Date, end: string | Date, opts?: PageOptions): Promise<Page>;
  snapshots(captureId: string, opts?: PageOptions): Promise<Page>;
  snapshotTopology(captureId: string, version: number): Promise<any>;
  experiments(opts?: PageOptions): Promise<Page>;
  metrics(opts?: PageOptions & { context?: string }): Promise<Page>;
  anomalies(opts?: PageOptions & { nodeId?: string }): Promise<Page>;
  behavior(nodeId: string): Promise<any>;
  simulate(scenario: object): Promise<any>;
  counterfactual(scenario: object): Promise<any>;
  askCounterfactual(captureId: string, question: string): Promise<any>;
  investigationReport(captureId: string, dependencyId: string, failedNodeId?: string): Promise<any>;
  rootCause(captureId: string, failedNodeId: string, maxCandidates?: number): Promise<any>;
  createExperiment(experiment: object): Promise<any>;
  paginate(method: "flows" | "dependencies" | "history" | "experiments" | "metrics" | "anomalies", ...args: any[]): AsyncGenerator<any>;
}
