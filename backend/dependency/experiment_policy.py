"""Active-learning experiment policy (spec addendum Phase 80).

Phase 67's `generate_experiment_recommendations` ranks failure experiments once, from structure alone
(articulation points by path-dependency impact, then routing chokepoints by betweenness); it never looks at
what an experiment revealed. This module adds a policy that does.

The loop it supports, for a digital twin (an inferred `TopologyGraph`):
  1. `select` picks the next node to fail in a controlled experiment;
  2. reality answers -- which nodes were actually stranded (supplied by the caller: a real lab, or in this
     project's benchmark the declared topology);
  3. the caller scores the twin's prediction for that experiment with Phase 63/66's validation and passes
     the real error back as the reward (`update`) -- this module never invents a reward;
  4. `repair_twin` uses the same real outcome to correct the twin.

What the repair can and cannot do, stated plainly: the twin's dominant avoidable error is a real edge that
observation loss never discovered, so it predicts stranding that does not happen. Where reality stayed
connected but the twin predicted stranding, ONE bridging edge per falsely stranded component is added,
flagged as experiment-inferred. One experiment cannot say WHICH real edge is missing, so the bridge is a
guess that restores the observed connectivity; whether it helps other targets is measured in
`experiments/experiment_policy_benchmark.py`, not assumed. It cannot fix spurious edges or propagation
false positives (it only ever adds).

Policies: `LinUCBPolicy` (contextual bandit over structural features of the twin), `StaticPolicy` (Phase
67's ranking, computed once), `RandomPolicy` (sanity baseline). Features use only the twin's own graph -- no
ground truth -- and never import `simulator.ground_truth` (spec §4;
`scripts/check_ground_truth_boundary.py`).
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Optional, Sequence, Set, Tuple

import networkx as nx
import numpy as np

from backend.app.models.topology import Edge, TopologyGraph
from backend.dependency.criticality import compute_graph_criticality
from backend.dependency.experiment_recommendations import generate_experiment_recommendations

FEATURE_NAMES: Tuple[str, ...] = (
    "bias",
    "degree_centrality",
    "betweenness_centrality",
    "is_articulation_point",
    "path_dependency_impact_fraction",
    "mean_incident_edge_confidence",
    "predicted_stranded_fraction",
    "adjacent_to_repaired_node",
)
BRIDGE_CONFIDENCE = 0.5


def _nx(graph: TopologyGraph) -> nx.Graph:
    g = nx.Graph()
    g.add_nodes_from(n.node_id for n in graph.nodes)
    g.add_edges_from((e.source_node_id, e.target_node_id) for e in graph.edges)
    return g


def _components_after_removal(g: nx.Graph, node_id: str) -> List[Set[str]]:
    after = g.copy()
    after.remove_node(node_id)
    return sorted((set(c) for c in nx.connected_components(after)), key=lambda c: (-len(c), min(c)))


def node_features(
    graph: TopologyGraph, repaired_nodes: FrozenSet[str] = frozenset()
) -> Dict[str, np.ndarray]:
    """One feature vector per node, all derived from the twin's own graph (Phase 55's criticality plus a
    predicted-stranding fraction). `repaired_nodes` are nodes an earlier repair touched."""
    report = compute_graph_criticality(graph)
    g = _nx(graph)
    n = len(graph.nodes)
    features: Dict[str, np.ndarray] = {}
    for score in report.node_scores:
        stranded = 0.0
        if n > 1:
            components = _components_after_removal(g, score.node_id)
            largest = len(components[0]) if components else 0
            stranded = (n - 1 - largest) / (n - 1)
        features[score.node_id] = np.array(
            [
                1.0,
                score.degree_centrality,
                score.betweenness_centrality,
                1.0 if score.is_articulation_point else 0.0,
                score.path_dependency_impact / max(n - 1, 1),
                score.mean_incident_edge_confidence or 0.0,
                stranded,
                1.0 if any(nb in repaired_nodes for nb in g.neighbors(score.node_id)) else 0.0,
            ]
        )
    return features


class LinUCBPolicy:
    """Shared-linear-model contextual bandit over nodes: score = theta.x + alpha * sqrt(x A^-1 x). Picks the
    highest-scoring UNTESTED node (ties by node id) and learns from the reward the caller reports."""

    name = "linucb"

    def __init__(self, alpha: float = 1.0, ridge: float = 1.0) -> None:
        self.alpha = alpha
        self.A = ridge * np.eye(len(FEATURE_NAMES))
        self.b = np.zeros(len(FEATURE_NAMES))
        self._last: Dict[str, np.ndarray] = {}

    def select(
        self, graph: TopologyGraph, tested: Set[str], repaired_nodes: FrozenSet[str] = frozenset()
    ) -> Optional[str]:
        features = node_features(graph, repaired_nodes)
        self._last = features
        inverse = np.linalg.inv(self.A)
        theta = inverse @ self.b
        best: Optional[Tuple[float, str]] = None
        for node_id in sorted(features):
            if node_id in tested:
                continue
            x = features[node_id]
            score = float(theta @ x + self.alpha * np.sqrt(max(float(x @ inverse @ x), 0.0)))
            if best is None or score > best[0] + 1e-12:
                best = (score, node_id)
        return best[1] if best else None

    def update(self, node_id: str, reward: float) -> None:
        x = self._last[node_id]
        self.A = self.A + np.outer(x, x)
        self.b = self.b + reward * x

    def state(self) -> Tuple[np.ndarray, np.ndarray]:
        return self.A.copy(), self.b.copy()

    @classmethod
    def from_state(cls, state: Tuple[np.ndarray, np.ndarray], alpha: float = 1.0) -> "LinUCBPolicy":
        policy = cls(alpha=alpha)
        policy.A, policy.b = state[0].copy(), state[1].copy()
        return policy


class StaticPolicy:
    """Phase 67's ranking, computed once from the initial twin and never revised. It stops when its
    recommendations are exhausted (Phase 67 recommends only articulation points and above-mean chokepoints),
    so it may run fewer experiments than the budget."""

    name = "static"

    def __init__(self, initial_graph: TopologyGraph) -> None:
        self._order = [r.node_id for r in generate_experiment_recommendations(initial_graph)]

    def select(
        self, graph: TopologyGraph, tested: Set[str], repaired_nodes: FrozenSet[str] = frozenset()
    ) -> Optional[str]:
        return next((n for n in self._order if n not in tested), None)

    def update(self, node_id: str, reward: float) -> None:
        return None


class RandomPolicy:
    """Uniform over untested nodes, seeded -- the sanity baseline."""

    name = "random"

    def __init__(self, seed: int = 0) -> None:
        self._rng = random.Random(seed)

    def select(
        self, graph: TopologyGraph, tested: Set[str], repaired_nodes: FrozenSet[str] = frozenset()
    ) -> Optional[str]:
        remaining = sorted(n.node_id for n in graph.nodes if n.node_id not in tested)
        return self._rng.choice(remaining) if remaining else None

    def update(self, node_id: str, reward: float) -> None:
        return None


@dataclass(frozen=True)
class RepairResult:
    graph: TopologyGraph
    bridges: List[Tuple[str, str]]  # (node_id, node_id) edges added
    missing_stranding_count: int  # actually stranded nodes the twin did NOT predict stranded (unfixable by adding)


def repair_twin(
    graph: TopologyGraph, failed_node_id: str, actual_largest_component_node_ids: Sequence[str]
) -> RepairResult:
    """Corrects `graph` from one real experiment. `actual_largest_component_node_ids` is the largest
    component reality left after failing `failed_node_id` (Phase 63's own `ActualFailureOutcome` field).

    The twin's components after the failure are compared with reality's: a component wholly inside reality's
    largest component but disconnected from the twin's best-matching component is a FALSE stranding, so one
    bridging edge is added between the two, at the nodes nearest the failed node (the failed node's own
    former neighbours, then id). Returns the new graph (the input is never modified), the bridges added, and
    how many really stranded nodes the twin failed to predict (a spurious twin edge, which adding edges cannot
    fix). Returns the graph unchanged when the twin already agrees with reality."""
    if failed_node_id not in {n.node_id for n in graph.nodes}:
        raise ValueError(f"unknown node {failed_node_id!r}")
    g = _nx(graph)
    actual = set(actual_largest_component_node_ids) - {failed_node_id}
    components = _components_after_removal(g, failed_node_id)
    if not components:
        return RepairResult(graph, [], 0)

    # the twin component that best matches reality's largest one (ties: larger, then lower id)
    main = sorted(components, key=lambda c: (-len(c & actual), -len(c), min(c)))[0]
    distance = nx.single_source_shortest_path_length(g, failed_node_id)

    def nearest(component: Set[str]) -> str:
        return sorted(component, key=lambda node: (distance.get(node, 10**9), node))[0]

    bridges: List[Tuple[str, str]] = []
    edges: List[Edge] = list(graph.edges)
    for component in components:
        if component is main or not component <= actual:
            continue
        u, v = nearest(component), nearest(main)
        a, b = sorted((u, v))
        bridges.append((a, b))
        edges.append(
            Edge(
                edge_id=f"experiment-bridge:{failed_node_id}:{a}-{b}",
                source_node_id=a,
                target_node_id=b,
                confidence=BRIDGE_CONFIDENCE,
                evidence=[
                    f"inferred from a controlled experiment failing {failed_node_id}: reality stayed connected "
                    "where the twin predicted stranding; the actual connecting edge is unidentified"
                ],
                observation_count=1,
                first_observed=graph.generated_at,
                last_observed=graph.generated_at,
                protocols=["unknown"],
            )
        )

    twin_stranded = {n for c in components if c is not main for n in c}
    actual_stranded = {n.node_id for n in graph.nodes} - actual - {failed_node_id}
    missing = len(actual_stranded - twin_stranded)
    if not bridges:
        return RepairResult(graph, [], missing)
    return RepairResult(graph.model_copy(update={"edges": edges}), bridges, missing)
