"""Dynamic Path Engine (spec Phase 60, FR-1.33: "compute shortest paths,
alternate paths, path costs, route changes, and disconnected components
on the (possibly failure-modified) graph").

`docs/architecture/algorithm_selection.md` section 5 already selected the
algorithms: Dijkstra for weighted shortest path, Yen's algorithm (bounded
K) for alternate paths, BFS/union-find for connectivity. NetworkX already
supplies all three -- `nx.shortest_path`/`nx.shortest_simple_paths`
(Yen's, a generator yielding paths in increasing cost order)/
`nx.connected_components` -- so nothing here reimplements a graph
algorithm the library already provides correctly.

Edge weight is a genuinely probabilistic cost, not an arbitrary scale:
`-log(confidence)`. Probability along a path multiplies; cost along a
path adds -- so a path's total weight is `-log` of its overall confidence
product, and Dijkstra/Yen's minimizing summed cost is exactly maximizing
route confidence, not an unrelated number bolted on. For an edge in a
Phase 59 `FailureInjectionResult.degraded_edge_ids`, `PACKET_LOSS`/
`BANDWIDTH_REDUCTION` add `-log(1 - ratio)` -- the same unit, treating the
ratio as an additional independent failure probability for that edge.
`LATENCY_INJECTION` adds `latency_ms / _DEFAULT_LATENCY_COST_SCALE`, a
documented provisional constant (same "provisional, uncalibrated pending
Phase 68" status as `_DEFAULT_PACKET_SCALE` and friends elsewhere in this
project). `SERVICE_DEGRADATION` carries no quantitative field on
`FailureScenario` at all -- the edge stays recorded in
`degraded_edge_ids` but contributes no extra cost here, a documented
limitation, not an invented number.

A missing source/target node is deliberately NOT an error here, unlike
Phase 59's "unknown scenario target" guard. The single most important
real case this module must handle is a route-change query where a
`NODE_FAILURE` removed the very node being asked about -- the honest
answer is "no path" (`None`), not a crash. This mirrors the archaeology
layer's own "missing means empty" convention (Phase 44/47/49) rather than
Phase 59's stricter fail-fast one: the two situations are genuinely
different -- Phase 59 validates a scenario's own internal consistency
before acting, while this module answers a reachability question where
"the node isn't there" is itself a valid, common answer.

"Route changes" (FR-1.33) is not elaborated anywhere beyond the phrase
itself -- no doc defines what baseline it is diffed against. The only
self-consistent reading adopted here: compare the shortest path for a
given `(source, target)` pair on a baseline graph vs. a current (possibly
failure-modified) graph. Composing this into the full
failure -> propagation -> routing -> service-impact pipeline is
explicitly FR-1.34's job (Phase 61), not attempted here.

Never imports `simulator.ground_truth` (spec §4;
`scripts/check_ground_truth_boundary.py` would reject it if it did).
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from typing import List, Optional

import networkx as nx

from backend.app.models.failure import FailureType
from backend.app.models.topology import TopologyGraph
from backend.simulation.failure_injection import FailureInjectionResult

_EPSILON = 1e-9
_DEFAULT_ALTERNATE_PATH_K = 5
_DEFAULT_LATENCY_COST_SCALE = 100.0  # ms; provisional, uncalibrated (pending Phase 68)


@dataclass(frozen=True)
class PathResult:
    node_ids: List[str]
    edge_ids: List[str]
    cost: float


@dataclass(frozen=True)
class ConnectivityResult:
    connected_component_count: int
    components: List[List[str]]
    is_fully_connected: bool
    largest_component_node_ids: List[str]


@dataclass(frozen=True)
class RouteChange:
    source_node_id: str
    target_node_id: str
    baseline_path: Optional[PathResult]
    current_path: Optional[PathResult]
    changed: bool
    cost_delta: Optional[float]


def _confidence_cost(probability: float) -> float:
    return -math.log(max(min(probability, 1 - _EPSILON), _EPSILON))


def _edge_weight(edge, failure: Optional[FailureInjectionResult]) -> float:
    cost = _confidence_cost(edge.confidence)
    if failure is None or edge.edge_id not in failure.degraded_edge_ids:
        return cost

    scenario = failure.scenario
    if scenario.failure_type == FailureType.LATENCY_INJECTION:
        cost += scenario.latency_ms / _DEFAULT_LATENCY_COST_SCALE
    elif scenario.failure_type == FailureType.PACKET_LOSS:
        cost += _confidence_cost(1 - scenario.packet_loss_ratio)
    elif scenario.failure_type == FailureType.BANDWIDTH_REDUCTION:
        cost += _confidence_cost(1 - scenario.bandwidth_reduction_ratio)
    # SERVICE_DEGRADATION: no quantitative field to derive a magnitude from.
    return cost


def _check_failure_matches(graph: TopologyGraph, failure: Optional[FailureInjectionResult]) -> None:
    if failure is not None and failure.graph != graph:
        raise ValueError("failure.graph does not match the given graph")


def _build_weighted_graph(graph: TopologyGraph, failure: Optional[FailureInjectionResult]) -> nx.Graph:
    g = nx.Graph()
    g.add_nodes_from(node.node_id for node in graph.nodes)
    for edge in graph.edges:
        g.add_edge(
            edge.source_node_id,
            edge.target_node_id,
            weight=_edge_weight(edge, failure),
            edge_id=edge.edge_id,
        )
    return g


def _to_path_result(g: nx.Graph, node_path: List[str]) -> PathResult:
    pairs = list(zip(node_path, node_path[1:]))
    return PathResult(
        node_ids=node_path,
        edge_ids=[g[u][v]["edge_id"] for u, v in pairs],
        cost=sum(g[u][v]["weight"] for u, v in pairs),
    )


def compute_shortest_path(
    graph: TopologyGraph,
    source_node_id: str,
    target_node_id: str,
    failure: Optional[FailureInjectionResult] = None,
) -> Optional[PathResult]:
    """The lowest-cost path from `source_node_id` to `target_node_id`, or
    `None` if either node is absent from `graph` or no path connects them.
    """
    _check_failure_matches(graph, failure)
    node_ids = {n.node_id for n in graph.nodes}
    if source_node_id not in node_ids or target_node_id not in node_ids:
        return None

    g = _build_weighted_graph(graph, failure)
    try:
        node_path = nx.shortest_path(g, source_node_id, target_node_id, weight="weight")
    except nx.NetworkXNoPath:
        return None
    return _to_path_result(g, node_path)


def compute_alternate_paths(
    graph: TopologyGraph,
    source_node_id: str,
    target_node_id: str,
    k: int = _DEFAULT_ALTERNATE_PATH_K,
    failure: Optional[FailureInjectionResult] = None,
) -> List[PathResult]:
    """Up to `k` paths from `source_node_id` to `target_node_id`, ranked by
    increasing cost (Yen's algorithm via `nx.shortest_simple_paths`).
    Empty if either node is absent or no path connects them.
    """
    _check_failure_matches(graph, failure)
    node_ids = {n.node_id for n in graph.nodes}
    if source_node_id not in node_ids or target_node_id not in node_ids:
        return []

    g = _build_weighted_graph(graph, failure)
    try:
        paths = itertools.islice(
            nx.shortest_simple_paths(g, source_node_id, target_node_id, weight="weight"), k
        )
        return [_to_path_result(g, p) for p in paths]
    except nx.NetworkXNoPath:
        return []


def compute_connectivity(graph: TopologyGraph) -> ConnectivityResult:
    """Connected-component analysis of `graph` as-is -- already reflects
    any hard-failure removal in the graph passed in; soft failures never
    change structure, so no `failure` parameter is needed here.
    """
    g = nx.Graph()
    g.add_nodes_from(node.node_id for node in graph.nodes)
    for edge in graph.edges:
        g.add_edge(edge.source_node_id, edge.target_node_id)

    if g.number_of_nodes() == 0:
        return ConnectivityResult(
            connected_component_count=0,
            components=[],
            is_fully_connected=True,
            largest_component_node_ids=[],
        )

    components = sorted((sorted(c) for c in nx.connected_components(g)), key=lambda c: c[0])
    largest = max(components, key=len)

    return ConnectivityResult(
        connected_component_count=len(components),
        components=components,
        is_fully_connected=len(components) == 1,
        largest_component_node_ids=largest,
    )


def compute_route_change(
    baseline_graph: TopologyGraph,
    current_graph: TopologyGraph,
    source_node_id: str,
    target_node_id: str,
    failure: Optional[FailureInjectionResult] = None,
) -> RouteChange:
    """Compares the shortest `(source, target)` path on `baseline_graph`
    against `current_graph` (typically a Phase 59 `FailureInjectionResult.graph`,
    with `failure` supplying the matching weight adjustments).
    """
    baseline_path = compute_shortest_path(baseline_graph, source_node_id, target_node_id)
    current_path = compute_shortest_path(current_graph, source_node_id, target_node_id, failure=failure)

    if baseline_path is None and current_path is None:
        changed = False
    elif baseline_path is None or current_path is None:
        changed = True
    else:
        changed = baseline_path.node_ids != current_path.node_ids

    cost_delta = (
        current_path.cost - baseline_path.cost if baseline_path is not None and current_path is not None else None
    )

    return RouteChange(
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        baseline_path=baseline_path,
        current_path=current_path,
        changed=changed,
        cost_delta=cost_delta,
    )
