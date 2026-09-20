"""Phase 65 counterfactual graph engine unit tests (pure, no Docker)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.app.models.packet import Packet, PacketDirection, TransportProtocol
from backend.app.models.simulation import CounterfactualAction, CounterfactualScenario
from backend.app.models.topology import Edge, Node, TopologyGraph
from backend.nettrace.reconstruct import reconstruct_flows
from backend.nettrace.topology.graph import build_topology_graph
from backend.simulation.counterfactual_engine import execute_counterfactual_scenario
from experiments.artifacts.io import write_jsonl
from experiments.artifacts.paths import packets_path

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _node(node_id: str) -> Node:
    return Node(node_id=node_id, ip_addresses=["10.0.0.1"], first_observed=BASE, last_observed=BASE)


def _edge(edge_id: str, source: str, target: str) -> Edge:
    return Edge(
        edge_id=edge_id,
        source_node_id=source,
        target_node_id=target,
        confidence=0.8,
        evidence=["synthetic evidence"],
        observation_count=1,
        first_observed=BASE,
        last_observed=BASE,
        protocols=["TCP"],
    )


def _graph() -> TopologyGraph:
    # Star: H connects to A, B, C. D is isolated (no edges) -- a valid ADD_ROUTE target.
    return TopologyGraph(
        graph_id="g1",
        generated_at=BASE,
        nodes=[_node(n) for n in ("H", "A", "B", "C", "D")],
        edges=[_edge("e0", "A", "H"), _edge("e1", "B", "H"), _edge("e2", "C", "H")],
    )


def _scenario(action: CounterfactualAction, scenario_id: str = "cf1", **kwargs) -> CounterfactualScenario:
    return CounterfactualScenario(
        scenario_id=scenario_id,
        action=action,
        baseline_graph_id="g1",
        isolated_graph_id=f"g1-{scenario_id}",
        created_at=BASE,
        **kwargs,
    )


def test_remove_node_removes_node_and_incident_edges() -> None:
    graph = _graph()
    scenario = _scenario(CounterfactualAction.REMOVE_NODE, target_node_id="H")

    result = execute_counterfactual_scenario(graph, scenario)

    assert result.removed_node_ids == ["H"]
    assert sorted(result.removed_edge_ids) == ["e0", "e1", "e2"]
    assert result.degraded_edge_ids == []
    assert result.added_edge_id is None
    assert {n.node_id for n in result.graph.nodes} == {"A", "B", "C", "D"}
    assert result.graph.edges == []
    assert result.graph.graph_id == "g1-cf1"


def test_remove_node_raises_for_unknown_target() -> None:
    graph = _graph()
    scenario = _scenario(CounterfactualAction.REMOVE_NODE, target_node_id="no-such-node")

    with pytest.raises(ValueError):
        execute_counterfactual_scenario(graph, scenario)


def test_remove_edge_removes_only_that_edge() -> None:
    graph = _graph()
    scenario = _scenario(CounterfactualAction.REMOVE_EDGE, target_edge_id="e0")

    result = execute_counterfactual_scenario(graph, scenario)

    assert result.removed_node_ids == []
    assert result.removed_edge_ids == ["e0"]
    assert sorted(e.edge_id for e in result.graph.edges) == ["e1", "e2"]


def test_increase_latency_degrades_incident_edges_without_removal() -> None:
    graph = _graph()
    scenario = _scenario(CounterfactualAction.INCREASE_LATENCY, target_node_id="H", magnitude=50.0)

    result = execute_counterfactual_scenario(graph, scenario)

    assert result.removed_node_ids == []
    assert result.removed_edge_ids == []
    assert sorted(result.degraded_edge_ids) == ["e0", "e1", "e2"]
    assert len(result.graph.edges) == 3


def test_reduce_bandwidth_via_target_node_id_degrades_incident_edges() -> None:
    graph = _graph()
    scenario = _scenario(CounterfactualAction.REDUCE_BANDWIDTH, target_node_id="H", magnitude=0.5)

    result = execute_counterfactual_scenario(graph, scenario)

    assert sorted(result.degraded_edge_ids) == ["e0", "e1", "e2"]


def test_reduce_bandwidth_via_target_edge_id_degrades_only_that_edge() -> None:
    graph = _graph()
    scenario = _scenario(CounterfactualAction.REDUCE_BANDWIDTH, target_edge_id="e0", magnitude=0.5)

    result = execute_counterfactual_scenario(graph, scenario)

    assert result.degraded_edge_ids == ["e0"]


def test_increase_traffic_degrades_incident_edges() -> None:
    graph = _graph()
    scenario = _scenario(CounterfactualAction.INCREASE_TRAFFIC, target_node_id="H", magnitude=2.0)

    result = execute_counterfactual_scenario(graph, scenario)

    assert sorted(result.degraded_edge_ids) == ["e0", "e1", "e2"]


def test_add_route_adds_one_hypothetical_edge() -> None:
    graph = _graph()
    scenario = _scenario(CounterfactualAction.ADD_ROUTE, source_node_id="A", target_node_id="D")

    result = execute_counterfactual_scenario(graph, scenario)

    assert result.removed_node_ids == []
    assert result.removed_edge_ids == []
    assert result.degraded_edge_ids == []
    assert result.added_edge_id is not None
    assert len(result.graph.edges) == 4

    new_edge = next(e for e in result.graph.edges if e.edge_id == result.added_edge_id)
    assert {new_edge.source_node_id, new_edge.target_node_id} == {"A", "D"}
    assert new_edge.confidence == 0.5
    assert new_edge.observation_count == 1
    assert new_edge.protocols == ["unknown"]
    assert "hypothetical" in new_edge.evidence[0]
    assert result.graph.graph_id == "g1-cf1"


def test_add_route_raises_when_already_connected() -> None:
    graph = _graph()
    scenario = _scenario(CounterfactualAction.ADD_ROUTE, source_node_id="A", target_node_id="H")

    with pytest.raises(ValueError):
        execute_counterfactual_scenario(graph, scenario)


def test_add_route_raises_for_unknown_endpoint() -> None:
    graph = _graph()
    scenario = _scenario(CounterfactualAction.ADD_ROUTE, source_node_id="A", target_node_id="no-such-node")

    with pytest.raises(ValueError):
        execute_counterfactual_scenario(graph, scenario)


def test_raises_when_baseline_graph_id_mismatches() -> None:
    graph = _graph()
    scenario = CounterfactualScenario(
        scenario_id="cf-mismatch",
        action=CounterfactualAction.REMOVE_NODE,
        baseline_graph_id="not-g1",
        isolated_graph_id="g1-cf-mismatch",
        target_node_id="H",
        created_at=BASE,
    )

    with pytest.raises(ValueError):
        execute_counterfactual_scenario(graph, scenario)


def test_execution_never_mutates_input_graph() -> None:
    graph = _graph()
    node_ids_before = {n.node_id for n in graph.nodes}
    edge_ids_before = {e.edge_id for e in graph.edges}

    scenario = _scenario(CounterfactualAction.REMOVE_NODE, target_node_id="H")
    execute_counterfactual_scenario(graph, scenario)

    assert {n.node_id for n in graph.nodes} == node_ids_before
    assert {e.edge_id for e in graph.edges} == edge_ids_before


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


def test_real_end_to_end_remove_node_over_discovered_topology(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    packets = [
        _pkt("p0", BASE, "10.0.0.1", 1000, "10.0.0.2", 80, TransportProtocol.TCP),
        _pkt("p1", BASE, "10.0.0.2", 80, "10.0.0.1", 1000, TransportProtocol.TCP),
    ]
    write_jsonl(packets_path(root, "cap-1"), packets)
    reconstruct_flows(root, "cap-1")
    graph = build_topology_graph(root, "cap-1", graph_id="g-real")

    node_a = next(n for n in graph.nodes if "10.0.0.1" in {str(ip) for ip in n.ip_addresses})
    scenario = CounterfactualScenario(
        scenario_id="cf-real",
        action=CounterfactualAction.REMOVE_NODE,
        baseline_graph_id="g-real",
        isolated_graph_id="g-real-cf-real",
        target_node_id=node_a.node_id,
        created_at=BASE,
    )

    result = execute_counterfactual_scenario(graph, scenario)

    assert result.removed_node_ids == [node_a.node_id]
    assert node_a.node_id not in {n.node_id for n in result.graph.nodes}
