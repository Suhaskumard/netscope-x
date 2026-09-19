"""Criticality Analysis (spec Phase 55, FR-1.29: "compute graph criticality
metrics (degree, betweenness, articulation points, path dependency,
connectivity) with documented rationale for each metric's relevance").

The algorithm and per-metric rationale were already committed at Phase 05:
`docs/architecture/algorithm_selection.md` section 4 selected "Exact
NetworkX implementations" (degree centrality, Brandes' betweenness
centrality, Tarjan's articulation-points algorithm) and wrote the required
"why each metric is relevant" documentation. `METRIC_RATIONALE` below
carries that documentation as a real, in-code artifact, adapted directly
from section 4's own text.

Operates on `TopologyGraph` (Phase 30-32), not `DependencyEdge` (Phase
50-54) -- section 4's own confidence caveat references `Edge.confidence`
specifically, and its rationale (betweenness as "routing/proxy
chokepoints", articulation points as "structural single points of
failure") describes the full inferred communication topology, not the
narrower, sparser dependency/causal-candidate graph.

Resolves section 4's explicitly flagged open question -- "a low-confidence
edge contributing to a node's high betweenness score should be flagged as
lower-confidence criticality, not reported with false precision" -- via
`mean_incident_edge_confidence`: the real, honest mean confidence of a
node's own incident edges, reported alongside its (unweighted, exact)
centrality scores, rather than distorting the graph-theoretic computation
itself with an unjustified confidence-weighting scheme the spec never asks
for.

Lives in `backend/dependency/` per that package's own docstring (Phase
50), which already names "criticality metrics" as one of its anticipated
later additions.

Never imports `simulator.ground_truth` (spec §4;
`scripts/check_ground_truth_boundary.py` would reject it if it did).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import networkx as nx

from backend.app.models.topology import TopologyGraph

METRIC_RATIONALE: Dict[str, str] = {
    "degree_centrality": (
        "Cheap first-pass signal for how many direct relationships a node has -- a high "
        "degree is the simplest indicator that a node's removal or misbehavior touches many "
        "others directly."
    ),
    "betweenness_centrality": (
        "Identifies nodes that lie on many shortest communication paths, i.e. likely "
        "routing/proxy chokepoints (Gateway and Load Balancer roles are expected to score "
        "highly here)."
    ),
    "is_articulation_point": (
        "Identifies nodes whose removal would disconnect the graph, i.e. structural single "
        "points of failure -- directly feeds failure-injection experiment suggestions "
        "(spec Phase 67)."
    ),
    "path_dependency_impact": (
        "Measures how many other nodes would lose connectivity to the main remaining "
        "component if this node were removed -- a graded refinement of the articulation-point "
        "flag, showing how much redundancy protects against a given node's failure (ties to "
        "RQ6, resilience quantification)."
    ),
    "connectivity": (
        "Graph-wide minimum number of nodes that must be removed to disconnect the graph "
        "(node connectivity) plus the number of already-separate connected components -- the "
        "overall redundancy/resilience picture the per-node metrics sit inside."
    ),
}


@dataclass(frozen=True)
class NodeCriticality:
    node_id: str
    degree_centrality: float
    betweenness_centrality: float
    is_articulation_point: bool
    path_dependency_impact: int
    mean_incident_edge_confidence: Optional[float]


@dataclass(frozen=True)
class GraphCriticalityReport:
    node_scores: List[NodeCriticality]
    node_connectivity: int
    connected_component_count: int


def _build_graph(graph: TopologyGraph) -> nx.Graph:
    g = nx.Graph()
    g.add_nodes_from(node.node_id for node in graph.nodes)
    for edge in graph.edges:
        g.add_edge(edge.source_node_id, edge.target_node_id, confidence=edge.confidence)
    return g


def _path_dependency_impact(g: nx.Graph, node_id: str) -> int:
    remaining = g.copy()
    remaining.remove_node(node_id)
    if remaining.number_of_nodes() == 0:
        return 0
    largest_component_size = max(len(c) for c in nx.connected_components(remaining))
    return remaining.number_of_nodes() - largest_component_size


def _mean_incident_edge_confidence(g: nx.Graph, node_id: str) -> Optional[float]:
    confidences = [g.edges[node_id, neighbor]["confidence"] for neighbor in g.neighbors(node_id)]
    if not confidences:
        return None
    return sum(confidences) / len(confidences)


def compute_graph_criticality(graph: TopologyGraph) -> GraphCriticalityReport:
    """Computes `NodeCriticality` for every node in `graph`, plus
    graph-level `node_connectivity`/`connected_component_count`. Returns
    an empty report for a graph with no nodes -- never an error.
    """
    g = _build_graph(graph)

    if g.number_of_nodes() == 0:
        return GraphCriticalityReport(node_scores=[], node_connectivity=0, connected_component_count=0)

    degree_centrality = nx.degree_centrality(g)
    betweenness_centrality = nx.betweenness_centrality(g)
    articulation_points = set(nx.articulation_points(g))

    node_scores = [
        NodeCriticality(
            node_id=node_id,
            degree_centrality=degree_centrality[node_id],
            betweenness_centrality=betweenness_centrality[node_id],
            is_articulation_point=node_id in articulation_points,
            path_dependency_impact=_path_dependency_impact(g, node_id),
            mean_incident_edge_confidence=_mean_incident_edge_confidence(g, node_id),
        )
        for node_id in sorted(g.nodes)
    ]

    node_connectivity = nx.node_connectivity(g) if g.number_of_nodes() >= 2 else 0
    connected_component_count = nx.number_connected_components(g)

    return GraphCriticalityReport(
        node_scores=node_scores,
        node_connectivity=node_connectivity,
        connected_component_count=connected_component_count,
    )
