"""Phase 60 dynamic path engine unit tests (pure, no Docker)."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.app.models.failure import FailureScenario, FailureType
from backend.app.models.packet import Packet, PacketDirection, TransportProtocol
from backend.app.models.topology import Edge, Node, TopologyGraph
from backend.nettrace.reconstruct import reconstruct_flows
from backend.nettrace.topology.graph import build_topology_graph
from backend.simulation.failure_injection import apply_failure_scenario
from backend.simulation.path_engine import (
    compute_alternate_paths,
    compute_connectivity,
    compute_route_change,
    compute_shortest_path,
)
from experiments.artifacts.io import write_jsonl
from experiments.artifacts.paths import packets_path

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _node(node_id: str) -> Node:
    return Node(node_id=node_id, ip_addresses=["10.0.0.1"], first_observed=BASE, last_observed=BASE)


def _edge(edge_id: str, source: str, target: str, confidence: float) -> Edge:
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


def _chain_graph() -> TopologyGraph:
    # A -(0.9)- B -(0.8)- C
    return _graph(["A", "B", "C"], [_edge("e0", "A", "B", 0.9), _edge("e1", "B", "C", 0.8)])


def _diamond_graph() -> TopologyGraph:
    # A -(0.9)- B -(0.9)- D  (cheap route)
    # A -(0.5)- C -(0.5)- D  (expensive alternate route)
    return _graph(
        ["A", "B", "C", "D"],
        [
            _edge("e_ab", "A", "B", 0.9),
            _edge("e_bd", "B", "D", 0.9),
            _edge("e_ac", "A", "C", 0.5),
            _edge("e_cd", "C", "D", 0.5),
        ],
    )


def _disconnected_graph() -> TopologyGraph:
    return _graph(["A", "B", "C", "D"], [_edge("e0", "A", "B", 0.9), _edge("e1", "C", "D", 0.9)])


def test_shortest_path_cost_matches_negative_log_confidence_sum() -> None:
    graph = _chain_graph()
    result = compute_shortest_path(graph, "A", "C")

    assert result is not None
    assert result.node_ids == ["A", "B", "C"]
    assert result.edge_ids == ["e0", "e1"]
    assert result.cost == pytest.approx(-math.log(0.9) - math.log(0.8))


def test_shortest_path_returns_none_when_disconnected() -> None:
    graph = _disconnected_graph()
    assert compute_shortest_path(graph, "A", "D") is None


def test_shortest_path_returns_none_for_missing_node() -> None:
    graph = _chain_graph()
    assert compute_shortest_path(graph, "A", "no-such-node") is None
    assert compute_shortest_path(graph, "no-such-node", "A") is None


def test_alternate_paths_ranked_by_increasing_cost_on_diamond() -> None:
    graph = _diamond_graph()
    results = compute_alternate_paths(graph, "A", "D", k=5)

    assert len(results) == 2
    assert results[0].node_ids == ["A", "B", "D"]
    assert results[1].node_ids == ["A", "C", "D"]
    assert results[0].cost < results[1].cost


def test_alternate_paths_bounded_by_k() -> None:
    graph = _diamond_graph()
    results = compute_alternate_paths(graph, "A", "D", k=1)
    assert len(results) == 1
    assert results[0].node_ids == ["A", "B", "D"]


def test_alternate_paths_empty_when_disconnected() -> None:
    graph = _disconnected_graph()
    assert compute_alternate_paths(graph, "A", "D") == []


def test_connectivity_reports_two_components() -> None:
    graph = _disconnected_graph()
    result = compute_connectivity(graph)

    assert result.connected_component_count == 2
    assert result.is_fully_connected is False
    assert sorted(result.components) == [["A", "B"], ["C", "D"]]


def test_connectivity_reports_fully_connected() -> None:
    graph = _chain_graph()
    result = compute_connectivity(graph)

    assert result.connected_component_count == 1
    assert result.is_fully_connected is True
    assert result.largest_component_node_ids == ["A", "B", "C"]


def test_route_change_detects_reroute_after_node_failure() -> None:
    graph = _diamond_graph()
    baseline_path = compute_shortest_path(graph, "A", "D")
    assert baseline_path.node_ids == ["A", "B", "D"]  # sanity: B-route is cheaper

    scenario = FailureScenario(scenario_id="s1", failure_type=FailureType.NODE_FAILURE, target_node_id="B")
    failure = apply_failure_scenario(graph, scenario)

    result = compute_route_change(graph, failure.graph, "A", "D", failure=failure)

    assert result.changed is True
    assert result.baseline_path.node_ids == ["A", "B", "D"]
    assert result.current_path.node_ids == ["A", "C", "D"]
    assert result.cost_delta == pytest.approx(result.current_path.cost - result.baseline_path.cost)
    assert result.cost_delta > 0


def test_route_change_reports_unreachable_after_total_disconnection() -> None:
    graph = _chain_graph()
    scenario = FailureScenario(scenario_id="s2", failure_type=FailureType.NODE_FAILURE, target_node_id="B")
    failure = apply_failure_scenario(graph, scenario)

    result = compute_route_change(graph, failure.graph, "A", "C", failure=failure)

    assert result.changed is True
    assert result.baseline_path is not None
    assert result.current_path is None
    assert result.cost_delta is None


def test_route_change_no_change_when_path_identical() -> None:
    graph = _diamond_graph()
    result = compute_route_change(graph, graph, "A", "D")

    assert result.changed is False
    assert result.cost_delta == pytest.approx(0.0)


def test_latency_injection_increases_cost_of_degraded_edge() -> None:
    graph = _graph(["A", "B"], [_edge("e0", "A", "B", 0.9)])
    scenario = FailureScenario(
        scenario_id="s3", failure_type=FailureType.LATENCY_INJECTION, target_node_id="A", latency_ms=100.0
    )
    failure = apply_failure_scenario(graph, scenario)

    without = compute_shortest_path(graph, "A", "B")
    with_latency = compute_shortest_path(failure.graph, "A", "B", failure=failure)

    assert with_latency.cost == pytest.approx(without.cost + 1.0)  # 100.0 / _DEFAULT_LATENCY_COST_SCALE(100.0)


def test_packet_loss_increases_cost_by_negative_log_survival_probability() -> None:
    graph = _graph(["A", "B"], [_edge("e0", "A", "B", 0.9)])
    scenario = FailureScenario(
        scenario_id="s4", failure_type=FailureType.PACKET_LOSS, target_edge_id="e0", packet_loss_ratio=0.3
    )
    failure = apply_failure_scenario(graph, scenario)

    without = compute_shortest_path(graph, "A", "B")
    with_loss = compute_shortest_path(failure.graph, "A", "B", failure=failure)

    assert with_loss.cost == pytest.approx(without.cost - math.log(0.7))


def test_mismatched_failure_graph_raises() -> None:
    graph = _chain_graph()
    other_graph = _diamond_graph()
    scenario = FailureScenario(scenario_id="s5", failure_type=FailureType.NODE_FAILURE, target_node_id="B")
    failure = apply_failure_scenario(other_graph, scenario)

    with pytest.raises(ValueError):
        compute_shortest_path(graph, "A", "C", failure=failure)


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


def test_real_end_to_end_edge_failure_disconnects_only_path(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    packets = [
        _pkt("p0", BASE, "10.0.0.1", 1000, "10.0.0.2", 80, TransportProtocol.TCP),
        _pkt("p1", BASE, "10.0.0.2", 80, "10.0.0.1", 1000, TransportProtocol.TCP),
    ]
    write_jsonl(packets_path(root, "cap-1"), packets)
    reconstruct_flows(root, "cap-1")
    graph = build_topology_graph(root, "cap-1", graph_id="g-real")

    node_a = next(n for n in graph.nodes if "10.0.0.1" in {str(ip) for ip in n.ip_addresses})
    node_b = next(n for n in graph.nodes if "10.0.0.2" in {str(ip) for ip in n.ip_addresses})
    assert compute_shortest_path(graph, node_a.node_id, node_b.node_id) is not None

    edge = graph.edges[0]
    scenario = FailureScenario(scenario_id="s6", failure_type=FailureType.EDGE_FAILURE, target_edge_id=edge.edge_id)
    failure = apply_failure_scenario(graph, scenario)

    assert compute_shortest_path(failure.graph, node_a.node_id, node_b.node_id) is None
