"""Phase 16 ground-truth generator tests.

Pure -- no Docker required; a fake ip_lookup stands in for real
`docker inspect` calls, matching the pattern used by generate.py's builders.
"""

from __future__ import annotations

import pytest

from simulator.ground_truth.generate import (
    build_expected_paths,
    build_roles,
    build_topology_graph,
    check_services_match_compose,
)
from simulator.ground_truth.topology import DECLARED_EDGES, SERVICE_ROLES


def _fake_ip_lookup(service: str) -> str:
    index = sorted(SERVICE_ROLES).index(service) + 1
    return f"10.99.0.{index}"


def test_topology_graph_has_a_node_per_declared_service() -> None:
    graph = build_topology_graph(_fake_ip_lookup)
    assert {n.node_id for n in graph.nodes} == set(SERVICE_ROLES)


def test_topology_graph_has_all_declared_edges() -> None:
    # TopologyGraph's own model validator (Phase 04) already refuses to
    # construct if any edge references an undeclared node, so successful
    # construction here is itself part of the proof.
    graph = build_topology_graph(_fake_ip_lookup)
    assert len(graph.edges) == len(DECLARED_EDGES)


def test_topology_graph_edges_all_have_full_confidence_and_evidence() -> None:
    graph = build_topology_graph(_fake_ip_lookup)
    for edge in graph.edges:
        assert edge.confidence == 1.0
        assert edge.evidence


def test_roles_cover_every_declared_service_with_certainty() -> None:
    gt_roles = build_roles()
    assert set(gt_roles.roles) == set(SERVICE_ROLES)
    for service, classification in gt_roles.roles.items():
        expected_role = SERVICE_ROLES[service]
        assert classification.role_probabilities[expected_role] == 1.0
        assert classification.best_role == expected_role


def test_expected_path_client_to_redis_goes_through_gateway_lb_and_api() -> None:
    graph = build_topology_graph(_fake_ip_lookup)
    gt_paths = build_expected_paths(graph)
    path = gt_paths.paths["client->redis"]
    assert path[0] == "client"
    assert path[1] == "gateway"
    assert path[2] in ("load-balancer", "load-balancer-2")
    assert path[3] in ("api-1", "api-2")
    assert path[-1] == "redis"
    assert len(path) == 5


def test_expected_path_client_to_external_service_goes_through_an_api_node() -> None:
    graph = build_topology_graph(_fake_ip_lookup)
    gt_paths = build_expected_paths(graph)
    path = gt_paths.paths["client->external-service"]
    assert path[0] == "client"
    assert path[3] in ("api-1", "api-2")
    assert path[-1] == "external-service"


def test_check_services_match_compose_accepts_the_declared_set() -> None:
    check_services_match_compose(set(SERVICE_ROLES))  # must not raise


def test_check_services_match_compose_rejects_an_extra_service() -> None:
    with pytest.raises(ValueError):
        check_services_match_compose(set(SERVICE_ROLES) | {"new-service"})


def test_check_services_match_compose_rejects_a_missing_service() -> None:
    with pytest.raises(ValueError):
        check_services_match_compose(set(SERVICE_ROLES) - {"client"})
