import { useEffect, useMemo, useState } from "react";
import { ApiError, type ApiOptions } from "./api";
import {
  compareExperiments, experimentDetail, listExperiments, startExperimentRun, streamRunEvents,
  type CompareRow, type ExperimentDetail, type ExperimentRow, type RunEvent,
} from "./labApi";

// Mirrors experiments/matrix_runner.py's whitelist; the server re-validates every value.
const TOPOLOGIES = ["small", "medium", "large", "multi_path", "multi_service", "dynamic"];
const COMPLETENESS = [1.0, 0.9, 0.75, 0.5, 0.25];
const ABLATIONS = ["without_temporal", "without_dependency_weighting", "without_confidence_modeling", "without_behavioral"];
const METRICS = ["precision", "recall", "f1", "false_positive_rate", "false_negative_rate", "detection_latency_seconds", "graph_similarity", "calibration_error"];
const fmt = (v: unknown): string => (typeof v === "number" ? v.toFixed(4) : v === null || v === undefined ? "not recorded" : String(v));
const msg = (e: unknown): string => (e instanceof ApiError ? `${e.status}: ${e.message}` : String(e));

function Section({ title, children, testid }: { title: string; children: React.ReactNode; testid: string }): JSX.Element {
  return (
    <section data-testid={testid} className="mb-4">
      <h3 className="mb-1 text-sm font-semibold uppercase tracking-wide text-slate-400">{title}</h3>
      {children}
    </section>
  );
}

const Json = ({ v }: { v: unknown }): JSX.Element => (
  <pre className="max-h-64 overflow-auto rounded bg-slate-900 p-2 text-xs text-slate-300">{JSON.stringify(v, null, 2)}</pre>
);

/** Phase 102 Experiment Lab: experiment, hypothesis, setup, result, metrics, comparison, and a live run. Real data only. */
export default function ExperimentLab(): JSX.Element {
  const params = new URLSearchParams(window.location.search);
  const opt: ApiOptions = useMemo(
    () => ({ base: params.get("base") ?? "", token: params.get("token") ?? undefined, tenantKey: params.get("tenant") ?? undefined }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );
  const [rows, setRows] = useState<ExperimentRow[] | null>(null);
  const [selected, setSelected] = useState<string | null>(params.get("experiment"));
  const [detail, setDetail] = useState<ExperimentDetail | null>(null);
  const [cmpB, setCmpB] = useState("");
  const [cmp, setCmp] = useState<CompareRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({ topology_level: "small", completeness: 1.0, ablation: "", seed: 42 });
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  const refresh = (): Promise<void> => listExperiments(opt).then(setRows).catch((e) => setError(msg(e)));
  useEffect(() => {
    void refresh();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!selected) return;
    let cancelled = false;
    setDetail(null);
    setCmp(null);
    experimentDetail(selected, opt)
      .then((d) => !cancelled && setDetail(d))
      .catch((e) => !cancelled && setError(msg(e)));
    return () => {
      cancelled = true;
    };
  }, [selected, opt]);

  const compare = (): void => {
    if (!selected || !cmpB) return;
    compareExperiments(selected, cmpB, opt).then(setCmp).catch((e) => setError(msg(e)));
  };

  const run = async (): Promise<void> => {
    setRunError(null);
    setEvents([]);
    setRunning(true);
    try {
      const jobId = await startExperimentRun({ ...form, ablation: form.ablation || null }, opt);
      let doneId: string | null = null;
      await streamRunEvents(jobId, opt, (e) => {
        setEvents((prev) => [...prev, e]);
        if (e.event === "done") doneId = String(e.data.experiment_id);
        if (e.event === "error") setRunError(`run failed: ${String(e.data.error)}`);
      });
      await refresh();
      if (doneId) setSelected(doneId);
    } catch (e) {
      setRunError(msg(e));
    } finally {
      setRunning(false);
    }
  };

  return (
    <main className="grid grid-cols-[18rem_1fr] gap-4 p-4 text-sm text-slate-200" data-testid="lab">
      <aside>
        <h2 className="mb-2 font-semibold">Experiments</h2>
        {rows === null && !error && <p>Loading…</p>}
        {rows !== null && rows.length === 0 && <p data-testid="lab-empty">No experiments recorded.</p>}
        <ul className="max-h-96 overflow-auto">
          {rows?.map((r) => (
            <li key={r.experiment_id}>
              <button data-testid="exp-row" className={`w-full truncate py-0.5 text-left ${r.experiment_id === selected ? "text-sky-300" : ""}`} onClick={() => setSelected(r.experiment_id)}>
                {r.experiment_id}
              </button>
            </li>
          ))}
        </ul>
        <h2 className="mb-1 mt-4 font-semibold">Run a cell</h2>
        <div className="flex flex-col gap-1 text-slate-900">
          <select data-testid="run-topology" value={form.topology_level} onChange={(e) => setForm({ ...form, topology_level: e.target.value })}>
            {TOPOLOGIES.map((t) => <option key={t}>{t}</option>)}
          </select>
          <select data-testid="run-completeness" value={form.completeness} onChange={(e) => setForm({ ...form, completeness: Number(e.target.value) })}>
            {COMPLETENESS.map((c) => <option key={c}>{c}</option>)}
          </select>
          <select data-testid="run-ablation" value={form.ablation} onChange={(e) => setForm({ ...form, ablation: e.target.value })}>
            <option value="">no ablation</option>
            {ABLATIONS.map((a) => <option key={a}>{a}</option>)}
          </select>
          <input data-testid="run-seed" type="number" min={0} max={999} value={form.seed} onChange={(e) => setForm({ ...form, seed: Number(e.target.value) })} />
          <button data-testid="run-start" disabled={running} onClick={() => void run()} className="rounded bg-sky-600 px-2 py-1 text-white disabled:opacity-50">
            {running ? "Running…" : "Start run"}
          </button>
        </div>
        {runError && <p data-testid="run-error" className="mt-1 text-rose-400">{runError}</p>}
        <ol data-testid="run-events" className="mt-2 text-xs text-slate-400">
          {events.map((e, i) => <li key={i}>{e.event}{e.event === "progress" ? ` ${String(e.data.elapsed_seconds)}s` : ""}</li>)}
        </ol>
      </aside>
      <div>
        {error && <p data-testid="lab-error" className="text-rose-400">{error}</p>}
        {!selected && !error && <p>Select an experiment.</p>}
        {selected && !detail && !error && <p>Loading…</p>}
        {detail && (
          <>
            <Section title="Experiment" testid="sec-experiment"><Json v={detail.experiment} /></Section>
            <Section title="Hypothesis" testid="sec-hypothesis"><p>{detail.hypothesis ?? "Not recorded: the experiment record has no hypothesis field."}</p></Section>
            <Section title="Setup" testid="sec-setup"><Json v={detail.setup} /></Section>
            <Section title="Result" testid="sec-result"><Json v={detail.result} /></Section>
            <Section title="Metrics" testid="sec-metrics">
              <table className="text-xs">
                <thead><tr><th className="pr-3 text-left">context</th>{METRICS.map((m) => <th key={m} className="pr-3 text-left">{m}</th>)}</tr></thead>
                <tbody>
                  {detail.metrics.map((m) => (
                    <tr key={m.metric_id}><td className="pr-3">{m.context}</td>{METRICS.map((f) => <td key={f} className="pr-3">{fmt(m[f])}</td>)}</tr>
                  ))}
                </tbody>
              </table>
            </Section>
            <Section title="Comparison" testid="sec-compare">
              <select className="text-slate-900" data-testid="cmp-b" value={cmpB} onChange={(e) => setCmpB(e.target.value)}>
                <option value="">compare with…</option>
                {rows?.filter((r) => r.experiment_id !== selected).map((r) => <option key={r.experiment_id}>{r.experiment_id}</option>)}
              </select>
              <button data-testid="cmp-go" className="ml-2 rounded bg-slate-700 px-2" onClick={compare}>Compare</button>
              {cmp && (cmp.length === 0 ? <p>No metric present in both runs.</p> : (
                <table data-testid="cmp-table" className="mt-2 text-xs">
                  <thead><tr><th className="pr-3 text-left">context</th><th className="pr-3 text-left">metric</th><th className="pr-3">A</th><th className="pr-3">B</th><th>B − A</th></tr></thead>
                  <tbody>
                    {cmp.map((r, i) => (
                      <tr key={i}><td className="pr-3">{r.context}</td><td className="pr-3">{r.metric}</td><td className="pr-3">{fmt(r.a)}</td><td className="pr-3">{fmt(r.b)}</td><td>{r.delta >= 0 ? "+" : ""}{r.delta.toFixed(4)}</td></tr>
                    ))}
                  </tbody>
                </table>
              ))}
            </Section>
          </>
        )}
      </div>
    </main>
  );
}
