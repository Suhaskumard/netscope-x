import { useEffect, useRef } from "react";
import cytoscape from "cytoscape";
import type { ViewEdge, ViewNode } from "./diff";

const COLORS = { same: "#64748b", added: "#22c55e", removed: "#ef4444", changed: "#f59e0b" } as const;

/** Deterministic position from the node key, so the same host stays in the same place from snapshot to snapshot. */
function position(key: string): { x: number; y: number } {
  const last = parseInt(key.split(/[.+]/).filter(Boolean).pop() ?? "0", 10) || 0;
  let h = 0;
  for (const c of key) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  const angle = ((h % 3600) / 3600) * Math.PI * 2;
  const radius = 120 + (last % 5) * 45;
  return { x: 400 + Math.cos(angle) * radius, y: 260 + Math.sin(angle) * radius };
}

interface Props {
  nodes: ViewNode[];
  edges: ViewEdge[];
  onSelect: (what: { kind: "node" | "edge"; key: string } | null) => void;
}

export default function GraphView({ nodes, edges, onSelect }: Props): JSX.Element {
  const host = useRef<HTMLDivElement>(null);
  const cy = useRef<cytoscape.Core | null>(null);

  useEffect(() => {
    if (!host.current) return;
    const core = cytoscape({
      container: host.current,
      elements: [],
      layout: { name: "preset" },
      style: [
        { selector: "node", style: { label: "data(label)", color: "#e2e8f0", "font-size": 11, "text-valign": "bottom", "text-margin-y": 6, "background-color": "data(color)", width: 26, height: 26, "border-width": 2, "border-color": "#0f172a" } },
        { selector: "node[status = 'removed']", style: { opacity: 0.45, "border-style": "dashed", "border-color": "#ef4444" } },
        { selector: "edge", style: { width: "data(width)", "line-color": "data(color)", opacity: 0.9, "curve-style": "bezier", label: "data(clabel)", color: "#94a3b8", "font-size": 9, "text-background-color": "#020617", "text-background-opacity": 0.8 } },
        { selector: "edge[status = 'removed']", style: { "line-style": "dashed", opacity: 0.4 } },
        { selector: ":selected", style: { "border-color": "#38bdf8", "line-color": "#38bdf8", "border-width": 3 } },
      ],
    });
    core.on("tap", "node", (e) => onSelect({ kind: "node", key: e.target.id() }));
    core.on("tap", "edge", (e) => onSelect({ kind: "edge", key: e.target.data("key") }));
    core.on("tap", (e) => {
      if (e.target === core) onSelect(null);
    });
    cy.current = core;
    (window as unknown as { __cy: cytoscape.Core }).__cy = core; // exposed so the rendered graph can be inspected in a browser check
    return () => core.destroy();
  }, [onSelect]);

  useEffect(() => {
    const core = cy.current;
    if (!core) return;
    core.batch(() => {
      core.elements().remove();
      core.add(nodes.map((n) => ({ group: "nodes" as const, data: { id: n.key, label: n.label, status: n.status, color: COLORS[n.status] }, position: position(n.key) })));
      core.add(
        edges.map((e) => ({
          group: "edges" as const,
          data: {
            id: `e:${e.key}:${e.status}`, key: e.key, source: e.source, target: e.target, status: e.status,
            color: COLORS[e.status], width: 1 + e.confidence * 5, clabel: e.confidence.toFixed(2),
          },
        })),
      );
    });
    core.fit(undefined, 50);
  }, [nodes, edges]);

  return <div ref={host} data-testid="graph-canvas" className="h-[520px] w-full rounded border border-slate-800 bg-slate-950" />;
}
