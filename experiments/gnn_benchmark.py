"""Head-to-head benchmark: GNN edge model vs Phase 31's noisy-OR heuristic (spec addendum Phase 77).

Both are scored by Phase 32's own `compare_topology_to_ground_truth` on the same matrix topologies
(`TOPOLOGY_LEVELS`) and the same synthetic captures the Phase 68 matrix builds. Three methods:

  - `heuristic`            the existing graph as-is: an edge for every node pair with any flow.
  - `heuristic_thresholded` the same graph keeping only edges with heuristic confidence >= 0.5 -- the fair
                            confidence-vs-confidence comparison, since the comparison metric ignores confidence.
  - `gnn`                  every node pair with GNN probability >= 0.5.

Protocol: leave-one-topology-level-out. For each of the six levels, the GNN is trained on examples from
the *other five* levels (training seeds `TRAIN_SEEDS`) and tested on the held-out level (test seeds
`TEST_SEEDS`) -- never the same topology and never the same seed as training. The 0.5 threshold is fixed
in advance, not tuned on test data.

Two traffic settings, because the default matrix volume makes the completeness axis flat (Phase 74:
edge survival >= 0.9999, so every method scores 1.0 and the comparison says nothing): `default` (the
matrix's own volume, a sanity row) and `lowvol` (Phase 74's `SENSITIVITY_SWEEP`, where edges are really
lost to observation sampling and there is something to recover).

Ground truth is the declared scenario topology, used only here (`experiments/` may import it); the model in
`backend/` only ever receives a plain label array.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from backend.app.models.topology import Edge, TopologyGraph
from backend.nettrace.reconstruct import reconstruct_flows
from backend.nettrace.topology.gnn_edge_model import (
    EdgeGNNModel,
    GraphExample,
    example_from_observations,
    fit_edge_model,
    pair_indices,
    predict_edge_probabilities,
)
from backend.nettrace.topology.graph import build_topology_graph
from experiments.artifacts.io import write_jsonl
from experiments.artifacts.paths import packets_path
from experiments.matrix_runner import (
    _PULSE_CYCLES,
    _PULSE_INTENSITY_RANGE,
    _PULSE_PACKETS_PER_NODE,
    _WAVE_GAP_SECONDS,
    OBSERVATION_COMPLETENESS_LEVELS,
    SENSITIVITY_SWEEP,
    TOPOLOGY_LEVELS,
)
from experiments.metrics.summary_stats import MetricSummary, format_summary, summarize_values
from experiments.metrics.topology_comparison import compare_topology_to_ground_truth
from experiments.observation_sampling import sample_packets
from experiments.synthetic_traffic import assign_ips, build_ground_truth_graph, generate_packets_for_scenario

THRESHOLD = 0.5
TRAIN_SEEDS: List[int] = list(range(100, 105))
TEST_SEEDS: List[int] = list(range(42, 52))
VARIANTS: Tuple[str, ...] = ("default", "lowvol")
METHODS: Tuple[str, ...] = ("heuristic", "heuristic_thresholded", "gnn")


@dataclass(frozen=True)
class BenchmarkExample:
    level: str
    completeness: float
    variant: str
    seed: int
    example: GraphExample
    labels: np.ndarray  # [n, n] bool: the declared topology's edges among this capture's discovered nodes
    graph: TopologyGraph  # the heuristic graph
    ground_truth: TopologyGraph


def build_example(root: Path, level: str, completeness: float, seed: int, variant: str) -> BenchmarkExample:
    """Synthesizes one capture exactly as the matrix does for `variant`, runs the real pipeline up to
    the heuristic `TopologyGraph`, and pairs it with the declared ground truth."""
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}; choose from {VARIANTS}")
    roles, edges = TOPOLOGY_LEVELS[level]()
    ip_by_name = assign_ips(list(roles))
    capture_id = f"gnn-{level}-{str(completeness).replace('.', 'p')}-{variant}-{seed}"

    if variant == "lowvol":
        packets_per_edge, pulse_cycles = SENSITIVITY_SWEEP["packets_per_edge"], SENSITIVITY_SWEEP["pulse_cycles"]
    else:
        packets_per_edge, pulse_cycles = 15, _PULSE_CYCLES
    packets = generate_packets_for_scenario(
        roles, edges, ip_by_name, capture_id, seed,
        packets_per_edge=packets_per_edge, wave_2_edges=max(1, len(edges) // 4), wave_gap_seconds=_WAVE_GAP_SECONDS,
        pulse_cycles=pulse_cycles, pulse_packets_per_node=_PULSE_PACKETS_PER_NODE,
        pulse_intensity_range=_PULSE_INTENSITY_RANGE,
    )
    write_jsonl(packets_path(root, capture_id), sample_packets(packets, completeness, seed))
    flows = reconstruct_flows(root, capture_id)
    graph = build_topology_graph(root, capture_id, graph_id=f"{capture_id}-heuristic")

    ip_to_name = {ip: name for name, ip in ip_by_name.items()}
    names = [ip_to_name.get(str(node.ip_addresses[0])) for node in graph.nodes]
    true_pairs = {frozenset((e.source, e.target)) for e in edges}
    n = len(graph.nodes)
    labels = np.zeros((n, n), dtype=bool)
    for u in range(n):
        for v in range(u + 1, n):
            if names[u] is not None and names[v] is not None and frozenset((names[u], names[v])) in true_pairs:
                labels[u, v] = labels[v, u] = True

    return BenchmarkExample(
        level=level, completeness=completeness, variant=variant, seed=seed,
        example=example_from_observations(graph.nodes, graph.edges, flows),
        labels=labels, graph=graph,
        ground_truth=build_ground_truth_graph(roles, edges, ip_by_name, graph_id=f"{capture_id}-gt"),
    )


def heuristic_thresholded_graph(graph: TopologyGraph, threshold: float = THRESHOLD) -> TopologyGraph:
    return graph.model_copy(update={"edges": [e for e in graph.edges if e.confidence >= threshold]})


def graph_from_probabilities(
    graph: TopologyGraph, example: GraphExample, probabilities: np.ndarray, threshold: float = THRESHOLD
) -> TopologyGraph:
    """The heuristic graph's nodes with one edge per node pair whose probability >= `threshold`. An
    observed pair keeps its heuristic `Edge` (evidence intact) with the GNN probability as confidence; an
    unobserved pair gets a synthesized edge whose evidence says plainly it is a model prediction with no
    flow evidence. For benchmarking only -- never persisted as a discovered edge."""
    by_pair: Dict[Tuple[int, int], Edge] = {}
    index = {node_id: i for i, node_id in enumerate(example.node_ids)}
    for edge in graph.edges:
        u, v = index.get(edge.source_node_id), index.get(edge.target_node_id)
        if u is not None and v is not None:
            by_pair[(min(u, v), max(u, v))] = edge

    edges: List[Edge] = []
    iu, iv = pair_indices(example.node_count)
    for u, v in zip(iu, iv):
        p = float(probabilities[u, v])
        if p < threshold:
            continue
        existing = by_pair.get((int(u), int(v)))
        if existing is not None:
            edges.append(existing.model_copy(update={"confidence": p}))
        else:
            a, b = example.node_ids[u], example.node_ids[v]
            edges.append(
                Edge(
                    edge_id=f"gnn:{a}-{b}", source_node_id=a, target_node_id=b, confidence=p,
                    evidence=[f"GNN link prediction p={p:.3f}; no observed flows between these nodes"],
                    observation_count=1, first_observed=graph.generated_at, last_observed=graph.generated_at,
                    protocols=["unknown"],
                )
            )
    return graph.model_copy(update={"edges": edges})


def expected_calibration_error(probabilities: np.ndarray, outcomes: np.ndarray, bins: int = 10) -> float:
    """Standard binned ECE over the given (probability, 0/1 outcome) pairs."""
    if len(probabilities) == 0:
        return 0.0
    ids = np.minimum((probabilities * bins).astype(int), bins - 1)
    total = 0.0
    for b in range(bins):
        mask = ids == b
        if mask.any():
            total += mask.mean() * abs(probabilities[mask].mean() - outcomes[mask].mean())
    return float(total)


@dataclass(frozen=True)
class ExampleScore:
    level: str
    completeness: float
    variant: str
    seed: int
    precision: Dict[str, float]
    recall: Dict[str, float]
    f1: Dict[str, float]
    gnn_recovered_edges: int  # predicted, truly an edge, and not observed by the heuristic
    gnn_hallucinated_edges: int  # predicted but not an edge
    gnn_lost_edges: int  # observed by the heuristic and truly an edge, but dropped by the GNN
    ece_gnn: float
    ece_heuristic: float


def score_example(item: BenchmarkExample, model: EdgeGNNModel) -> ExampleScore:
    probabilities = predict_edge_probabilities(model, item.example)
    graphs = {
        "heuristic": item.graph,
        "heuristic_thresholded": heuristic_thresholded_graph(item.graph),
        "gnn": graph_from_probabilities(item.graph, item.example, probabilities),
    }
    results = {name: compare_topology_to_ground_truth(g, item.ground_truth) for name, g in graphs.items()}

    iu, iv = pair_indices(item.example.node_count)
    truth = item.labels[iu, iv]
    observed = item.example.adjacency[iu, iv] > 0
    predicted = probabilities[iu, iv] >= THRESHOLD
    return ExampleScore(
        level=item.level, completeness=item.completeness, variant=item.variant, seed=item.seed,
        precision={k: r.edge_precision for k, r in results.items()},
        recall={k: r.edge_recall for k, r in results.items()},
        f1={k: r.edge_f1 for k, r in results.items()},
        gnn_recovered_edges=int((predicted & truth & ~observed).sum()),
        gnn_hallucinated_edges=int((predicted & ~truth).sum()),
        gnn_lost_edges=int((~predicted & truth & observed).sum()),
        ece_gnn=expected_calibration_error(probabilities[iu, iv], truth.astype(float)),
        ece_heuristic=expected_calibration_error(item.example.adjacency[iu, iv], truth.astype(float)),
    )


@dataclass
class BenchmarkResult:
    scores: List[ExampleScore]
    fold_training_sizes: Dict[str, Dict[str, int]]  # held-out level -> examples / pairs / parameters
    hidden: int
    embedding: int
    epochs: int
    train_seeds: List[int]
    test_seeds: List[int]
    final_losses: Dict[str, float] = field(default_factory=dict)


def run_benchmark(
    root: Path,
    levels: Optional[Sequence[str]] = None,
    completeness_levels: Optional[Sequence[float]] = None,
    test_seeds: Optional[Sequence[int]] = None,
    train_seeds: Optional[Sequence[int]] = None,
    variants: Sequence[str] = VARIANTS,
    hidden: int = 16,
    embedding: int = 8,
    epochs: int = 200,
    model_seed: int = 0,
) -> BenchmarkResult:
    """Leave-one-topology-level-out benchmark (see module docstring). Training seeds and test seeds must
    be disjoint; each fold trains only on the other levels' examples."""
    levels = list(levels or TOPOLOGY_LEVELS)
    completenesses = list(completeness_levels or OBSERVATION_COMPLETENESS_LEVELS)
    test_seeds = list(test_seeds if test_seeds is not None else TEST_SEEDS)
    train_seeds = list(train_seeds if train_seeds is not None else TRAIN_SEEDS)
    if set(train_seeds) & set(test_seeds):
        raise ValueError("train_seeds and test_seeds must be disjoint")
    if len(levels) < 2:
        raise ValueError("leave-one-level-out needs at least two topology levels")

    def build(seeds: Sequence[int], level: str) -> List[BenchmarkExample]:
        return [
            build_example(root, level, c, s, v) for v in variants for c in completenesses for s in seeds
        ]

    train_pool = {level: build(train_seeds, level) for level in levels}
    test_pool = {level: build(test_seeds, level) for level in levels}

    scores: List[ExampleScore] = []
    sizes: Dict[str, Dict[str, int]] = {}
    losses: Dict[str, float] = {}
    for held_out in levels:
        train = [it for level in levels if level != held_out for it in train_pool[level] if it.example.node_count >= 2]
        model = fit_edge_model(
            [it.example for it in train], [it.labels for it in train],
            hidden=hidden, embedding=embedding, epochs=epochs, seed=model_seed,
        )
        sizes[held_out] = {
            "training_examples": model.training_example_count,
            "training_pairs": model.training_pair_count,
            "parameters": model.parameter_count,
        }
        losses[held_out] = model.final_loss
        scores.extend(score_example(it, model) for it in test_pool[held_out])

    return BenchmarkResult(
        scores=scores, fold_training_sizes=sizes, hidden=hidden, embedding=embedding, epochs=epochs,
        train_seeds=train_seeds, test_seeds=test_seeds, final_losses=losses,
    )


def summarize(scores: Sequence[ExampleScore], metric: str, method: str) -> MetricSummary:
    return summarize_values([getattr(s, metric)[method] for s in scores])


def format_benchmark_table(result: BenchmarkResult, variant: str, metric: str = "f1") -> str:
    """One row per (topology, completeness): the metric's mean ± stdev [min, max] for every method."""
    rows = [s for s in result.scores if s.variant == variant]
    levels = list(dict.fromkeys(s.level for s in rows))
    completenesses = sorted({s.completeness for s in rows}, reverse=True)
    header = ["topology", "completeness"] + list(METHODS)
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for level in levels:
        for c in completenesses:
            cell = [s for s in rows if s.level == level and s.completeness == c]
            lines.append("| " + " | ".join([level, f"{c:g}"] + [format_summary(summarize(cell, metric, m)) for m in METHODS]) + " |")
    overall = ["**all**", "all"] + [format_summary(summarize(rows, metric, m)) for m in METHODS]
    lines.append("| " + " | ".join(overall) + " |")
    return "\n".join(lines)


def format_edge_flow_table(result: BenchmarkResult) -> str:
    """Per variant and completeness: how many edges the GNN recovered / hallucinated / dropped
    (means per test example), and calibration error of GNN vs heuristic confidence."""
    header = ["variant", "completeness", "recovered", "hallucinated", "dropped observed", "ECE gnn", "ECE heuristic"]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for variant in dict.fromkeys(s.variant for s in result.scores):
        for c in sorted({s.completeness for s in result.scores if s.variant == variant}, reverse=True):
            cell = [s for s in result.scores if s.variant == variant and s.completeness == c]
            mean = lambda values: sum(values) / len(values)  # noqa: E731
            lines.append("| " + " | ".join([
                variant, f"{c:g}",
                f"{mean([s.gnn_recovered_edges for s in cell]):.2f}",
                f"{mean([s.gnn_hallucinated_edges for s in cell]):.2f}",
                f"{mean([s.gnn_lost_edges for s in cell]):.2f}",
                f"{mean([s.ece_gnn for s in cell]):.3f}",
                f"{mean([s.ece_heuristic for s in cell]):.3f}",
            ]) + " |")
    return "\n".join(lines)
