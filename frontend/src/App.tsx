import Attribution from "./Attribution";
import ExperimentLab from "./ExperimentLab";
import Explorer from "./Explorer";

/** Phase 97 topology explorer, Phase 99 causal attribution and Phase 102 Experiment Lab, selected with ?view=topology|attribution|experiments. */
export default function App(): JSX.Element {
  const params = new URLSearchParams(window.location.search);
  const requested = params.get("view");
  const view = requested === "attribution" || requested === "experiments" ? requested : "topology";
  const link = (v: string): string => {
    const p = new URLSearchParams(window.location.search);
    p.set("view", v);
    return `?${p.toString()}`;
  };
  return (
    <>
      <nav className="flex gap-4 bg-slate-900 px-6 py-2 text-sm text-slate-300">
        <a data-testid="nav-topology" href={link("topology")} className={view === "topology" ? "font-semibold text-sky-300" : ""}>Topology</a>
        <a data-testid="nav-attribution" href={link("attribution")} className={view === "attribution" ? "font-semibold text-sky-300" : ""}>Causal attribution</a>
        <a data-testid="nav-experiments" href={link("experiments")} className={view === "experiments" ? "font-semibold text-sky-300" : ""}>Experiment Lab</a>
      </nav>
      {view === "attribution" ? <Attribution /> : view === "experiments" ? <ExperimentLab /> : <Explorer />}
    </>
  );
}
