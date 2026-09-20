"""Phase 67 experiment recommendation engine unit tests (pure, no Docker)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from backend.app.models.failure import FailureType
from backend.app.models.packet import Packet, PacketDirection, TransportProtocol
from backend.app.models.topology import Edge, Node, TopologyGraph
from backend.dependency.experiment_recommendations import (
    _RECOMMENDATION_DISCLAIMER,
    generate_experiment_recommendations,
)
from backend.nettrace.reconstruct import reconstruct_flows
from backend.nettrace.topology.graph import build_topology_graph
from experiments.artifacts.io import write_jsonl
from experiments.artifacts.paths import packets_path

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _node(node_id: str) -> Node:
    return Node(node_id=node_id, ip_addresses=["10.0.0.1"], first_observed=BASE, last_observed=BASE)


def _edge(edge_id: str, source: str, target: str, confidence: float = 0.8) -> Edge:
    return Edge(
        edge_id=edge_id,
        source_node_id=source,
        target_node_id=target,
        confidence=confidence,
        evidence=["synthetic evidence"],
        observation_count=1,
        first_observed=BASE,
        last_observed=BASE,
        protocols=["TCP"],
    )


def _graph(node_ids, edges) -> TopologyGraph:
    return TopologyGraph(graph_id="g1", generated_at=BASE, nodes=[_node(n) for n in node_ids], edges=edges)


def _triangle_chain_graph() -> TopologyGraph:
    # Triangle A-B-C (redundant) plus a plain chain C-D-E.
    # C and D are both real articulation points; A, B, E are not.
    return _graph(
        ["A", "B", "C", "D", "E"],
        [
            _edge("e_ab", "A", "B"),
            _edge("e_bc", "B", "C"),
            _edge("e_ac", "A", "C"),
            _edge("e_cd", "C", "D"),
            _edge("e_de", "D", "E"),
        ],
    )


def _bipartite_graph() -> TopologyGraph:
    # K_{2,3}: hubs A, B each connect to leaves X, Y, Z; no edges among hubs
    # or among leaves. No articulation points exist anywhere (every pair has
    # a redundant path), but A/B sit on more shortest paths than X/Y/Z.
    return _graph(
        ["A", "B", "X", "Y", "Z"],
        [
            _edge("e_ax", "A", "X"),
            _edge("e_ay", "A", "Y"),
            _edge("e_az", "A", "Z"),
            _edge("e_bx", "B", "X"),
            _edge("e_by", "B", "Y"),
            _edge("e_bz", "B", "Z"),
        ],
    )


def _cycle_graph() -> TopologyGraph:
    # A plain 4-cycle: no articulation points, all nodes structurally symmetric.
    return _graph(
        ["A", "B", "C", "D"],
        [_edge("e0", "A", "B"), _edge("e1", "B", "C"), _edge("e2", "C", "D"), _edge("e3", "D", "A")],
    )


def test_articulation_points_recommended_for_removal_ranked_by_severity() -> None:
    graph = _triangle_chain_graph()

    recommendations = generate_experiment_recommendations(graph)

    spof = [r for r in recommendations if r.category == "structural_single_point_of_failure"]
    assert {r.node_id for r in spof} == {"C", "D"}
    assert all(r.suggested_scenario.failure_type == FailureType.NODE_FAILURE for r in spof)
    assert [r.node_id for r in spof] == ["C", "D"]  # C's path_dependency_impact (2) > D's (1)


def test_chokepoints_recommended_for_non_articulation_high_betweenness_nodes() -> None:
    graph = _bipartite_graph()

    recommendations = generate_experiment_recommendations(graph)

    spof = [r for r in recommendations if r.category == "structural_single_point_of_failure"]
    chokepoints = [r for r in recommendations if r.category == "routing_chokepoint"]
    assert spof == []
    assert {r.node_id for r in chokepoints} == {"A", "B"}
    assert all(r.suggested_scenario.failure_type == FailureType.SERVICE_DEGRADATION for r in chokepoints)


def test_symmetric_cycle_produces_no_recommendations() -> None:
    graph = _cycle_graph()

    recommendations = generate_experiment_recommendations(graph)

    assert recommendations == []


def test_recommendations_are_deterministic() -> None:
    graph = _triangle_chain_graph()

    first = generate_experiment_recommendations(graph)
    second = generate_experiment_recommendations(graph)

    assert [r.recommendation_id for r in first] == [r.recommendation_id for r in second]
    assert [r.node_id for r in first] == [r.node_id for r in second]


def test_reasoning_cites_real_path_dependency_impact_value() -> None:
    graph = _triangle_chain_graph()

    recommendations = generate_experiment_recommendations(graph)

    node_c = next(r for r in recommendations if r.node_id == "C")
    assert node_c.evidence.path_dependency_impact == 2
    assert any("path_dependency_impact=2" in line for line in node_c.reasoning)


def test_every_recommendation_ends_with_disclaimer() -> None:
    graph = _triangle_chain_graph()

    recommendations = generate_experiment_recommendations(graph)

    assert recommendations
    for r in recommendations:
        assert r.reasoning[-1] == _RECOMMENDATION_DISCLAIMER


def _pkt(pid, t, src_ip, src_port, dst_ip, dst_port, protocol) -> Packet:
    return Packet(
        packet_id=pid,
        capture_id="cap-1",
        timestamp=t,
        src_ip=src_ip,
        dst_ip=dst_ip,
        src_port=src_port,
        dst_port=dst_port,
        protocol=protocol,
        size_bytes=100,
        direction=PacketDirection.UNKNOWN,
    )


def test_real_end_to_end_over_discovered_topology(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    packets = [
        _pkt("p0", BASE, "10.0.0.1", 1000, "10.0.0.2", 80, TransportProtocol.TCP),
        _pkt("p1", BASE, "10.0.0.2", 80, "10.0.0.1", 1000, TransportProtocol.TCP),
    ]
    write_jsonl(packets_path(root, "cap-1"), packets)
    reconstruct_flows(root, "cap-1")
    graph = build_topology_graph(root, "cap-1", graph_id="g-real")

    recommendations = generate_experiment_recommendations(graph)

    for r in recommendations:
        assert r.suggested_scenario.target_node_id is not None
