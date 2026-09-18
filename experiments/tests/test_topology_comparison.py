"""Phase 32 ground-truth topology comparison unit tests (pure, no Docker,
no filesystem I/O -- constructs TopologyGraph instances directly)."""

from __future__ import annotations

from datetime import datetime, timezone

from backend.app.models import Edge, Node, TopologyGraph
from experiments.metrics.topology_comparison import compare_topology_to_ground_truth

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _node(node_id: str, ip: str) -> Node:
    return Node(node_id=node_id, ip_addresses=[ip], first_observed=NOW, last_observed=NOW)


def _edge(edge_id: str, source_node_id: str, target_node_id: str, protocol: str = "TCP") -> Edge:
    return Edge(
        edge_id=edge_id,
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        confidence=0.9,
        evidence=["synthetic evidence"],
        observation_count=1,
        first_observed=NOW,
        last_observed=NOW,
        protocols=[protocol],
    )


def _graph(graph_id: str, nodes, edges) -> TopologyGraph:
    return TopologyGraph(graph_id=graph_id, generated_at=NOW, nodes=nodes, edges=edges)


def test_perfect_match_gives_precision_recall_similarity_of_one() -> None:
    # Inferred and ground truth use DIFFERENT id schemes for the same two hosts --
    # this is the real-world situation (inference ids vs. lab service names) --
    # matching must go through ip_addresses, not node_id/edge_id equality.
    inferred = _graph(
        "cap-1",
        [_node("cap-1:node:0", "10.0.0.1"), _node("cap-1:node:1", "10.0.0.2")],
        [_edge("cap-1:edge:0", "cap-1:node:0", "cap-1:node:1")],
    )
    ground_truth = _graph(
        "lab-ground-truth",
        [_node("client", "10.0.0.1"), _node("server", "10.0.0.2")],
        [_edge("client->server", "client", "server")],
    )

    result = compare_topology_to_ground_truth(inferred, ground_truth)

    assert result.node_precision == result.node_recall == result.node_f1 == 1.0
    assert result.edge_precision == result.edge_recall == result.edge_f1 == 1.0
    assert result.graph_similarity == 1.0
    assert result.inferred_node_count == result.ground_truth_node_count == 2
    assert result.inferred_edge_count == result.ground_truth_edge_count == 1


def test_ground_truth_extra_node_and_edge_drops_recall_not_precision() -> None:
    inferred = _graph(
        "cap-1",
        [_node("cap-1:node:0", "10.0.0.1"), _node("cap-1:node:1", "10.0.0.2")],
        [_edge("cap-1:edge:0", "cap-1:node:0", "cap-1:node:1")],
    )
    ground_truth = _graph(
        "lab-ground-truth",
        [
            _node("client", "10.0.0.1"),
            _node("server", "10.0.0.2"),
            _node("database", "10.0.0.3"),
        ],
        [
            _edge("client->server", "client", "server"),
            _edge("server->database", "server", "database"),
        ],
    )

    result = compare_topology_to_ground_truth(inferred, ground_truth)

    assert result.node_precision == 1.0
    assert result.node_recall < 1.0
    assert result.edge_precision == 1.0
    assert result.edge_recall < 1.0
    assert result.graph_similarity < 1.0


def test_inferred_extra_node_and_edge_drops_precision_not_recall() -> None:
    inferred = _graph(
        "cap-1",
        [
            _node("cap-1:node:0", "10.0.0.1"),
            _node("cap-1:node:1", "10.0.0.2"),
            _node("cap-1:node:2", "10.0.0.9"),
        ],
        [
            _edge("cap-1:edge:0", "cap-1:node:0", "cap-1:node:1"),
            _edge("cap-1:edge:1", "cap-1:node:1", "cap-1:node:2"),
        ],
    )
    ground_truth = _graph(
        "lab-ground-truth",
        [_node("client", "10.0.0.1"), _node("server", "10.0.0.2")],
        [_edge("client->server", "client", "server")],
    )

    result = compare_topology_to_ground_truth(inferred, ground_truth)

    assert result.node_precision < 1.0
    assert result.node_recall == 1.0
    assert result.edge_precision < 1.0
    assert result.edge_recall == 1.0
    assert result.graph_similarity < 1.0


def test_empty_vs_empty_is_perfect_agreement_and_empty_vs_nonempty_is_zero() -> None:
    empty = _graph("empty", [], [])
    nonempty = _graph(
        "lab-ground-truth",
        [_node("client", "10.0.0.1"), _node("server", "10.0.0.2")],
        [_edge("client->server", "client", "server")],
    )

    both_empty = compare_topology_to_ground_truth(empty, empty)
    assert both_empty.node_precision == both_empty.node_recall == both_empty.node_f1 == 1.0
    assert both_empty.edge_precision == both_empty.edge_recall == both_empty.edge_f1 == 1.0
    assert both_empty.graph_similarity == 1.0

    inferred_empty = compare_topology_to_ground_truth(empty, nonempty)
    assert inferred_empty.node_precision == 0.0
    assert inferred_empty.node_recall == 0.0
    assert inferred_empty.edge_precision == 0.0
    assert inferred_empty.edge_recall == 0.0
    assert inferred_empty.graph_similarity == 0.0


def test_edge_matching_ignores_source_target_direction() -> None:
    # Inferred edge is undirected-by-construction (Phase 30); ground truth
    # declares the opposite direction. They must still match as the same edge.
    inferred = _graph(
        "cap-1",
        [_node("cap-1:node:0", "10.0.0.1"), _node("cap-1:node:1", "10.0.0.2")],
        [_edge("cap-1:edge:0", "cap-1:node:1", "cap-1:node:0")],  # 10.0.0.2 -> 10.0.0.1
    )
    ground_truth = _graph(
        "lab-ground-truth",
        [_node("client", "10.0.0.1"), _node("server", "10.0.0.2")],
        [_edge("client->server", "client", "server")],  # 10.0.0.1 -> 10.0.0.2, opposite direction
    )

    result = compare_topology_to_ground_truth(inferred, ground_truth)

    assert result.edge_precision == 1.0
    assert result.edge_recall == 1.0
