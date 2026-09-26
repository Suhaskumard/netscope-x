import type { TopologyGraph } from "./api";

export type Status = "same" | "added" | "removed" | "changed";

/** Stable identity across snapshots: node = its IP set, edge = its two endpoint IP sets (ids are per-graph). */
export const nodeKey = (g: TopologyGraph, id: string): string =>
  g.nodes.find((n) => n.node_id === id)?.ip_addresses.slice().sort().join("+") ?? id;

export interface ViewNode {
  key: string;
  label: string;
  status: Status;
}
export interface ViewEdge {
  key: string;
  source: string;
  target: string;
  confidence: number;
  previous?: number;
  status: Status;
  ref?: string; // edge_id in the current graph (undefined for removed)
}

const edgeKey = (a: string, b: string): string => (a < b ? `${a}|${b}` : `${b}|${a}`);

/** Current graph plus, when `prev` is given, ghosts of what disappeared and status flags for what changed. */
export function buildView(cur: TopologyGraph, prev: TopologyGraph | null): { nodes: ViewNode[]; edges: ViewEdge[] } {
  const curNodes = new Map(cur.nodes.map((n) => [nodeKey(cur, n.node_id), n]));
  const prevNodes = prev ? new Set(prev.nodes.map((n) => nodeKey(prev, n.node_id))) : null;
  const nodes: ViewNode[] = [];
  for (const [key, n] of curNodes) {
    nodes.push({ key, label: n.ip_addresses.join(", "), status: prevNodes && !prevNodes.has(key) ? "added" : "same" });
  }
  if (prev) {
    for (const n of prev.nodes) {
      const key = nodeKey(prev, n.node_id);
      if (!curNodes.has(key)) nodes.push({ key, label: n.ip_addresses.join(", "), status: "removed" });
    }
  }

  const prevEdges = new Map<string, number>();
  if (prev) for (const e of prev.edges) prevEdges.set(edgeKey(nodeKey(prev, e.source_node_id), nodeKey(prev, e.target_node_id)), e.confidence);
  const edges: ViewEdge[] = [];
  const seen = new Set<string>();
  for (const e of cur.edges) {
    const s = nodeKey(cur, e.source_node_id);
    const t = nodeKey(cur, e.target_node_id);
    const k = edgeKey(s, t);
    seen.add(k);
    const before = prevEdges.get(k);
    let status: Status = "same";
    if (prev) status = before === undefined ? "added" : Math.abs(before - e.confidence) > 1e-9 ? "changed" : "same";
    edges.push({ key: k, source: s, target: t, confidence: e.confidence, previous: before, status, ref: e.edge_id });
  }
  if (prev) {
    for (const e of prev.edges) {
      const s = nodeKey(prev, e.source_node_id);
      const t = nodeKey(prev, e.target_node_id);
      const k = edgeKey(s, t);
      if (!seen.has(k)) edges.push({ key: k, source: s, target: t, confidence: e.confidence, status: "removed" });
    }
  }
  return { nodes, edges };
}
