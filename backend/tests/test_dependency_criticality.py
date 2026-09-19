"""Phase 55 criticality analysis unit tests (pure, no Docker)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.app.models.packet import Packet, PacketDirection, TransportProtocol
from backend.app.models.topology import Edge, Node, TopologyGraph
from backend.dependency.criticality import METRIC_RATIONALE, compute_graph_criticality
from backend.nettrace.reconstruct import reconstruct_flows
from backend.nettrace.topology.discovery import discover_nodes
from backend.nettrace.topology.edges import discover_edges
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
    return TopologyGraph(
        graph_id="g1",
        generated_at=BASE,
        nodes=[_node(n) for n in node_ids],
        edges=edges,
    )


def test_star_topology_hub_is_articulation_point_with_real_impact() -> None:
    # Hub H connects to leaves A, B, C; no other edges.
    graph = _graph(
        ["H", "A", "B", "C"],
        [
            _edge("e0", "A", "H"),
            _edge("e1", "B", "H"),
            _edge("e2", "C", "H"),
        ],
    )

    report = compute_graph_criticality(graph)
    by_id = {s.node_id: s for s in report.node_scores}

    assert by_id["H"].is_articulation_point is True
    assert by_id["H"].degree_centrality == max(s.degree_centrality for s in report.node_scores)
    assert by_id["H"].betweenness_centrality == max(s.betweenness_centrality for s in report.node_scores)
    # Removing H leaves A, B, C each isolated (3 singleton components);
    # largest remaining component size = 1, so 2 nodes are stranded.
    assert by_id["H"].path_dependency_impact == 2
    for leaf in ("A", "B", "C"):
        assert by_id[leaf].is_articulation_point is False
        assert by_id[leaf].path_dependency_impact == 0


def test_linear_chain_interior_nodes_are_articulation_points() -> None:
    graph = _graph(
        ["A", "B", "C", "D"],
        [
            _edge("e0", "A", "B"),
            _edge("e1", "B", "C"),
            _edge("e2", "C", "D"),
        ],
    )

    report = compute_graph_criticality(graph)
    by_id = {s.node_id: s for s in report.node_scores}

    assert by_id["B"].is_articulation_point is True
    assert by_id["C"].is_articulation_point is True
    assert by_id["A"].is_articulation_point is False
    assert by_id["D"].is_articulation_point is False
    # Removing B: {A} and {C, D} -> largest=2, stranded = 3 - 2 = 1.
    assert by_id["B"].path_dependency_impact == 1
    assert by_id["C"].path_dependency_impact == 1


def test_cycle_has_no_articulation_points_and_full_redundancy() -> None:
    graph = _graph(
        ["A", "B", "C", "D"],
        [
            _edge("e0", "A", "B"),
            _edge("e1", "B", "C"),
            _edge("e2", "C", "D"),
            _edge("e3", "D", "A"),
        ],
    )

    report = compute_graph_criticality(graph)

    assert all(not s.is_articulation_point for s in report.node_scores)
    assert all(s.path_dependency_impact == 0 for s in report.node_scores)
    assert report.node_connectivity == 2


def test_isolated_node_has_zero_scores_and_no_confidence() -> None:
    graph = _graph(["A", "B", "ISOLATED"], [_edge("e0", "A", "B")])

    report = compute_graph_criticality(graph)
    isolated = next(s for s in report.node_scores if s.node_id == "ISOLATED")

    assert isolated.degree_centrality == 0.0
    assert isolated.betweenness_centrality == 0.0
    assert isolated.is_articulation_point is False
    assert isolated.path_dependency_impact == 0
    assert isolated.mean_incident_edge_confidence is None


def test_mean_incident_edge_confidence_matches_hand_computed_value() -> None:
    graph = _graph(
        ["A", "B", "C"],
        [
            _edge("e0", "A", "B", confidence=0.4),
            _edge("e1", "A", "C", confidence=0.8),
        ],
    )

    report = compute_graph_criticality(graph)
    a_score = next(s for s in report.node_scores if s.node_id == "A")

    assert a_score.mean_incident_edge_confidence == (0.4 + 0.8) / 2


def test_node_connectivity_reflects_topology_shape() -> None:
    chain = _graph(["A", "B", "C"], [_edge("e0", "A", "B"), _edge("e1", "B", "C")])
    assert compute_graph_criticality(chain).node_connectivity == 1

    cycle = _graph(
        ["A", "B", "C", "D"],
        [_edge("e0", "A", "B"), _edge("e1", "B", "C"), _edge("e2", "C", "D"), _edge("e3", "D", "A")],
    )
    assert compute_graph_criticality(cycle).node_connectivity == 2

    disconnected = _graph(["A", "B", "C", "D"], [_edge("e0", "A", "B"), _edge("e1", "C", "D")])
    assert compute_graph_criticality(disconnected).node_connectivity == 0
    assert compute_graph_criticality(disconnected).connected_component_count == 2


def test_empty_graph_returns_empty_report() -> None:
    graph = _graph([], [])

    report = compute_graph_criticality(graph)

    assert report.node_scores == []
    assert report.node_connectivity == 0
    assert report.connected_component_count == 0


def test_metric_rationale_documents_every_reported_metric() -> None:
    for metric in (
        "degree_centrality",
        "betweenness_centrality",
        "is_articulation_point",
        "path_dependency_impact",
        "connectivity",
    ):
        assert metric in METRIC_RATIONALE
        assert len(METRIC_RATIONALE[metric]) > 0


def test_deterministic_across_repeated_calls() -> None:
    graph = _graph(
        ["H", "A", "B", "C"],
        [_edge("e0", "A", "H"), _edge("e1", "B", "H"), _edge("e2", "C", "H")],
    )

    first = compute_graph_criticality(graph)
    second = compute_graph_criticality(graph)

    assert first == second


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


def test_real_end_to_end_via_build_topology_graph(tmp_path: Path) -> None:
    """A real hub-and-spoke capture: a gateway node relays between two
    otherwise-unconnected clusters -- confirms the gateway is discovered
    as a genuine articulation point from a real, pipeline-produced graph,
    not a hand-built fixture."""
    root = tmp_path / "artifacts"
    packets = [
        _pkt("p0", BASE, "10.0.0.1", 1000, "10.0.0.2", 80, TransportProtocol.TCP),
        _pkt("p1", BASE, "10.0.0.2", 80, "10.0.0.1", 1000, TransportProtocol.TCP),
        _pkt("p2", BASE + timedelta(seconds=1), "10.0.0.2", 2000, "10.0.0.3", 81, TransportProtocol.TCP),
        _pkt("p3", BASE + timedelta(seconds=1), "10.0.0.3", 81, "10.0.0.2", 2000, TransportProtocol.TCP),
    ]
    write_jsonl(packets_path(root, "cap-1"), packets)
    reconstruct_flows(root, "cap-1")

    from backend.nettrace.topology.graph import build_topology_graph

    graph = build_topology_graph(root, "cap-1", "g1")
    report = compute_graph_criticality(graph)

    assert len(report.node_scores) == 3
    for score in report.node_scores:
        assert 0.0 <= score.degree_centrality <= 1.0
        assert 0.0 <= score.betweenness_centrality <= 1.0
        if score.mean_incident_edge_confidence is not None:
            assert 0.0 <= score.mean_incident_edge_confidence <= 1.0

    nodes = discover_nodes(root, "cap-1")
    edges = discover_edges(root, "cap-1", nodes)
    gateway_id = next(n.node_id for n in nodes if str(n.ip_addresses[0]) == "10.0.0.2")
    gateway_score = next(s for s in report.node_scores if s.node_id == gateway_id)

    assert gateway_score.is_articulation_point is True
    assert gateway_score.path_dependency_impact == 1
    assert len(edges) == 2
