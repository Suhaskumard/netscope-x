"""Turns a topology generator's (roles, edges) output into persistable artifacts (spec Phase 18).

`build_declaration` is what gets persisted for every generated scenario, deployed or not.
`build_topology_graph`/`build_roles` mirror `simulator/ground_truth/generate.py`'s builders
(parameterized here instead of reading module-level constants, since a scenario's roles/edges
come from a generator call, not a single hardcoded declaration) and are only used once a scenario
is actually deployed and a real `ip_lookup` is available.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Dict, List

from backend.app.models import Edge, Node, RoleClassification, ServiceRole, TopologyGraph
from simulator.ground_truth.models import GroundTruthRoles
from simulator.scenarios.models import ScenarioDeclaration, ScenarioEdgeModel
from simulator.scenarios.topologies import ScenarioEdge

IpLookup = Callable[[str], str]


def build_declaration(roles: Dict[str, ServiceRole], edges: List[ScenarioEdge]) -> ScenarioDeclaration:
    return ScenarioDeclaration(
        roles=roles,
        edges=[ScenarioEdgeModel(source=e.source, target=e.target, protocols=e.protocols) for e in edges],
    )


def build_roles(roles: Dict[str, ServiceRole]) -> GroundTruthRoles:
    now = datetime.now(timezone.utc)
    return GroundTruthRoles(
        generated_at=now,
        roles={
            service: RoleClassification(node_id=service, computed_at=now, role_probabilities={role: 1.0})
            for service, role in roles.items()
        },
    )


def build_topology_graph(
    roles: Dict[str, ServiceRole],
    edges: List[ScenarioEdge],
    ip_lookup: IpLookup,
    graph_id: str,
) -> TopologyGraph:
    """Only callable once a scenario is actually deployed -- `ip_lookup` must resolve each
    node's real running container IP (see simulator.ground_truth.cli.docker_ip_lookup, reused
    as-is: it looks up any running compose service by its compose label, nothing lab-specific)."""
    now = datetime.now(timezone.utc)
    nodes = [
        Node(node_id=service, ip_addresses=[ip_lookup(service)], first_observed=now, last_observed=now)
        for service in roles
    ]
    graph_edges = [
        Edge(
            edge_id=f"{e.source}->{e.target}",
            source_node_id=e.source,
            target_node_id=e.target,
            confidence=1.0,
            evidence=[f"scenario declaration: {graph_id}"],
            observation_count=1,
            first_observed=now,
            last_observed=now,
            protocols=e.protocols,
        )
        for e in edges
    ]
    return TopologyGraph(graph_id=graph_id, generated_at=now, nodes=nodes, edges=graph_edges)
