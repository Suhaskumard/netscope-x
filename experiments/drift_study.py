"""Longitudinal drift study over a simulated multi-week evolving topology (spec addendum Phase 105).

WHAT THIS IS: a synthetic network whose services and edges change week by week (seeded, deterministic), run through the real pipeline
(`run_matrix_cell`) every week with the DEFAULT constants, measuring how the matrix metrics move; and, at checkpoint weeks, the real
Phase 82 `calibrate()` run on that week's network to find out whether recalibration would measurably help.
WHAT THIS IS NOT: evidence about a real network's evolution. The weekly change process is an assumption, network size grows as a
side effect (reported as a covariate, never hidden), and only checkpoint weeks are tested for recalibration.

Drift per metric: Theil-Sen slope with CI and a Kendall tau p-value over weekly means; the week-0 seed mean as the reference and
the within-week seed stdev pooled over all weeks as the noise yardstick; "first sustained degradation" = earliest week the metric is
worse than the reference by more than that spread for two consecutive weeks (Phase 82 compares against seed spread too). Recalibration is "necessary" at a checkpoint only if the pre-registered Phase 82
rule adopts a group on validation seeds disjoint from the tuning seeds (gain > baseline seed spread, no guard metric regressing).
"""

from __future__ import annotations

import json
import random
import shutil
import statistics
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import networkx as nx
from scipy import stats

from backend.app.models.behavior import ServiceRole
from backend.app.models.metric import MetricContext
from experiments.calibration.calibrate import Evaluator, calibrate, cell_set, decide
from experiments.calibration.constants import CalibrationConstants
from experiments.matrix_runner import OBSERVATION_COMPLETENESS_LEVELS, SENSITIVITY_SWEEP, run_matrix_cell
from simulator.scenarios.topologies import ScenarioEdge, dynamic_service_network

Scenario = Tuple[Dict[str, ServiceRole], List[ScenarioEdge]]
ROOT_NODE = "svc-1"  # the CLIENT that originates traffic; never retired
_ROLES = [ServiceRole.API, ServiceRole.CACHE, ServiceRole.DATABASE, ServiceRole.WORKER]
METRICS = ("topology_f1", "temporal_f1", "causal_f1", "role_calibration_error")
HIGHER_IS_WORSE = {"role_calibration_error"}
DRIFT_COMPLETENESS = (1.0, 0.5)
DRIFT_SEEDS = tuple(range(42, 47))
CHECKPOINT_WEEKS = (0, 6, 11)


def _connected(roles: Dict[str, ServiceRole], edges: Sequence[ScenarioEdge]) -> bool:
    g = nx.Graph()
    g.add_nodes_from(roles)
    g.add_edges_from((e.source, e.target) for e in edges)
    return nx.is_connected(g)


def _edge(a: str, b: str) -> ScenarioEdge:
    return ScenarioEdge(a, b, ["HTTP", "TCP"])


def _step(roles: Dict[str, ServiceRole], edges: List[ScenarioEdge], next_id: int, rng: random.Random):
    """One week of change: retire ~1 service, add 1-2, rewire ~1 edge, change ~1 role. Connectivity is preserved."""
    roles, edges = dict(roles), list(edges)
    removable = [n for n in roles if n != ROOT_NODE]
    rng.shuffle(removable)
    if len(roles) > 5:
        for cand in removable[:10]:
            rest = {n: r for n, r in roles.items() if n != cand}
            kept = [e for e in edges if cand not in (e.source, e.target)]
            if _connected(rest, kept):
                roles, edges = rest, kept
                break
    for _ in range(rng.choice([1, 2])):
        name = f"svc-{next_id}"
        next_id += 1
        anchors = rng.sample(sorted(roles), k=2 if rng.random() < 0.5 and len(roles) > 1 else 1)
        roles[name] = rng.choice(_ROLES)
        edges += [_edge(a, name) for a in anchors]
    if edges:
        victim = rng.choice(edges)
        kept = [e for e in edges if e is not victim]
        if _connected(roles, kept):
            existing = {frozenset((e.source, e.target)) for e in kept}
            for _ in range(20):
                a, b = rng.sample(sorted(roles), 2)
                if frozenset((a, b)) not in existing:
                    edges = kept + [_edge(a, b)]
                    break
    changeable = [n for n in roles if n != ROOT_NODE]
    if changeable:
        n = rng.choice(changeable)
        roles[n] = rng.choice([r for r in _ROLES if r != roles[n]])
    return roles, edges, next_id


def evolve_topology(week: int, seed: int = 7, n0: int = 8) -> Scenario:
    """The network as of `week` (0 = the initial network). Deterministic in (week, seed, n0)."""
    if week < 0:
        raise ValueError("week must be >= 0")
    roles, edges = dynamic_service_network(seed, n0)
    next_id = n0 + 1
    for w in range(1, week + 1):
        roles, edges, next_id = _step(roles, edges, next_id, random.Random(seed * 1000 + w))
    return roles, edges


class ScenarioEvaluator(Evaluator):
    """Phase 82's `Evaluator` with cells whose level label names an explicit scenario (a week of the evolving network)."""

    def __init__(self, scratch: Path, scenarios: Dict[str, Scenario]) -> None:
        super().__init__(scratch)
        self.scenarios = scenarios

    def cell(self, constants: CalibrationConstants, seed: int, cell) -> Dict[MetricContext, Optional[float]]:
        key = (tuple(constants.as_dict().values()), seed, cell)
        if key not in self._cache:
            label, completeness, low = cell
            kwargs = ({"variant": SENSITIVITY_SWEEP["variant"], "packets_per_edge": SENSITIVITY_SWEEP["packets_per_edge"],
                       "pulse_cycles": SENSITIVITY_SWEEP["pulse_cycles"]} if low else {})
            self.scratch.mkdir(parents=True, exist_ok=True)
            work = Path(tempfile.mkdtemp(dir=self.scratch))
            try:
                result = run_matrix_cell(work, label, completeness, seed=seed, constants=constants, evaluate_anomaly=False,
                                         scenario=self.scenarios[label], **kwargs)
            finally:
                shutil.rmtree(work, ignore_errors=True)
            self.cells_run += 1
            self._cache[key] = {m.context: m.f1 for m in result.metrics}
        return self._cache[key]


def week_label(week: int) -> str:
    return f"week-{week:02d}"


def measure_week(scratch: Path, week: int, scenario: Scenario, seeds: Sequence[int],
                 constants: Optional[CalibrationConstants] = None) -> Dict[str, Any]:
    """Real pipeline runs for one week with the default constants: per-seed metric values (mean over completeness levels)."""
    per_seed: Dict[str, List[float]] = {m: [] for m in METRICS}
    for seed in seeds:
        acc: Dict[str, List[float]] = {m: [] for m in METRICS}
        for c in DRIFT_COMPLETENESS:
            scratch.mkdir(parents=True, exist_ok=True)
            work = Path(tempfile.mkdtemp(dir=scratch))
            try:
                cell = run_matrix_cell(work, week_label(week), c, seed=seed, constants=constants, evaluate_anomaly=False, scenario=scenario)
            finally:
                shutil.rmtree(work, ignore_errors=True)
            for m in cell.metrics:
                if m.context == MetricContext.TOPOLOGY_RECONSTRUCTION and m.f1 is not None:
                    acc["topology_f1"].append(m.f1)
                elif m.context == MetricContext.TEMPORAL_ANALYSIS and m.f1 is not None:
                    acc["temporal_f1"].append(m.f1)
                elif m.context == MetricContext.CAUSAL_ANALYSIS and m.f1 is not None:
                    acc["causal_f1"].append(m.f1)
                elif m.context == MetricContext.ROLE_INFERENCE and m.calibration_error is not None:
                    acc["role_calibration_error"].append(m.calibration_error)
        for name, vals in acc.items():
            if vals:
                per_seed[name].append(statistics.fmean(vals))
    return {"week": week, "nodes": len(scenario[0]), "edges": len(scenario[1]), "per_seed": per_seed}


def first_sustained_degradation(means: Sequence[float], ref_mean: float, ref_spread: float, higher_is_worse: bool = False,
                                run_length: int = 2) -> Optional[int]:
    """Earliest week index w >= 1 from which `run_length` consecutive weeks are worse than the reference by more than its spread."""
    margin = max(ref_spread, 1e-9)

    def worse(v: float) -> bool:
        return v > ref_mean + margin if higher_is_worse else v < ref_mean - margin

    for w in range(1, len(means) - run_length + 1):
        if all(worse(means[w + k]) for k in range(run_length)):
            return w
    return None


def drift_stats(weeks: Sequence[int], series: Sequence[Sequence[float]], nodes: Sequence[int], higher_is_worse: bool = False) -> Dict[str, Any]:
    """`series[i]` = per-seed values for weeks[i]. Reference = week 0's seed mean and stdev."""
    means = [statistics.fmean(v) for v in series]
    ref_mean = statistics.fmean(series[0])
    # Seed spread = within-week stdev pooled over all weeks: one week's 4-5 seeds give a stdev too noisy to serve as a yardstick
    # (it produced false "sustained degradation" on a planted flat series).
    variances = [statistics.variance(v) for v in series if len(v) >= 2]
    ref_spread = statistics.fmean(variances) ** 0.5 if variances else 0.0
    out: Dict[str, Any] = {"weekly_mean": means, "weekly_stdev": [statistics.stdev(v) if len(v) >= 2 else 0.0 for v in series],
                           "reference_mean": ref_mean, "reference_spread": ref_spread}  # reference_mean = week 0; spread = pooled seed stdev
    if len(set(means)) < 2:
        out.update(slope_per_week=0.0, slope_ci95=[0.0, 0.0], kendall_tau=None, kendall_p=None, trend="flat (constant series)")
    else:
        slope, _, lo, hi = stats.theilslopes(means, list(weeks), alpha=0.95)
        tau = stats.kendalltau(list(weeks), means)
        worsening = slope > 0 if higher_is_worse else slope < 0
        significant = tau.pvalue < 0.05 and (lo > 0 or hi < 0)
        out.update(slope_per_week=float(slope), slope_ci95=[float(lo), float(hi)], kendall_tau=float(tau.statistic), kendall_p=float(tau.pvalue),
                   trend=("significant worsening" if worsening else "significant improvement") if significant else "no significant trend")
    if len(set(nodes)) > 1 and len(set(means)) > 1:
        rho = stats.spearmanr(list(nodes), means)
        out["spearman_vs_node_count"] = {"rho": float(rho.statistic), "p": float(rho.pvalue)}
    idx = first_sustained_degradation(means, ref_mean, ref_spread, higher_is_worse)
    out["first_sustained_degradation_week"] = None if idx is None else int(weeks[idx])
    return out


def _summarize_checkpoint(week: int, report) -> Dict[str, Any]:
    groups = []
    for g in report.groups:
        groups.append({"group": g.group, "objective": g.objective, "validation_baseline": g.validation_baseline,
                       "validation_tuned": g.validation_tuned, "gain": g.decision.objective_gain,
                       "baseline_spread": g.decision.baseline_spread, "adopt": g.decision.adopt, "reasons": g.decision.reasons,
                       "constants": [{"name": c.name, "default": c.default, "tuned": c.tuned} for c in g.constants]})
    return {"week": week, "recalibration_necessary": any(g["adopt"] for g in groups), "groups": groups,
            "adopted_constants": report.adopted.as_dict(), "cells_run": report.cells_run}


def checkpoint_calibration(root: Path, week: int, scenarios: Dict[str, Scenario], n_init: int, n_iter: int,
                           train_seeds: Sequence[int], validation_seeds: Sequence[int]) -> Dict[str, Any]:
    label = week_label(week)
    evaluator = ScenarioEvaluator(root / "drift" / "scratch", scenarios)
    report = calibrate(root, train_seeds=train_seeds, validation_seeds=validation_seeds,
                       train_cells=cell_set([label]), validation_cells=cell_set([label], OBSERVATION_COMPLETENESS_LEVELS),
                       n_init=n_init, n_iter=n_iter, evaluator=evaluator)
    return _summarize_checkpoint(week, report)


def stale_check(root: Path, adopted: CalibrationConstants, week: int, scenario: Scenario, seeds: Sequence[int]) -> Dict[str, Any]:
    """Would constants adopted at an earlier checkpoint beat the defaults at this later week? Same-seed paired comparison."""
    label = week_label(week)
    ev = ScenarioEvaluator(root / "drift" / "scratch", {label: scenario})
    cells = cell_set([label], OBSERVATION_COMPLETENESS_LEVELS)
    base, tuned = ev.scores(CalibrationConstants(), seeds, cells), ev.scores(adopted, seeds, cells)
    out = {}
    for ctx in base:
        b, t = base[ctx], tuned[ctx]
        spread = statistics.stdev(b) if len(b) >= 2 else 0.0
        out[ctx.value] = {"default": statistics.fmean(b), "adopted": statistics.fmean(t), "gain": statistics.fmean(t) - statistics.fmean(b),
                          "default_seed_spread": spread}
    # The Phase 82 rule, applied to the carried-over constants: any stage objective improving beyond its seed spread, no other regressing.
    decisions = {ctx.value: decide(base, tuned, ctx, [g for g in base if g != ctx]) for ctx in base}
    return {"week": week, "contexts": out, "would_adopt": any(d.adopt for d in decisions.values()),
            "adopt_reasons": {k: d.reasons for k, d in decisions.items() if d.adopt}}


def render_markdown(report: Dict[str, Any]) -> str:
    cfg = report["config"]
    lines = ["# Longitudinal drift study (Phase 105)", "",
             f"> Synthetic: a seeded weekly change process over {cfg['weeks']} weeks (start {cfg['n0']} services), run through the real pipeline "
             f"with DEFAULT constants; {len(cfg['seeds'])} traffic seeds x completeness {cfg['completeness']}. Not evidence about a real network. "
             "Network size grows as a side effect and is reported as a covariate.", "",
             "| week | nodes | edges | topology F1 | temporal F1 | causal F1 | role cal. error |", "|---|---|---|---|---|---|---|"]
    for i, w in enumerate(report["weekly"]):
        ms = [report["drift"][m]["weekly_mean"][i] for m in METRICS]
        lines.append(f"| {w['week']} | {w['nodes']} | {w['edges']} | " + " | ".join(f"{v:.4f}" for v in ms) + " |")
    lines += ["", "## Drift per metric", ""]
    for m in METRICS:
        d = report["drift"][m]
        sp = d.get("spearman_vs_node_count")
        lines.append(f"- **{m}**: {d['trend']}; Theil-Sen slope {d['slope_per_week']:+.5f}/week, CI {d['slope_ci95'][0]:+.5f}..{d['slope_ci95'][1]:+.5f}; "
                     f"Kendall p={d['kendall_p'] if d['kendall_p'] is None else round(d['kendall_p'], 4)}; reference {d['reference_mean']:.4f} ± {d['reference_spread']:.4f}; "
                     f"first sustained degradation week: {d['first_sustained_degradation_week']}"
                     + (f"; vs node count rho={sp['rho']:+.2f} (p={sp['p']:.3g})" if sp else ""))
    lines += ["", "## Recalibration checkpoints (real Phase 82 `calibrate()` on that week's network)", ""]
    for c in report.get("checkpoints", []):
        lines.append(f"### Week {c['week']}: recalibration {'NECESSARY' if c['recalibration_necessary'] else 'not necessary'}")
        for g in c["groups"]:
            lines.append(f"- {g['group']}: {g['objective']} validation {g['validation_baseline']:.4f} -> {g['validation_tuned']:.4f} "
                         f"(gain {g['gain']:+.4f} vs spread {g['baseline_spread']:.4f}) — {'adopt' if g['adopt'] else 'keep defaults'}")
        lines.append("")
    for s in report.get("stale_checks", []):
        lines.append(f"Stale check week {s['week']} (constants adopted at the first necessary checkpoint vs defaults): "
                     + "; ".join(f"{k} {v['gain']:+.4f} (spread {v['default_seed_spread']:.4f})" for k, v in s["contexts"].items())
                     + f" — Phase 82 rule would {'ADOPT' if s['would_adopt'] else 'keep defaults'}")
    lines += ["", f"Weeks where recalibration is supported by evidence (checkpoint adoption or carried-over constants passing the rule): {report['recalibration_necessary_weeks']}", "",
              f"Resolution limit: recalibration was only tested at weeks {cfg['checkpoints']}."]
    return "\n".join(lines) + "\n"


def run_drift_study(root: Path, weeks: int = 12, seeds: Sequence[int] = DRIFT_SEEDS, checkpoints: Sequence[int] = CHECKPOINT_WEEKS,
                    n0: int = 8, topo_seed: int = 7, n_init: int = 5, n_iter: int = 8,
                    train_seeds: Sequence[int] = (42, 43, 44), validation_seeds: Sequence[int] = (100, 101, 102, 103)) -> Dict[str, Any]:
    scenarios = {week_label(w): evolve_topology(w, topo_seed, n0) for w in range(weeks)}
    scratch = root / "drift" / "scratch"
    weekly = [measure_week(scratch, w, scenarios[week_label(w)], seeds) for w in range(weeks)]
    week_ids = [w["week"] for w in weekly]
    nodes = [w["nodes"] for w in weekly]
    drift = {m: drift_stats(week_ids, [w["per_seed"][m] for w in weekly], nodes, m in HIGHER_IS_WORSE) for m in METRICS}
    checkpoints_out: List[Dict[str, Any]] = []
    stale: List[Dict[str, Any]] = []
    first_adopted: Optional[Dict[str, Any]] = None
    for w in sorted(c for c in checkpoints if c < weeks):
        cp = checkpoint_calibration(root, w, scenarios, n_init, n_iter, train_seeds, validation_seeds)
        checkpoints_out.append(cp)
        if first_adopted is None and cp["recalibration_necessary"]:
            first_adopted = cp
        elif first_adopted is not None and w > first_adopted["week"]:
            stale.append(stale_check(root, CalibrationConstants(**first_adopted["adopted_constants"]), w, scenarios[week_label(w)], validation_seeds))
    necessary = sorted({c["week"] for c in checkpoints_out if c["recalibration_necessary"]} | {x["week"] for x in stale if x["would_adopt"]})
    report = {"config": {"weeks": weeks, "n0": n0, "topo_seed": topo_seed, "seeds": list(seeds), "completeness": list(DRIFT_COMPLETENESS),
                         "checkpoints": list(checkpoints), "train_seeds": list(train_seeds), "validation_seeds": list(validation_seeds),
                         "bo": {"n_init": n_init, "n_iter": n_iter}},
              "weekly": [{k: v for k, v in w.items() if k != "per_seed"} for w in weekly], "per_seed": {m: [w["per_seed"][m] for w in weekly] for m in METRICS},
              "drift": drift, "checkpoints": checkpoints_out, "stale_checks": stale,
              "first_week_recalibration_necessary": None if first_adopted is None else first_adopted["week"],
              "recalibration_necessary_weeks": necessary}
    out = root / "drift"
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    (out / "report.md").write_text(render_markdown(report), encoding="utf-8")
    return report
