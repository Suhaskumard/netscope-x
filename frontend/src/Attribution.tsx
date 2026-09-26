import { useEffect, useMemo, useState } from "react";
import { ApiError, attribution, listDependencies, type ApiOptions, type AttributionResult, type Dependency } from "./api";

const COLORS = ["#38bdf8", "#a78bfa", "#f472b6", "#fbbf24", "#34d399"];
const f4 = (x: number): string => x.toFixed(4);
const TOL = 1e-6;

export default function Attribution(): JSX.Element {
  const params = new URLSearchParams(window.location.search);
  const opt: ApiOptions = useMemo(
    () => ({ base: params.get("base") ?? "", token: params.get("token") ?? undefined, tenantKey: params.get("tenant") ?? undefined }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );
  const [captureId, setCaptureId] = useState(params.get("capture") ?? "");
  const [deps, setDeps] = useState<Dependency[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [data, setData] = useState<AttributionResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = async (): Promise<void> => {
    if (!captureId) return;
    setError(null);
    setData(null);
    try {
      setDeps(await listDependencies(captureId, opt));
    } catch (e) {
      setError(e instanceof ApiError ? `${e.status} ${e.code}: ${e.message}` : String(e));
    }
  };
  useEffect(() => {
    if (params.get("capture")) void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!selected) return;
    let cancelled = false;
    attribution(captureId, selected, opt)
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setError(e instanceof ApiError ? `${e.status} ${e.code}: ${e.message}` : String(e)));
    return () => {
      cancelled = true;
    };
  }, [selected, captureId, opt]);

  // The consistency check runs here, in the browser, on the numbers the API returned.
  const sum = data ? data.signals.reduce((a, s) => a + s.contribution, 0) : 0;
  const diff = data ? Math.abs(sum - data.stored_strength) : 0;
  const consistent = data ? diff < TOL && Math.abs(data.strength - data.stored_strength) < TOL : true;

  return (
    <main className="min-h-screen bg-slate-950 p-6 text-slate-100">
      <header className="mb-4 flex flex-wrap items-end gap-3">
        <h1 className="text-xl font-semibold tracking-tight">NETSCOPE-X · Causal attribution</h1>
        <form className="ml-auto flex gap-2" onSubmit={(e) => { e.preventDefault(); void load(); }}>
          <input data-testid="capture-input" value={captureId} onChange={(e) => setCaptureId(e.target.value.trim())} placeholder="capture id" className="w-80 rounded border border-slate-700 bg-slate-900 px-2 py-1 text-sm" />
          <button data-testid="load" className="rounded bg-sky-600 px-3 py-1 text-sm font-medium hover:bg-sky-500" disabled={!captureId}>Load</button>
        </form>
      </header>
      {error && <p data-testid="error" className="mb-3 rounded border border-red-800 bg-red-950 p-2 text-sm text-red-300">{error}</p>}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[300px_1fr]">
        <ul data-testid="dependency-list" className="max-h-[70vh] space-y-1 overflow-auto text-sm">
          {deps.map((d) => (
            <li key={d.dependency_id}>
              <button data-testid={`dep-${d.dependency_id}`} onClick={() => { setData(null); setSelected(d.dependency_id); }} className={`w-full rounded border px-2 py-1 text-left ${selected === d.dependency_id ? "border-sky-400 bg-slate-800" : "border-slate-800 bg-slate-900 hover:bg-slate-800"}`}>
                <span className="font-mono text-xs text-slate-400">{d.source_node_id.split(":").pop()} → {d.target_node_id.split(":").pop()}</span>
                <span className="float-right font-mono">{f4(d.strength)}</span>
              </button>
            </li>
          ))}
          {deps.length === 0 && !error && captureId && <li className="text-slate-500">No dependencies for this capture.</li>}
        </ul>

        {data ? (
          <section data-testid="attribution" data-dependency-id={data.dependency_id} className="space-y-4">
            <div className="rounded border border-slate-800 bg-slate-900 p-3">
              <p className="text-sm text-slate-300">{data.report.relationship}</p>
              <p className="mt-2 text-lg">
                Dependency strength <span data-testid="strength-value" className="font-mono font-semibold">{f4(data.stored_strength)}</span>
                <span data-testid="consistency" data-consistent={consistent} className={`ml-3 rounded px-2 py-0.5 text-xs ${consistent ? "bg-green-900 text-green-300" : "bg-red-900 text-red-300"}`}>
                  {consistent ? "Consistent: contributions sum to strength" : "Inconsistent"}
                </span>
              </p>
              <div data-testid="contrib-bar" className="mt-3 flex h-7 w-full overflow-hidden rounded bg-slate-800">
                {data.signals.map((s, i) => (
                  <div key={s.signal} title={`${s.label}: ${f4(s.contribution)}`} style={{ width: `${(s.contribution / Math.max(data.stored_strength, 1e-12)) * 100}%`, background: COLORS[i] }} />
                ))}
              </div>
              <p className="mt-1 text-xs text-slate-400">
                Σ contributions = <span data-testid="contrib-sum" className="font-mono">{f4(sum)}</span> · residual{" "}
                <span data-testid="residual" className="font-mono">{diff.toExponential(1)}</span>
              </p>
            </div>

            <table className="w-full text-sm" data-testid="signal-table">
              <thead className="text-left text-xs text-slate-400"><tr><th className="p-1">Signal</th><th>Raw value</th><th>Standalone probability</th><th>Contribution (Shapley)</th><th>Strength without it</th></tr></thead>
              <tbody>
                {data.signals.map((s, i) => (
                  <tr key={s.signal} className="border-t border-slate-800">
                    <td className="p-1"><span className="mr-2 inline-block h-2 w-2 rounded-full" style={{ background: COLORS[i] }} />{s.label}</td>
                    <td className="font-mono" data-testid={`raw-${s.signal}`}>{s.raw.toFixed(3)} <span className="text-slate-500">{s.unit}</span></td>
                    <td className="font-mono" data-testid={`term-${s.signal}`}>{f4(s.term)}</td>
                    <td className="font-mono font-semibold" data-testid={`contrib-${s.signal}`}>{f4(s.contribution)}</td>
                    <td className="font-mono" data-testid={`without-${s.signal}`}>{f4(s.without)}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            <div className="rounded border border-slate-800 bg-slate-900 p-3 text-xs text-slate-400">
              <p>
                Strength is a noisy-OR of five signals: 1 − Π(1 − tᵢ), with signal weight {data.parameters.signal_strength} on four of them (uncalibrated).
                Each contribution is the signal's exact Shapley value, its average marginal effect over every order the signals could be added, so the
                contributions add up to the strength. "Strength without it" removes that one signal. This explains the score; it does not prove causation.
              </p>
              {data.report.counter_evidence.length > 0 && <><h3 className="mt-2 font-medium text-slate-300">Counter-evidence</h3><ul className="list-disc pl-4">{data.report.counter_evidence.map((x, i) => <li key={i}>{x}</li>)}</ul></>}
              <h3 className="mt-2 font-medium text-slate-300">Limitations</h3>
              <ul className="list-disc pl-4">{data.report.limitations.map((x, i) => <li key={i}>{x}</li>)}</ul>
            </div>
          </section>
        ) : (
          <p className="text-sm text-slate-500">Select a dependency to see what drives its strength.</p>
        )}
      </div>
    </main>
  );
}
