"""Phase 59 controlled failure injection unit tests (pure, no Docker)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.app.models.failure import FailureScenario, FailureType
from backend.app.models.packet import Packet, PacketDirection, TransportProtocol
from backend.app.models.topology import Edge, Node, TopologyGraph
from backend.nettrace.reconstruct import reconstruct_flows
from backend.nettrace.topology.graph import build_topology_graph
from backend.simulation.failure_injection import apply_failure_scenario
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
    # Star: H connects to A, B, C.
    return TopologyGraph(
        graph_id="g1",
        generated_at=BASE,
        nodes=[_node(n) for n in ("H", "A", "B", "C")],
        edges=[_edge("e0", "A", "H"), _edge("e1", "B", "H"), _edge("e2", "C", "H")],
    )


def test_node_failure_removes_node_and_incident_edges() -> None:
    graph = _graph()
    scenario = FailureScenario(scenario_id="s1", failure_type=FailureType.NODE_FAILURE, target_node_id="H")

    result = apply_failure_scenario(graph, scenario)

    assert result.removed_node_ids == ["H"]
    assert sorted(result.removed_edge_ids) == ["e0", "e1", "e2"]
    assert result.degraded_edge_ids == []
    assert {n.node_id for n in result.graph.nodes} == {"A", "B", "C"}
    assert result.graph.edges == []


def test_edge_failure_removes_only_that_edge() -> None:
    graph = _graph()
    scenario = FailureScenario(scenario_id="s2", failure_type=FailureType.EDGE_FAILURE, target_edge_id="e0")

    result = apply_failure_scenario(graph, scenario)

    assert result.removed_node_ids == []
    assert result.removed_edge_ids == ["e0"]
    assert result.degraded_edge_ids == []
    assert {n.node_id for n in result.graph.nodes} == {"H", "A", "B", "C"}
    assert {e.edge_id for e in result.graph.edges} == {"e1", "e2"}


@pytest.mark.parametrize("failure_type", [FailureType.LATENCY_INJECTION, FailureType.SERVICE_DEGRADATION])
def test_soft_node_failure_leaves_structure_unchanged_but_marks_incident_edges(failure_type) -> None:
    graph = _graph()
    kwargs = {"latency_ms": 50.0} if failure_type == FailureType.LATENCY_INJECTION else {}
    scenario = FailureScenario(
        scenario_id="s3", failure_type=failure_type, target_node_id="H", **kwargs
    )

    result = apply_failure_scenario(graph, scenario)

    assert result.removed_node_ids == []
    assert result.removed_edge_ids == []
    assert sorted(result.degraded_edge_ids) == ["e0", "e1", "e2"]
    assert {n.node_id for n in result.graph.nodes} == {"H", "A", "B", "C"}
    assert {e.edge_id for e in result.graph.edges} == {"e0", "e1", "e2"}


def test_packet_loss_targeting_an_edge_degrades_only_that_edge() -> None:
    graph = _graph()
    scenario = FailureScenario(
        scenario_id="s4",
        failure_type=FailureType.PACKET_LOSS,
        target_edge_id="e1",
        packet_loss_ratio=0.5,
    )

    result = apply_failure_scenario(graph, scenario)

    assert result.degraded_edge_ids == ["e1"]
    assert result.removed_node_ids == []
    assert result.removed_edge_ids == []


def test_bandwidth_reduction_targeting_a_node_degrades_its_incident_edges() -> None:
    graph = _graph()
    scenario = FailureScenario(
        scenario_id="s5",
        failure_type=FailureType.BANDWIDTH_REDUCTION,
        target_node_id="H",
        bandwidth_reduction_ratio=0.7,
    )

    result = apply_failure_scenario(graph, scenario)

    assert sorted(result.degraded_edge_ids) == ["e0", "e1", "e2"]


def test_untargeted_ratio_failure_raises() -> None:
    graph = _graph()
    scenario = FailureScenario(
        scenario_id="s6", failure_type=FailureType.PACKET_LOSS, packet_loss_ratio=0.5
    )

    with pytest.raises(ValueError):
        apply_failure_scenario(graph, scenario)


def test_unknown_target_node_id_raises() -> None:
    graph = _graph()
    scenario = FailureScenario(
        scenario_id="s7", failure_type=FailureType.NODE_FAILURE, target_node_id="no-such-node"
    )

    with pytest.raises(ValueError):
        apply_failure_scenario(graph, scenario)


def test_unknown_target_edge_id_raises() -> None:
    graph = _graph()
    scenario = FailureScenario(
        scenario_id="s8", failure_type=FailureType.EDGE_FAILURE, target_edge_id="no-such-edge"
    )

    with pytest.raises(ValueError):
        apply_failure_scenario(graph, scenario)


def test_result_graph_is_a_new_object_and_input_is_untouched() -> None:
    graph = _graph()
    original_node_ids = {n.node_id for n in graph.nodes}
    original_edge_ids = {e.edge_id for e in graph.edges}
    scenario = FailureScenario(scenario_id="s9", failure_type=FailureType.NODE_FAILURE, target_node_id="H")

    result = apply_failure_scenario(graph, scenario)

    assert result.graph is not graph
    assert {n.node_id for n in graph.nodes} == original_node_ids
    assert {e.edge_id for e in graph.edges} == original_edge_ids


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


def test_real_end_to_end_node_failure_over_a_discovered_topology(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    packets = [
        _pkt("p0", BASE, "10.0.0.1", 1000, "10.0.0.2", 80, TransportProtocol.TCP),
        _pkt("p1", BASE, "10.0.0.2", 80, "10.0.0.1", 1000, TransportProtocol.TCP),
        _pkt(
            "p2",
            BASE + timedelta(seconds=10),
            "10.0.0.1",
            1001,
            "10.0.0.3",
            80,
            TransportProtocol.TCP,
        ),
        _pkt(
            "p3",
            BASE + timedelta(seconds=10),
            "10.0.0.3",
            80,
            "10.0.0.1",
            1001,
            TransportProtocol.TCP,
        ),
    ]
    write_jsonl(packets_path(root, "cap-1"), packets)
    reconstruct_flows(root, "cap-1")
    graph = build_topology_graph(root, "cap-1", graph_id="g-real")

    node_a = next(n for n in graph.nodes if "10.0.0.1" in {str(ip) for ip in n.ip_addresses})
    scenario = FailureScenario(
        scenario_id="s10", failure_type=FailureType.NODE_FAILURE, target_node_id=node_a.node_id
    )

    result = apply_failure_scenario(graph, scenario)

    assert len(result.graph.nodes) == len(graph.nodes) - 1
    assert len(result.graph.edges) == len(graph.edges) - len(result.removed_edge_ids)
    assert node_a.node_id not in {n.node_id for n in result.graph.nodes}
    # The rebuilt graph is internally consistent (passes its own validators).
    assert isinstance(result.graph, TopologyGraph)
