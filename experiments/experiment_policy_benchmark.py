"""Benchmark: learned experiment policy vs Phase 67's static ranking (spec addendum Phase 80).

An *episode* is one digital twin (the matrix's own low-volume capture, `SENSITIVITY_SWEEP` settings, at a
completeness where edges are genuinely lost), one policy, and a budget of `BUDGET` controlled experiments.
Each step:

  1. the policy picks a node to fail;
  2. the twin's prediction for that experiment is scored against the REAL outcome with Phase 63's
     `evaluate_failure_propagation_prediction` (through the matrix's own `_evaluate_failure_target`, which also
     runs Phase 66's counterfactual comparison) -- the reward is `1 - affected_node_f1`, the twin's real
     prediction error, never synthesized;
  3. `repair_twin` corrects the twin from that same real outcome;
  4. the policy learns from the reward.

The real outcome comes from the declared topology (this repository has no Docker lab), the same substitute
Phases 68/73 use. Ground truth reaches only this harness, never the policy or the repair's decision logic
beyond the real outcome it is given.

Accuracy after every step is the mean Phase 63 affected-node F1 over every node as a failure target
(`a_all`), and over the nodes NOT experimented on (`a_held`, measured on the same final held-out set at the
start and the end, so a repair that merely fits the experiments it ran is not counted as learning). The
headline is accuracy gained per experiment actually run. Phase 66's counterfactual F1 is reported
alongside but is not part of the reward.

Policies (same twins, budget and scoring): `static` (Phase 67, computed once), `linucb` (pre-trained on other
topologies, then online), `linucb_cold` (no pre-training), `random`. Leave-one-topology-level-out: the
pre-training episodes use the other five levels and disjoint seeds; exploration alpha 1.0 and ridge 1.0 are
fixed in advance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import networkx as nx

from backend.app.models.topology import TopologyGraph
from backend.dependency.causal_candidates import CausalCandidate, generate_causal_candidates
from backend.dependency.experiment_policy import LinUCBPolicy, RandomPolicy, StaticPolicy, repair_twin
from backend.dependency.strength import estimate_dependency_strength
from backend.nettrace.reconstruct import reconstruct_flows
from backend.nettrace.topology.graph import build_topology_graph
from experiments.artifacts.io import write_jsonl
from experiments.artifacts.paths import packets_path
from experiments.matrix_runner import (
    _WAVE_GAP_SECONDS,
    SENSITIVITY_SWEEP,
    TOPOLOGY_LEVELS,
    _actual_outcome_from_ground_truth,
    _evaluate_failure_target,
    _ground_truth_nx,
    _name_to_node_id,
)
from experiments.metrics.summary_stats import MetricSummary, format_summary, summarize_values
from experiments.observation_sampling import sample_packets
from experiments.synthetic_traffic import assign_ips, generate_packets_for_scenario

BUDGET = 4
COMPLETENESS_LEVELS: List[float] = [0.75, 0.5, 0.25]
TRAIN_SEEDS: List[int] = list(range(100, 105))
TEST_SEEDS: List[int] = list(range(42, 52))
POLICIES: Tuple[str, ...] = ("static", "linucb", "linucb_cold", "random")
_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True)
class TwinCase:
    level: str
    completeness: float
    seed: int
    experiment_id: str
    graph: TopologyGraph  # the twin
    candidates: List[CausalCandidate]
    gt_nx: nx.Graph
    gt_pairs: frozenset  # declared edges as frozenset({name, name})
    name_to_node_id: Dict[str, str]
    node_id_to_name: Dict[str, str]


def build_twin_case(root: Path, level: str, completeness: float, seed: int) -> TwinCase:
    """The matrix's low-volume capture for (level, completeness, seed), reconstructed into a twin graph."""
    roles, edges = TOPOLOGY_LEVELS[level]()
    ip_by_name = assign_ips(list(roles))
    experiment_id = f"policy-{level}-{str(completeness).replace('.', 'p')}-{seed}"
    packets = generate_packets_for_scenario(
        roles, edges, ip_by_name, experiment_id, seed,
        packets_per_edge=SENSITIVITY_SWEEP["packets_per_edge"], wave_2_edges=max(1, len(edges) // 4),
        wave_gap_seconds=_WAVE_GAP_SECONDS, pulse_cycles=SENSITIVITY_SWEEP["pulse_cycles"],
    )
    write_jsonl(packets_path(root, experiment_id), sample_packets(packets, completeness, seed))
    reconstruct_flows(root, experiment_id)
    graph = build_topology_graph(root, experiment_id, graph_id=f"{experiment_id}-twin")
    candidates = generate_causal_candidates(estimate_dependency_strength(root, experiment_id))
    name_to_node_id = _name_to_node_id(graph.nodes, ip_by_name)
    return TwinCase(
        level=level, completeness=completeness, seed=seed, experiment_id=experiment_id, graph=graph,
        candidates=candidates, gt_nx=_ground_truth_nx(roles, edges),
        gt_pairs=frozenset(frozenset((e.source, e.target)) for e in edges),
        name_to_node_id=name_to_node_id, node_id_to_name={v: k for k, v in name_to_node_id.items()},
    )


def evaluate_experiment(case: TwinCase, graph: TopologyGraph, node_id: str) -> Tuple[float, float]:
    """(Phase 63 affected-node F1, Phase 66 counterfactual F1) of `graph`'s prediction for failing `node_id`,
    scored against the real outcome."""
    failure_eval, _, cf_eval, _ = _evaluate_failure_target(
        graph, case.gt_nx, case.candidates, case.name_to_node_id, case.node_id_to_name[node_id],
        case.experiment_id, _NOW,
    )
    return failure_eval.affected_node_f1, cf_eval.affected_node_f1


def _per_node_accuracy(case: TwinCase, graph: TopologyGraph) -> Dict[str, Tuple[float, float]]:
    return {n.node_id: evaluate_experiment(case, graph, n.node_id) for n in graph.nodes if n.node_id in case.node_id_to_name}


def _mean(values: Sequence[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


@dataclass(frozen=True)
class EpisodeResult:
    policy: str
    level: str
    completeness: float
    seed: int
    picks: List[str]
    rewards: List[float]  # 1 - Phase 63 F1 of each experiment, before its repair
    a_all_curve: List[float]  # step 0 .. n_experiments
    a_all_start: float
    a_all_end: float
    a_held_start: Optional[float]
    a_held_end: Optional[float]
    cf_all_start: float
    cf_all_end: float
    bridges_added: int
    bridges_real: int  # bridges that happen to be a real declared edge

    @property
    def n_experiments(self) -> int:
        return len(self.picks)

    @property
    def gain_all(self) -> float:
        return self.a_all_end - self.a_all_start

    @property
    def gain_all_per_experiment(self) -> Optional[float]:
        return self.gain_all / self.n_experiments if self.n_experiments else None

    @property
    def gain_held_per_experiment(self) -> Optional[float]:
        if self.a_held_start is None or self.a_held_end is None or not self.n_experiments:
            return None
        return (self.a_held_end - self.a_held_start) / self.n_experiments


def run_episode(
    case: TwinCase, policy, budget: int = BUDGET, score_accuracy: bool = True,
    baseline_accuracy: Optional[Dict[str, Tuple[float, float]]] = None,
) -> EpisodeResult:
    """One policy on one twin for up to `budget` experiments (fewer if the policy runs out). With
    `score_accuracy=False` (pre-training) only the reward/repair loop runs."""
    graph = case.graph
    tested: List[str] = []
    repaired: set = set()
    picks: List[str] = []
    rewards: List[float] = []
    bridges_added = bridges_real = 0

    start = (baseline_accuracy or _per_node_accuracy(case, graph)) if score_accuracy else {}
    curve = [_mean([v[0] for v in start.values()])] if score_accuracy else []

    for _ in range(min(budget, len(case.node_id_to_name))):
        node_id = policy.select(graph, set(tested), frozenset(repaired))
        if node_id is None:
            break
        f1, _cf = evaluate_experiment(case, graph, node_id)
        reward = 1.0 - f1
        policy.update(node_id, reward)
        _, largest, _ = _actual_outcome_from_ground_truth(
            case.gt_nx, case.node_id_to_name[node_id], case.name_to_node_id, []
        )
        repair = repair_twin(graph, node_id, largest)
        graph = repair.graph
        for a, b in repair.bridges:
            repaired.update((a, b))
            bridges_added += 1
            bridges_real += frozenset((case.node_id_to_name[a], case.node_id_to_name[b])) in case.gt_pairs
        tested.append(node_id)
        picks.append(node_id)
        rewards.append(reward)
        if score_accuracy:
            curve.append(_mean([v[0] for v in _per_node_accuracy(case, graph).values()]))

    if not score_accuracy:
        return EpisodeResult(policy.name, case.level, case.completeness, case.seed, picks, rewards, [], 0.0, 0.0,
                             None, None, 0.0, 0.0, bridges_added, bridges_real)

    end = _per_node_accuracy(case, graph)
    held = [n for n in end if n not in set(tested)]
    return EpisodeResult(
        policy=policy.name, level=case.level, completeness=case.completeness, seed=case.seed, picks=picks,
        rewards=rewards, a_all_curve=curve, a_all_start=curve[0], a_all_end=curve[-1],
        a_held_start=_mean([start[n][0] for n in held if n in start]) if held else None,
        a_held_end=_mean([end[n][0] for n in held]) if held else None,
        cf_all_start=_mean([v[1] for v in start.values()]), cf_all_end=_mean([v[1] for v in end.values()]),
        bridges_added=bridges_added, bridges_real=bridges_real,
    )


def pretrain_linucb(cases: Sequence[TwinCase], budget: int = BUDGET, alpha: float = 1.0) -> LinUCBPolicy:
    """Runs a single LinUCB through every training episode in order (deterministic), learning from the real
    reward of every experiment, and returns it."""
    policy = LinUCBPolicy(alpha=alpha)
    for case in cases:
        run_episode(case, policy, budget, score_accuracy=False)
    return policy


@dataclass
class PolicyBenchmarkResult:
    episodes: List[EpisodeResult]
    budget: int
    train_seeds: List[int]
    test_seeds: List[int]
    pretraining_episodes: Dict[str, int] = field(default_factory=dict)
    skipped_test_cases: int = 0  # twins with no discoverable node (nothing to predict), never scored


def run_policy_benchmark(
    root: Path,
    levels: Optional[Sequence[str]] = None,
    completeness_levels: Optional[Sequence[float]] = None,
    test_seeds: Optional[Sequence[int]] = None,
    train_seeds: Optional[Sequence[int]] = None,
    budget: int = BUDGET,
    policies: Sequence[str] = POLICIES,
) -> PolicyBenchmarkResult:
    levels = list(levels or TOPOLOGY_LEVELS)
    completenesses = list(completeness_levels or COMPLETENESS_LEVELS)
    test_seeds = list(test_seeds if test_seeds is not None else TEST_SEEDS)
    train_seeds = list(train_seeds if train_seeds is not None else TRAIN_SEEDS)
    if set(train_seeds) & set(test_seeds):
        raise ValueError("train_seeds and test_seeds must be disjoint")
    if len(levels) < 2:
        raise ValueError("leave-one-level-out needs at least two topology levels")

    train_cases = {l: [build_twin_case(root, l, c, s) for c in completenesses for s in train_seeds] for l in levels}
    test_cases = {l: [build_twin_case(root, l, c, s) for c in completenesses for s in test_seeds] for l in levels}

    episodes: List[EpisodeResult] = []
    pretraining: Dict[str, int] = {}
    skipped = 0
    for held_out in levels:
        pretrained = pretrain_linucb([c for l in levels if l != held_out for c in train_cases[l]], budget)
        pretraining[held_out] = sum(len(train_cases[l]) for l in levels if l != held_out)
        for case in test_cases[held_out]:
            baseline = _per_node_accuracy(case, case.graph)  # step-0 accuracy, shared by every policy
            if not baseline:  # sampling left the twin with no node: there is nothing to predict or score
                skipped += 1
                continue
            for name in policies:
                if name == "static":
                    policy = StaticPolicy(case.graph)
                elif name == "linucb":
                    policy = LinUCBPolicy.from_state(pretrained.state())
                elif name == "linucb_cold":
                    policy = LinUCBPolicy()
                elif name == "random":
                    policy = RandomPolicy(seed=case.seed)
                else:
                    raise ValueError(f"unknown policy {name!r}")
                policy.name = name if name != "linucb_cold" else "linucb_cold"
                episodes.append(run_episode(case, policy, budget, baseline_accuracy=baseline))
    return PolicyBenchmarkResult(episodes, budget, train_seeds, test_seeds, pretraining, skipped)


def _summ(values: Sequence[Optional[float]]) -> MetricSummary:
    return summarize_values(values)


def format_policy_table(result: PolicyBenchmarkResult) -> str:
    """Pooled over every topology, completeness level and seed."""
    header = ["policy", "episodes", "experiments run", "accuracy start", "accuracy end", "gain / experiment (all nodes)",
              "gain / experiment (held-out nodes)", "counterfactual F1 gain", "mean reward"]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for policy in POLICIES:
        rows = [e for e in result.episodes if e.policy == policy]
        if not rows:
            continue
        lines.append("| " + " | ".join([
            policy, str(len(rows)), f"{sum(e.n_experiments for e in rows) / len(rows):.2f}",
            f"{sum(e.a_all_start for e in rows) / len(rows):.3f}", f"{sum(e.a_all_end for e in rows) / len(rows):.3f}",
            format_summary(_summ([e.gain_all_per_experiment for e in rows])),
            format_summary(_summ([e.gain_held_per_experiment for e in rows])),
            f"{sum(e.cf_all_end - e.cf_all_start for e in rows) / len(rows):+.3f}",
            f"{_mean([r for e in rows for r in e.rewards]):.3f}" if any(e.rewards for e in rows) else "n/a",
        ]) + " |")
    return "\n".join(lines)


def format_topology_table(result: PolicyBenchmarkResult, metric: str = "gain_all_per_experiment") -> str:
    """Per topology (pooled over completeness and seeds): the metric mean ± stdev for every policy."""
    header = ["topology"] + list(POLICIES)
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for level in dict.fromkeys(e.level for e in result.episodes):
        cells = [
            format_summary(_summ([getattr(e, metric) for e in result.episodes if e.level == level and e.policy == p]))
            for p in POLICIES
        ]
        lines.append("| " + " | ".join([level] + cells) + " |")
    return "\n".join(lines)


def format_curve_table(result: PolicyBenchmarkResult) -> str:
    """Mean accuracy (all nodes) after 0..budget experiments, per policy; episodes that ran fewer
    experiments hold their last value."""
    header = ["policy"] + [f"after {k}" for k in range(result.budget + 1)]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for policy in POLICIES:
        rows = [e for e in result.episodes if e.policy == policy]
        if not rows:
            continue
        means = [
            sum(e.a_all_curve[min(k, len(e.a_all_curve) - 1)] for e in rows) / len(rows) for k in range(result.budget + 1)
        ]
        lines.append("| " + " | ".join([policy] + [f"{m:.3f}" for m in means]) + " |")
    return "\n".join(lines)


def format_repair_table(result: PolicyBenchmarkResult) -> str:
    """How often repairs happened, how many bridges were a real edge, and whether an episode's accuracy rose,
    fell or stayed flat."""
    header = ["policy", "bridges / episode", "bridges that are a real edge", "episodes improved", "unchanged", "worse"]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for policy in POLICIES:
        rows = [e for e in result.episodes if e.policy == policy]
        if not rows:
            continue
        added = sum(e.bridges_added for e in rows)
        real = f"{sum(e.bridges_real for e in rows) / added:.2f}" if added else "n/a"
        eps = 1e-9
        lines.append("| " + " | ".join([
            policy, f"{added / len(rows):.2f}", real,
            str(sum(1 for e in rows if e.gain_all > eps)), str(sum(1 for e in rows if abs(e.gain_all) <= eps)),
            str(sum(1 for e in rows if e.gain_all < -eps)),
        ]) + " |")
    return "\n".join(lines)
