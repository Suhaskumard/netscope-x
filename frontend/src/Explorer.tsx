import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ApiError, eventsBetween, listSnapshots, snapshotTopology,
  type ApiOptions, type ChangeEvent, type Snapshot, type TopologyGraph,
} from "./api";
import { buildView, nodeKey } from "./diff";
import GraphView from "./GraphView";

const fmt = (iso: string): string => iso.replace("T", " ").replace(/\+00:00$|Z$/, " UTC");

export default function Explorer(): JSX.Element {
  const params = new URLSearchParams(window.location.search);
  const opt: ApiOptions = useMemo(
    () => ({ base: params.get("base") ?? "", token: params.get("token") ?? undefined, tenantKey: params.get("tenant") ?? undefined }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );
  const [captureId, setCaptureId] = useState(params.get("capture") ?? "");
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [index, setIndex] = useState(0);
  const [graphs, setGraphs] = useState<Record<number, TopologyGraph>>({});
  const [events, setEvents] = useState<ChangeEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [selected, setSelected] = useState<{ kind: "node" | "edge"; key: string } | null>(null);
  const [diffOn, setDiffOn] = useState(true);

  const load = useCallback(async () => {
    if (!captureId) return;
    setLoading(true);
    setError(null);
    setGraphs({});
    try {
      const list = await listSnapshots(captureId, opt);
      setSnapshots(list);
      setIndex(list.length ? list.length - 1 : 0);
    } catch (e) {
      setError(e instanceof ApiError ? `${e.status} ${e.code}: ${e.message}` : String(e));
      setSnapshots([]);
    } finally {
      setLoading(false);
    }
  }, [captureId, opt]);

  useEffect(() => {
    if (params.get("capture")) void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const current = snapshots[index];
  const previous = index > 0 ? snapshots[index - 1] : undefined;

  useEffect(() => {
    if (!current) return;
    let cancelled = false;
    (async () => {
      try {
        const need = [current, ...(previous ? [previous] : [])].filter((s) => !graphs[s.version]);
        const fetched = await Promise.all(need.map(async (s) => [s.version, await snapshotTopology(captureId, s.version, opt)] as const));
        if (cancelled) return;
        if (fetched.length) setGraphs((g) => ({ ...g, ...Object.fromEntries(fetched) }));
        setEvents(previous ? await eventsBetween(captureId, current.snapshot_id, opt) : []);
      } catch (e) {
        if (!cancelled) setError(e instanceof ApiError ? `${e.status} ${e.code}: ${e.message}` : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [current, previous, captureId, opt, graphs]);

  useEffect(() => {
    if (!playing) return;
    if (index >= snapshots.length - 1) {
      setPlaying(false);
      return;
    }
    const t = setTimeout(() => setIndex((i) => i + 1), 1200);
    return () => clearTimeout(t);
  }, [playing, index, snapshots.length]);

  const graph = current ? graphs[current.version] : undefined;
  const prevGraph = previous ? graphs[previous.version] ?? null : null;
  const ready = graph && (!previous || prevGraph);
  const view = useMemo(() => (graph ? buildView(graph, diffOn && prevGraph ? prevGraph : null) : { nodes: [], edges: [] }), [graph, prevGraph, diffOn]);
  const onSelect = useCallback((s: { kind: "node" | "edge"; key: string } | null) => setSelected(s), []);

  const t0 = snapshots.length ? Date.parse(snapshots[0].captured_at) : 0;
  const span = snapshots.length > 1 ? Date.parse(snapshots[snapshots.length - 1].captured_at) - t0 : 1;

  const detail = (() => {
    if (!selected || !graph) return null;
    if (selected.kind === "node") {
      const n = graph.nodes.find((x) => nodeKey(graph, x.node_id) === selected.key);
      return n ? { title: `Node ${n.ip_addresses.join(", ")}`, rows: [["first observed", fmt(n.first_observed)], ["last observed", fmt(n.last_observed)]], evidence: [] as string[] } : null;
    }
    const e = graph.edges.find((x) => [nodeKey(graph, x.source_node_id), nodeKey(graph, x.target_node_id)].sort().join("|") === selected.key);
    return e ? { title: `Edge ${e.source_node_id} - ${e.target_node_id}`, rows: [["confidence", e.confidence.toFixed(4)], ["observations", String(e.observation_count)], ["protocols", e.protocols.join(", ")], ["first observed", fmt(e.first_observed)], ["last observed", fmt(e.last_observed)]], evidence: e.evidence } : null;
  })();

  return (
    <main className="min-h-screen bg-slate-950 p-6 text-slate-100">
      <header className="mb-4 flex flex-wrap items-end gap-3">
        <h1 className="text-xl font-semibold tracking-tight">NETSCOPE-X · Topology explorer</h1>
        <form className="ml-auto flex gap-2" onSubmit={(e) => { e.preventDefault(); void load(); }}>
          <input data-testid="capture-input" value={captureId} onChange={(e) => setCaptureId(e.target.value.trim())} placeholder="capture id" className="w-80 rounded border border-slate-700 bg-slate-900 px-2 py-1 text-sm" />
          <button data-testid="load" className="rounded bg-sky-600 px-3 py-1 text-sm font-medium hover:bg-sky-500" disabled={!captureId || loading}>{loading ? "Loading…" : "Load"}</button>
        </form>
      </header>

      {error && <p data-testid="error" className="mb-3 rounded border border-red-800 bg-red-950 p-2 text-sm text-red-300">{error}</p>}
      {!error && !loading && captureId && snapshots.length === 0 && <p data-testid="empty" className="text-sm text-slate-400">No snapshots recorded for this capture yet.</p>}

      {current && (
        <>
          <section className="mb-4 rounded border border-slate-800 bg-slate-900 p-3">
            <div className="mb-2 flex flex-wrap items-center gap-3 text-sm">
              <button data-testid="step-back" className="rounded bg-slate-700 px-2 py-1 disabled:opacity-40" disabled={index === 0} onClick={() => { setPlaying(false); setIndex(index - 1); }}>◀ Earlier</button>
              <button data-testid="play" className="rounded bg-slate-700 px-2 py-1" onClick={() => { if (index >= snapshots.length - 1) setIndex(0); setPlaying((p) => !p); }}>{playing ? "Pause" : "Play"}</button>
              <button data-testid="step-forward" className="rounded bg-slate-700 px-2 py-1 disabled:opacity-40" disabled={index >= snapshots.length - 1} onClick={() => { setPlaying(false); setIndex(index + 1); }}>Later ▶</button>
              <span data-testid="snapshot-label" className="font-mono text-slate-300">snapshot v{current.version} · {fmt(current.captured_at)} · {current.snapshot_id}</span>
              <label className="ml-auto flex items-center gap-1 text-slate-400"><input data-testid="diff-toggle" type="checkbox" checked={diffOn} onChange={(e) => setDiffOn(e.target.checked)} /> highlight changes vs previous</label>
            </div>
            <div className="relative mx-2 h-10">
              <div className="absolute left-0 right-0 top-4 h-0.5 bg-slate-700" />
              {snapshots.map((s, i) => {
                const pct = snapshots.length > 1 ? ((Date.parse(s.captured_at) - t0) / span) * 100 : 50;
                return (
                  <button key={s.version} data-testid={`snapshot-tick-${s.version}`} title={`v${s.version} ${fmt(s.captured_at)}`} onClick={() => { setPlaying(false); setIndex(i); }}
                    style={{ left: `${pct}%` }} className={`absolute top-2 h-5 w-5 -translate-x-1/2 rounded-full border-2 text-[10px] leading-none ${i === index ? "border-sky-300 bg-sky-500" : "border-slate-500 bg-slate-800 hover:bg-slate-600"}`}>{s.version}</button>
                );
              })}
            </div>
          </section>

          {!ready ? <p className="text-sm text-slate-400">Loading snapshot…</p> : (
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_320px]">
              <div>
                <GraphView nodes={view.nodes} edges={view.edges} onSelect={onSelect} />
                <p className="mt-2 text-sm text-slate-300">
                  <span data-testid="node-count">{graph.nodes.length}</span> nodes ·{" "}
                  <span data-testid="edge-count">{graph.edges.length}</span> edges at this snapshot
                  {diffOn && previous && <span className="text-slate-500"> (dashed = present in the previous snapshot, gone now)</span>}
                </p>
              </div>
              <aside className="space-y-3 text-sm">
                {previous && diffOn && (
                  <div data-testid="diff-panel" className="rounded border border-slate-800 bg-slate-900 p-3">
                    <h2 className="mb-1 font-medium">Since v{previous.version}</h2>
                    <p className="text-slate-300">
                      <span className="text-green-400">+{view.nodes.filter((n) => n.status === "added").length} nodes</span>,{" "}
                      <span className="text-green-400">+{view.edges.filter((e) => e.status === "added").length} edges</span>,{" "}
                      <span className="text-red-400">−{view.nodes.filter((n) => n.status === "removed").length} nodes</span>,{" "}
                      <span className="text-red-400">−{view.edges.filter((e) => e.status === "removed").length} edges</span>,{" "}
                      <span className="text-amber-400">{view.edges.filter((e) => e.status === "changed").length} confidence changes</span>
                    </p>
                    <ul data-testid="event-list" className="mt-2 max-h-48 space-y-1 overflow-auto text-xs text-slate-400">
                      {events.map((ev) => <li key={ev.event_id}><b className="text-slate-300">{ev.change_type}</b> {ev.affected_node_id ?? ev.affected_edge_id}{ev.attribute_name ? ` ${ev.attribute_name}: ${ev.previous_value} → ${ev.new_value}` : ""}</li>)}
                      {events.length === 0 && <li>No recorded change events.</li>}
                    </ul>
                  </div>
                )}
                <div className="rounded border border-slate-800 bg-slate-900 p-3" data-testid="detail">
                  {detail ? (
                    <>
                      <h2 className="mb-1 font-medium">{detail.title}</h2>
                      <dl className="grid grid-cols-[auto_1fr] gap-x-3 text-xs text-slate-300">{detail.rows.map(([k, v]) => <><dt key={k} className="text-slate-500">{k}</dt><dd>{v}</dd></>)}</dl>
                      {detail.evidence.length > 0 && <ul className="mt-2 list-disc pl-4 text-xs text-slate-400">{detail.evidence.map((x, i) => <li key={i}>{x}</li>)}</ul>}
                    </>
                  ) : <p className="text-xs text-slate-500">Click a node or edge for its evidence.</p>}
                </div>
              </aside>
            </div>
          )}
        </>
      )}
    </main>
  );
}
