"""Head-to-head benchmark: time-series PC vs Phase 53's candidate generator (spec addendum Phase 79).

Both methods run on the SAME reconstructed capture and are scored by Phase 68's unmodified
`evaluate_causal_analysis` against the declared directed dependency pairs (mapped to node ids by IP, as the
matrix does):

  - `phase53`  `generate_causal_candidates(estimate_dependency_strength(...))` -- the existing method.
  - `pc`       `discover_causal_edges` -> `to_causal_candidates` (`backend/dependency/causal_discovery.py`).

Two datasets, on the six matrix topologies at five observation-completeness levels, seeds 42-51:
  - `phase70`        the matrix's own lag-encoded traffic, built exactly as `run_matrix_cell` builds it (the
                     required benchmark). Every node there is a delayed copy of one hidden driver.
  - `parent_driven`  `experiments/causal_generators.py`'s control dataset, where the declared edges are the
                     true causal graph and no hidden common cause exists.

Reported per method: directed precision/recall/F1, a direction-agnostic skeleton F1 (found the pair vs got
the direction too), reversed predictions (right pair, wrong direction), spurious pairs (not a declared edge in
either direction), and for PC the undefined-test count. Hyper-parameters are fixed in advance (alpha 0.05,
max lag 5, 10 s buckets); an alpha sweep {0.01, 0.05, 0.1} at completeness 1.0 is reported next to the
headline so its dependence is visible, not used to pick a winner.

Discovered edges are candidates, never proven causation (Phase 53's stance).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from backend.dependency.causal_candidates import CausalCandidate, generate_causal_candidates
from backend.dependency.causal_discovery import discover_causal_edges, to_causal_candidates
from backend.dependency.strength import estimate_dependency_strength
from backend.nettrace.reconstruct import reconstruct_flows
from backend.nettrace.topology.discovery import discover_nodes
from experiments.artifacts.io import write_jsonl
from experiments.artifacts.paths import packets_path
from experiments.causal_generators import parent_driven_traffic
from experiments.matrix_runner import (
    _PULSE_CYCLES,
    _PULSE_INTENSITY_RANGE,
    _PULSE_PACKETS_PER_NODE,
    _WAVE_GAP_SECONDS,
    OBSERVATION_COMPLETENESS_LEVELS,
    TOPOLOGY_LEVELS,
)
from experiments.metrics.causal_evaluation import evaluate_causal_analysis
from experiments.metrics.summary_stats import MetricSummary, format_summary, summarize_values
from experiments.observation_sampling import sample_packets
from experiments.synthetic_traffic import assign_ips, generate_packets_for_scenario

DATASETS: Tuple[str, ...] = ("phase70", "parent_driven")
METHODS: Tuple[str, ...] = ("phase53", "pc")
TEST_SEEDS: List[int] = list(range(42, 52))
HEADLINE_ALPHA = 0.05
SWEEP_ALPHAS: Tuple[float, ...] = (0.01, 0.05, 0.1)
SWEEP_COMPLETENESS = 1.0


@dataclass(frozen=True)
class CausalCase:
    dataset: str
    level: str
    completeness: float
    seed: int
    root: Path
    capture_id: str
    ground_truth: List[Tuple[str, str]]  # directed, as node ids
    dropped_edges: List[Tuple[str, str]]


def build_case(root: Path, level: str, completeness: float, seed: int, dataset: str) -> CausalCase:
    """Writes one observation-sampled capture for `dataset` and reconstructs its flows."""
    if dataset not in DATASETS:
        raise ValueError(f"unknown dataset {dataset!r}; choose from {DATASETS}")
    roles, edges = TOPOLOGY_LEVELS[level]()
    ip_by_name = assign_ips(list(roles))
    capture_id = f"causal-{dataset}-{level}-{str(completeness).replace('.', 'p')}-{seed}"

    dropped: List[Tuple[str, str]] = []
    if dataset == "phase70":
        packets = generate_packets_for_scenario(
            roles, edges, ip_by_name, capture_id, seed,
            packets_per_edge=15, wave_2_edges=max(1, len(edges) // 4), wave_gap_seconds=_WAVE_GAP_SECONDS,
            pulse_cycles=_PULSE_CYCLES, pulse_packets_per_node=_PULSE_PACKETS_PER_NODE,
            pulse_intensity_range=_PULSE_INTENSITY_RANGE,
        )
        truth_names = [(e.source, e.target) for e in edges]
    else:
        dataset_obj = parent_driven_traffic(roles, edges, ip_by_name, capture_id, seed)
        packets, truth_names, dropped = dataset_obj.packets, dataset_obj.true_edges, dataset_obj.dropped_edges

    write_jsonl(packets_path(root, capture_id), sample_packets(packets, completeness, seed))
    reconstruct_flows(root, capture_id)

    ip_to_node_id = {str(ip): n.node_id for n in discover_nodes(root, capture_id) for ip in n.ip_addresses}
    truth = [
        (ip_to_node_id[ip_by_name[a]], ip_to_node_id[ip_by_name[b]])
        for a, b in truth_names
        if ip_by_name[a] in ip_to_node_id and ip_by_name[b] in ip_to_node_id
    ]
    return CausalCase(dataset, level, completeness, seed, root, capture_id, truth, dropped)


@dataclass(frozen=True)
class CausalScore:
    dataset: str
    method: str
    alpha: Optional[float]
    level: str
    completeness: float
    seed: int
    precision: float
    recall: float
    f1: float
    skeleton_f1: float
    predicted: int
    ground_truth: int
    matched: int
    reversed_pairs: int
    spurious_pairs: int
    undefined_tests: int
    total_tests: int
    seconds: float


def score_candidates(
    case: CausalCase, method: str, alpha: Optional[float], candidates: List[CausalCandidate],
    undefined_tests: int = 0, total_tests: int = 0, seconds: float = 0.0,
) -> CausalScore:
    directed = evaluate_causal_analysis(candidates, case.ground_truth)
    undirected_candidates = [
        replace(c, source_node_id=min(c.source_node_id, c.target_node_id), target_node_id=max(c.source_node_id, c.target_node_id))
        for c in candidates
    ]
    skeleton = evaluate_causal_analysis(undirected_candidates, [tuple(sorted(p)) for p in case.ground_truth])

    truth = set(case.ground_truth)
    truth_unordered = {frozenset(p) for p in truth}
    predicted = {(c.source_node_id, c.target_node_id) for c in candidates}
    return CausalScore(
        dataset=case.dataset, method=method, alpha=alpha, level=case.level, completeness=case.completeness,
        seed=case.seed, precision=directed.dependency_precision, recall=directed.dependency_recall,
        f1=directed.dependency_f1, skeleton_f1=skeleton.dependency_f1, predicted=directed.predicted_count,
        ground_truth=directed.ground_truth_count, matched=directed.matched_count,
        reversed_pairs=sum(1 for a, b in predicted if (b, a) in truth and (a, b) not in truth),
        spurious_pairs=len({frozenset(p) for p in predicted} - truth_unordered),
        undefined_tests=undefined_tests, total_tests=total_tests, seconds=seconds,
    )


def evaluate_case(case: CausalCase, alphas: Sequence[float]) -> List[CausalScore]:
    """Scores phase53 and pc (at each of `alphas`) on one capture."""
    from backend.dependency.causal_discovery import DEFAULT_ALPHA  # noqa: F401  (documented default)
    from experiments.artifacts.io import read_jsonl
    from experiments.artifacts.paths import flows_path
    from backend.app.models.flow import Flow

    scores: List[CausalScore] = []
    started = time.perf_counter()
    heuristic = generate_causal_candidates(estimate_dependency_strength(case.root, case.capture_id))
    scores.append(score_candidates(case, "phase53", None, heuristic, seconds=time.perf_counter() - started))

    nodes = discover_nodes(case.root, case.capture_id)
    flows = read_jsonl(flows_path(case.root, case.capture_id), Flow)
    for alpha in alphas:
        started = time.perf_counter()
        result = discover_causal_edges(flows, nodes, alpha=alpha)
        scores.append(score_candidates(
            case, "pc", alpha, to_causal_candidates(result.edges, alpha),
            undefined_tests=result.undefined_tests, total_tests=result.total_tests,
            seconds=time.perf_counter() - started,
        ))
    return scores


@dataclass
class CausalBenchmarkResult:
    scores: List[CausalScore]
    seeds: List[int]
    dropped_edges: Dict[str, List[Tuple[str, str]]]


def run_causal_benchmark(
    root: Path,
    levels: Optional[Sequence[str]] = None,
    completeness_levels: Optional[Sequence[float]] = None,
    seeds: Optional[Sequence[int]] = None,
    datasets: Sequence[str] = DATASETS,
    sweep_alphas: Sequence[float] = SWEEP_ALPHAS,
) -> CausalBenchmarkResult:
    levels = list(levels or TOPOLOGY_LEVELS)
    completenesses = list(completeness_levels or OBSERVATION_COMPLETENESS_LEVELS)
    seeds = list(seeds if seeds is not None else TEST_SEEDS)
    scores: List[CausalScore] = []
    dropped: Dict[str, List[Tuple[str, str]]] = {}
    for dataset in datasets:
        for level in levels:
            for c in completenesses:
                for seed in seeds:
                    case = build_case(root, level, c, seed, dataset)
                    if case.dropped_edges:
                        dropped[f"{level}"] = case.dropped_edges
                    alphas = list(sweep_alphas) if c == SWEEP_COMPLETENESS else [HEADLINE_ALPHA]
                    scores.extend(evaluate_case(case, alphas))
    return CausalBenchmarkResult(scores=scores, seeds=seeds, dropped_edges=dropped)


def _summary(scores: Sequence[CausalScore], metric: str) -> MetricSummary:
    return summarize_values([getattr(s, metric) for s in scores])


def _select(result: CausalBenchmarkResult, dataset: str, method: str, level: Optional[str] = None,
            completeness: Optional[float] = None, alpha: Optional[float] = None) -> List[CausalScore]:
    return [
        s for s in result.scores
        if s.dataset == dataset and s.method == method and (level is None or s.level == level)
        and (completeness is None or s.completeness == completeness)
        and (method != "pc" or alpha is None or s.alpha == alpha)
    ]


def format_benchmark_table(result: CausalBenchmarkResult, dataset: str, metric: str = "f1") -> str:
    """One row per (topology, completeness), the metric mean ± stdev [min, max] for phase53 and pc (alpha
    0.05); a final row pools everything."""
    rows = [s for s in result.scores if s.dataset == dataset]
    levels = list(dict.fromkeys(s.level for s in rows))
    header = ["topology", "completeness", "phase53", "pc"]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for level in levels:
        for c in sorted({s.completeness for s in rows if s.level == level}, reverse=True):
            cells = [format_summary(_summary(_select(result, dataset, m, level, c, HEADLINE_ALPHA), metric)) for m in METHODS]
            lines.append("| " + " | ".join([level, f"{c:g}"] + cells) + " |")
    pooled = [format_summary(_summary(_select(result, dataset, m, alpha=HEADLINE_ALPHA), metric)) for m in METHODS]
    lines.append("| " + " | ".join(["**all**", "all"] + pooled) + " |")
    return "\n".join(lines)


def format_diagnostics_table(result: CausalBenchmarkResult) -> str:
    """Per dataset and method (pooled, alpha 0.05): mean directed precision/recall/F1, skeleton F1, and
    per-capture predicted / reversed / spurious counts and the PC undefined-test fraction."""
    header = ["dataset", "method", "precision", "recall", "f1", "skeleton f1", "predicted", "reversed", "spurious", "undefined tests", "seconds"]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    mean = lambda values: sum(values) / len(values) if values else float("nan")  # noqa: E731
    for dataset in dict.fromkeys(s.dataset for s in result.scores):
        for method in METHODS:
            rows = _select(result, dataset, method, alpha=HEADLINE_ALPHA)
            tests = sum(s.total_tests for s in rows)
            undefined = f"{sum(s.undefined_tests for s in rows) / tests:.3f}" if tests else "n/a"
            lines.append("| " + " | ".join([
                dataset, method,
                *(f"{mean([getattr(s, m) for s in rows]):.3f}" for m in ("precision", "recall", "f1", "skeleton_f1")),
                f"{mean([s.predicted for s in rows]):.2f}", f"{mean([s.reversed_pairs for s in rows]):.2f}",
                f"{mean([s.spurious_pairs for s in rows]):.2f}", undefined, f"{mean([s.seconds for s in rows]):.2f}",
            ]) + " |")
    return "\n".join(lines)


def format_alpha_sweep_table(result: CausalBenchmarkResult) -> str:
    """PC at each swept alpha, completeness 1.0 only, pooled over topologies and seeds."""
    header = ["dataset", "alpha", "precision", "recall", "f1", "spurious pairs / capture"]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for dataset in dict.fromkeys(s.dataset for s in result.scores):
        for alpha in sorted({s.alpha for s in result.scores if s.method == "pc" and s.completeness == SWEEP_COMPLETENESS}):
            rows = _select(result, dataset, "pc", completeness=SWEEP_COMPLETENESS, alpha=alpha)
            if not rows:
                continue
            spurious = sum(s.spurious_pairs for s in rows) / len(rows)
            lines.append("| " + " | ".join([
                dataset, f"{alpha:g}", format_summary(_summary(rows, "precision")), format_summary(_summary(rows, "recall")),
                format_summary(_summary(rows, "f1")), f"{spurious:.2f}",
            ]) + " |")
    return "\n".join(lines)
