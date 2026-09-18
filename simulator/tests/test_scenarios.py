"""Phase 18 scenario generator tests.

Pure -- no Docker required. Each archetype's defining structural claim is verified with real
NetworkX computation over the generated graph, not asserted merely because the generator
constructed something without erroring.
"""

from __future__ import annotations

import networkx as nx
import pytest

from backend.app.models import ServiceRole
from simulator.scenarios.generate import build_declaration, build_roles, build_topology_graph
from simulator.scenarios.topologies import (
    ScenarioEdge,
    dynamic_service_network,
    multi_path,
    multi_tier,
    redundant,
    simple_chain,
    star,
)


def _undirected_graph(roles, edges) -> nx.Graph:
    g = nx.Graph()
    g.add_nodes_from(roles)
    g.add_edges_from((e.source, e.target) for e in edges)
    return g


def _directed_graph(roles, edges) -> nx.DiGraph:
    g = nx.DiGraph()
    g.add_nodes_from(roles)
    g.add_edges_from((e.source, e.target) for e in edges)
    return g


# ---------------------------------------------------------------------------
# simple_chain
# ---------------------------------------------------------------------------


def test_simple_chain_is_a_simple_path_from_client_to_database() -> None:
    roles, edges = simple_chain(5)
    g = _directed_graph(roles, edges)
    path = list(nx.topological_sort(g))
    assert nx.is_simple_path(g, path)
    assert roles[path[0]] == ServiceRole.CLIENT
    assert roles[path[-1]] == ServiceRole.DATABASE
    assert len(path) == 5


def test_simple_chain_rejects_fewer_than_two_nodes() -> None:
    with pytest.raises(ValueError):
        simple_chain(1)


# ---------------------------------------------------------------------------
# star
# ---------------------------------------------------------------------------


def test_star_hub_has_degree_n_and_every_leaf_has_degree_1() -> None:
    roles, edges = star(6)
    g = _undirected_graph(roles, edges)
    assert g.degree["hub"] == 6
    for node in roles:
        if node != "hub":
            assert g.degree[node] == 1
    assert roles["hub"] == ServiceRole.GATEWAY


# ---------------------------------------------------------------------------
# multi_tier
# ---------------------------------------------------------------------------


def test_multi_tier_every_edge_crosses_exactly_one_tier_boundary() -> None:
    roles, edges = multi_tier([1, 2, 2, 1])
    tier_of = {}
    for t, size in enumerate([1, 2, 2, 1]):
        for i in range(1, size + 1):
            tier_of[f"tier{t}-{i}"] = t

    for edge in edges:
        assert tier_of[edge.target] - tier_of[edge.source] == 1

    g = _directed_graph(roles, edges)
    assert nx.is_weakly_connected(g)


def test_multi_tier_requires_at_least_two_tiers() -> None:
    with pytest.raises(ValueError):
        multi_tier([3])


# ---------------------------------------------------------------------------
# redundant
# ---------------------------------------------------------------------------


def test_redundant_has_no_bridge_around_the_skip_connection() -> None:
    roles, edges = redundant(4)
    g = _undirected_graph(roles, edges)
    bridges = set(nx.bridges(g))
    # node-1 <-> node-2 and node-2 <-> node-3 must NOT be bridges -- the skip
    # connection node-1 <-> node-3 provides an alternate route around node-2.
    assert ("node-1", "node-2") not in bridges and ("node-2", "node-1") not in bridges
    assert ("node-2", "node-3") not in bridges and ("node-3", "node-2") not in bridges


def test_redundant_requires_at_least_three_nodes() -> None:
    with pytest.raises(ValueError):
        redundant(2)


# ---------------------------------------------------------------------------
# multi_path
# ---------------------------------------------------------------------------


def test_multi_path_has_k_vertex_disjoint_paths_between_source_and_sink() -> None:
    roles, edges = multi_path(3)
    g = _undirected_graph(roles, edges)
    assert nx.node_connectivity(g, "source", "sink") == 3


def test_multi_path_requires_at_least_two_paths() -> None:
    with pytest.raises(ValueError):
        multi_path(1)


# ---------------------------------------------------------------------------
# dynamic_service_network
# ---------------------------------------------------------------------------


def test_dynamic_service_network_is_connected() -> None:
    roles, edges = dynamic_service_network(seed=7, n=10)
    g = _undirected_graph(roles, edges)
    assert nx.is_connected(g)
    assert roles["svc-1"] == ServiceRole.CLIENT


def test_dynamic_service_network_is_deterministic_given_the_same_seed() -> None:
    roles1, edges1 = dynamic_service_network(seed=99, n=8)
    roles2, edges2 = dynamic_service_network(seed=99, n=8)
    assert roles1 == roles2
    assert [(e.source, e.target, e.protocols) for e in edges1] == [(e.source, e.target, e.protocols) for e in edges2]


def test_dynamic_service_network_different_seeds_can_differ() -> None:
    _, edges1 = dynamic_service_network(seed=1, n=10)
    _, edges2 = dynamic_service_network(seed=2, n=10)
    shape1 = {(e.source, e.target) for e in edges1}
    shape2 = {(e.source, e.target) for e in edges2}
    assert shape1 != shape2


# ---------------------------------------------------------------------------
# generate.py builders
# ---------------------------------------------------------------------------


def test_build_declaration_round_trips_roles_and_edges() -> None:
    roles, edges = star(3)
    declaration = build_declaration(roles, edges)
    assert declaration.roles == roles
    assert {(e.source, e.target) for e in declaration.edges} == {(e.source, e.target) for e in edges}


def test_build_roles_gives_every_node_full_confidence_in_its_declared_role() -> None:
    roles, _ = star(3)
    gt_roles = build_roles(roles)
    assert set(gt_roles.roles) == set(roles)
    for node, classification in gt_roles.roles.items():
        assert classification.role_probabilities[roles[node]] == 1.0
        assert classification.best_role == roles[node]


def test_build_topology_graph_constructs_a_valid_graph_given_an_ip_lookup() -> None:
    roles, edges = simple_chain(3)

    def fake_ip_lookup(service: str) -> str:
        index = sorted(roles).index(service) + 1
        return f"10.77.0.{index}"

    graph = build_topology_graph(roles, edges, fake_ip_lookup, graph_id="test-chain")
    assert {n.node_id for n in graph.nodes} == set(roles)
    assert len(graph.edges) == len(edges)
    for edge in graph.edges:
        assert edge.confidence == 1.0
        assert edge.evidence
