"""Topology comparison against ground truth, for evaluation purposes only
(spec Phase 32, FR-1.11: "support comparison against ground truth for
evaluation purposes only"; RQ1).

This module is the ONLY place in the repository that combines an inferred
`TopologyGraph` (Phase 29-32's real output) with a ground-truth
`TopologyGraph` (Phase 16-17's `simulator/ground_truth/`). It must never be
imported from `backend/nettrace/` or `backend/app/` -- doing so would let
ground truth leak into the inference pipeline, forbidden by spec §4 and
REPRO-4. `scripts/check_ground_truth_boundary.py` enforces the analogous
rule for `simulator.ground_truth` imports; this module additionally never
imports that package directly, instead reading ground truth back through
`experiments/artifacts/io.py::read_ground_truth_generation`, an existing
Phase 17 primitive already used outside `simulator/`.

Node/edge identity across the two sides is NOT comparable by id string:
`discover_nodes`/`discover_edges` (inference) generate positional ids like
`f"{capture_id}:node:{index}"`, while `simulator.ground_truth.generate`
uses the lab's own service names (`node_id=service`,
`edge_id=f"{source}->{target}"`) -- two independently-run id schemes with
no shared vocabulary. The only genuinely comparable identity on both sides
is `Node.ip_addresses` (both use the same `IPvAnyAddress` type). So nodes
are matched by exact ip-address-set equality, and edges are matched by the
*unordered* pair of their two endpoints' ip-address sets -- unordered
because `discover_edges` deliberately reports edges as undirected (Phase
30; see `edges.py`'s own docstring), while ground truth's edges are
directed by lab declaration. Comparing directionally would penalize
inference for correctly declining to claim an initiator it has no honest
basis to claim.

`graph_similarity = (node_f1 + edge_f1) / 2`: equal weighting because
nothing today justifies weighting node agreement over edge agreement or
vice versa -- the same "no principled basis to weight one signal above
another" reasoning already used for Phase 31's noisy-OR edge-confidence
signals. This is a provisional, self-defined metric (no formula is
spec-mandated, and `docs/architecture/algorithm_selection.md` doesn't
cover graph comparison either -- the same "self-defined and justified
here" situation Phases 26/29-31 were already in), explicitly pending
Phase 68's full evaluation-matrix treatment, not a claim of validated
accuracy.

Returns a plain `TopologyComparisonResult`, not a `MetricResult`
(`backend/app/models/metric.py`): `MetricResult.experiment_id` is
required and non-optional, and no experiment registry exists anywhere in
this repository yet (`experiments/runners/` doesn't exist) -- inventing a
plausible-looking `experiment_id` with no real registered experiment
behind it would be exactly the kind of metric-that-looks-legitimate-but-
isn't that spec §21 ("No Fake Metrics") forbids. Real `MetricResult`
wrapping is left to whichever future phase (68) has a genuine experiment
to anchor it to.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, FrozenSet, Set, Tuple

from backend.app.models.topology import TopologyGraph


@dataclass(frozen=True)
class TopologyComparisonResult:
    capture_id: str
    computed_at: datetime

    node_precision: float
    node_recall: float
    node_f1: float

    edge_precision: float
    edge_recall: float
    edge_f1: float

    graph_similarity: float

    inferred_node_count: int
    ground_truth_node_count: int
    inferred_edge_count: int
    ground_truth_edge_count: int


def _node_ip_sets(graph: TopologyGraph) -> Set[FrozenSet[str]]:
    return {frozenset(str(ip) for ip in node.ip_addresses) for node in graph.nodes}


def _resolved_edge_pairs(graph: TopologyGraph) -> Set[FrozenSet[FrozenSet[str]]]:
    node_ips: Dict[str, FrozenSet[str]] = {
        node.node_id: frozenset(str(ip) for ip in node.ip_addresses) for node in graph.nodes
    }
    pairs: Set[FrozenSet[FrozenSet[str]]] = set()
    for edge in graph.edges:
        source_ips = node_ips.get(edge.source_node_id)
        target_ips = node_ips.get(edge.target_node_id)
        if source_ips is None or target_ips is None:
            continue
        pairs.add(frozenset({source_ips, target_ips}))
    return pairs


def _precision_recall_f1(matched: int, predicted: int, actual: int) -> Tuple[float, float, float]:
    """Empty-vs-empty (nothing to disagree on) is defined as perfect
    agreement (1.0/1.0/1.0); empty-vs-nonempty is 0.0 on whichever side has
    nothing -- both conventions stated explicitly, never left implicit."""
    if predicted == 0 and actual == 0:
        return 1.0, 1.0, 1.0
    precision = (matched / predicted) if predicted else 0.0
    recall = (matched / actual) if actual else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return precision, recall, f1


def compare_topology_to_ground_truth(
    inferred: TopologyGraph, ground_truth: TopologyGraph
) -> TopologyComparisonResult:
    """Compares an inferred `TopologyGraph` (Phase 32's `build_topology_graph`
    output) against a ground-truth `TopologyGraph` (Phase 16-17's
    `simulator.ground_truth.generate.build_topology_graph` output) for the
    SAME network. Both must already exist -- this function does no I/O
    itself; the caller resolves which capture's inferred graph to compare
    against which ground-truth generation."""
    inferred_nodes = _node_ip_sets(inferred)
    ground_truth_nodes = _node_ip_sets(ground_truth)
    matched_nodes = len(inferred_nodes & ground_truth_nodes)
    node_precision, node_recall, node_f1 = _precision_recall_f1(
        matched_nodes, len(inferred_nodes), len(ground_truth_nodes)
    )

    inferred_edges = _resolved_edge_pairs(inferred)
    ground_truth_edges = _resolved_edge_pairs(ground_truth)
    matched_edges = len(inferred_edges & ground_truth_edges)
    edge_precision, edge_recall, edge_f1 = _precision_recall_f1(
        matched_edges, len(inferred_edges), len(ground_truth_edges)
    )

    return TopologyComparisonResult(
        capture_id=inferred.graph_id,
        computed_at=datetime.now(timezone.utc),
        node_precision=node_precision,
        node_recall=node_recall,
        node_f1=node_f1,
        edge_precision=edge_precision,
        edge_recall=edge_recall,
        edge_f1=edge_f1,
        graph_similarity=(node_f1 + edge_f1) / 2,
        inferred_node_count=len(inferred.nodes),
        ground_truth_node_count=len(ground_truth.nodes),
        inferred_edge_count=len(inferred.edges),
        ground_truth_edge_count=len(ground_truth.edges),
    )
