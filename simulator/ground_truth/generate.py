"""Ground-truth generation (spec Phase 16).

`build_topology_graph`/`build_roles`/`build_expected_paths` are pure given
an `ip_lookup` function -- real Docker IP lookup lives in cli.py, kept
separate so these builders are unit-testable without Docker (see
simulator/tests/test_ground_truth.py).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Dict, List, Set

import networkx as nx

from backend.app.models import Edge, Node, RoleClassification, TopologyGraph
from simulator.ground_truth.models import GroundTruthPaths, GroundTruthRoles
from simulator.ground_truth.topology import DECLARED_EDGES, EXPECTED_PATH_PAIRS, SERVICE_ROLES

IpLookup = Callable[[str], str]


def check_services_match_compose(compose_service_names: Set[str]) -> None:
    """Raises if the declared roles don't exactly match the compose file's services --
    catches drift between the lab definition and this ground-truth declaration."""
    declared = set(SERVICE_ROLES)
    missing = compose_service_names - declared
    extra = declared - compose_service_names
    if missing or extra:
        raise ValueError(
            "ground truth role declarations out of sync with docker-compose.yml: "
            f"missing_from_ground_truth={sorted(missing)} extra_in_ground_truth={sorted(extra)}"
        )


def build_topology_graph(ip_lookup: IpLookup, graph_id: str = "lab-ground-truth") -> TopologyGraph:
    now = datetime.now(timezone.utc)
    nodes = [
        Node(node_id=service, ip_addresses=[ip_lookup(service)], first_observed=now, last_observed=now)
        for service in SERVICE_ROLES
    ]
    edges = [
        Edge(
            edge_id=f"{e.source}->{e.target}",
            source_node_id=e.source,
            target_node_id=e.target,
            confidence=1.0,
            evidence=["ground truth: declared lab architecture (simulator/ground_truth/topology.py)"],
            observation_count=1,
            first_observed=now,
            last_observed=now,
            protocols=e.protocols,
        )
        for e in DECLARED_EDGES
    ]
    return TopologyGraph(graph_id=graph_id, generated_at=now, nodes=nodes, edges=edges)


def build_roles() -> GroundTruthRoles:
    now = datetime.now(timezone.utc)
    roles = {
        service: RoleClassification(node_id=service, computed_at=now, role_probabilities={role: 1.0})
        for service, role in SERVICE_ROLES.items()
    }
    return GroundTruthRoles(generated_at=now, roles=roles)


def build_expected_paths(graph: TopologyGraph) -> GroundTruthPaths:
    """Computes real shortest paths (NetworkX/Dijkstra -- the Phase 05-selected
    path-analysis algorithm) over the ground-truth graph for each representative pair."""
    g = nx.DiGraph()
    for node in graph.nodes:
        g.add_node(node.node_id)
    for edge in graph.edges:
        g.add_edge(edge.source_node_id, edge.target_node_id)

    paths: Dict[str, List[str]] = {}
    for source, target in EXPECTED_PATH_PAIRS:
        try:
            path = nx.shortest_path(g, source, target)
        except nx.NetworkXNoPath:
            path = []
        paths[f"{source}->{target}"] = path
    return GroundTruthPaths(generated_at=datetime.now(timezone.utc), paths=paths)
