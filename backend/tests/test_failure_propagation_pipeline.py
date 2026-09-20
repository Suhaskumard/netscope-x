"""Phase 61 failure propagation pipeline unit tests (pure, no Docker)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.app.models.behavior import RoleClassification, ServiceRole
from backend.app.models.failure import FailureScenario, FailureType
from backend.app.models.packet import Packet, PacketDirection, TransportProtocol
from backend.app.models.topology import Edge, Node, TopologyGraph
from backend.dependency.causal_candidates import CausalCandidate
from backend.nettrace.reconstruct import reconstruct_flows
from backend.nettrace.topology.graph import build_topology_graph
from backend.simulation.failure_propagation_pipeline import run_failure_propagation_pipeline
from experiments.artifacts.io import write_jsonl
from experiments.artifacts.paths import packets_path

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _node(node_id: str) -> Node:
    return Node(node_id=node_id, ip_addresses=["10.0.0.1"], first_observed=BASE, last_observed=BASE)


def _edge(edge_id: str, source: str, target: str, confidence: float = 0.9) -> Edge:
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


def _chain_graph() -> TopologyGraph:
    return _graph(["A", "B", "C"], [_edge("e0", "A", "B"), _edge("e1", "B", "C")])


def _candidate(dependency_id: str, source: str, target: str) -> CausalCandidate:
    return CausalCandidate(
        dependency_id=dependency_id,
        source_node_id=source,
        target_node_id=target,
        strength=0.8,
        temporal_precedence_score=0.6,
        rationale=["synthetic rationale"],
    )


def test_node_failure_propagates_and_reports_routing_impact() -> None:
    graph = _diamond_graph()
    scenario = FailureScenario(scenario_id="s1", failure_type=FailureType.NODE_FAILURE, target_node_id="B")
    candidates = [_candidate("dep-1", "B", "D")]

    result = run_failure_propagation_pipeline(graph, scenario, candidates)

    orders = {impact.affected_node_id: impact.order.value for impact in result.propagation_impacts}
    assert orders == {"B": "primary", "D": "secondary"}

    assert len(result.route_changes) == 2
    pair_sources = {rc.source_node_id for rc in result.route_changes}
    assert pair_sources == {"A", "D"}
    assert all(rc.target_node_id == "B" for rc in result.route_changes)

    assert result.newly_unreachable_node_ids == []

    service_impact_by_node = {si.node_id: si for si in result.service_impacts}
    assert "D" in service_impact_by_node
    d_impact = service_impact_by_node["D"]
    assert d_impact.reason == "propagation"
    assert d_impact.propagation_order == "secondary"
    assert d_impact.newly_unreachable is False
    assert d_impact.role_classification is None


def test_edge_failure_has_no_propagation_impacts() -> None:
    graph = _diamond_graph()
    scenario = FailureScenario(scenario_id="s2", failure_type=FailureType.EDGE_FAILURE, target_edge_id="e_ab")

    result = run_failure_propagation_pipeline(graph, scenario, candidates=[])

    assert result.propagation_impacts == []
    assert len(result.route_changes) == 1
    assert {result.route_changes[0].source_node_id, result.route_changes[0].target_node_id} == {"A", "B"}
    assert result.connectivity_before.is_fully_connected is True
    assert result.connectivity_after.is_fully_connected is True  # A still reachable to B via C/D


def test_node_failure_with_no_causal_candidates_still_reports_primary() -> None:
    graph = _diamond_graph()
    scenario = FailureScenario(scenario_id="s3", failure_type=FailureType.NODE_FAILURE, target_node_id="B")

    result = run_failure_propagation_pipeline(graph, scenario, candidates=[])

    assert len(result.propagation_impacts) == 1
    assert result.propagation_impacts[0].affected_node_id == "B"
    assert result.propagation_impacts[0].order.value == "primary"


def test_total_disconnection_reports_newly_unreachable_node() -> None:
    graph = _chain_graph()
    scenario = FailureScenario(scenario_id="s4", failure_type=FailureType.NODE_FAILURE, target_node_id="B")

    result = run_failure_propagation_pipeline(graph, scenario, candidates=[])

    assert result.connectivity_before.is_fully_connected is True
    assert result.connectivity_after.is_fully_connected is False
    assert result.newly_unreachable_node_ids == ["C"]


def test_service_impact_reason_is_propagation_plus_routing_when_both_apply() -> None:
    graph = _chain_graph()
    scenario = FailureScenario(scenario_id="s5", failure_type=FailureType.NODE_FAILURE, target_node_id="B")
    candidates = [_candidate("dep-1", "B", "C")]

    result = run_failure_propagation_pipeline(graph, scenario, candidates)

    service_impact_by_node = {si.node_id: si for si in result.service_impacts}
    assert service_impact_by_node["C"].reason == "propagation+routing"
    assert service_impact_by_node["C"].newly_unreachable is True
    assert service_impact_by_node["C"].propagation_order == "secondary"


def test_role_classification_passed_through_when_supplied() -> None:
    graph = _chain_graph()
    scenario = FailureScenario(scenario_id="s6", failure_type=FailureType.NODE_FAILURE, target_node_id="B")
    classification = RoleClassification(
        node_id="C", computed_at=BASE, role_probabilities={ServiceRole.DATABASE: 1.0}
    )

    result = run_failure_propagation_pipeline(graph, scenario, candidates=[], role_classifications={"C": classification})

    service_impact_by_node = {si.node_id: si for si in result.service_impacts}
    assert service_impact_by_node["C"].role_classification is classification


def test_pipeline_never_mutates_input_graph() -> None:
    graph = _diamond_graph()
    node_ids_before = {n.node_id for n in graph.nodes}
    edge_ids_before = {e.edge_id for e in graph.edges}

    scenario = FailureScenario(scenario_id="s7", failure_type=FailureType.NODE_FAILURE, target_node_id="B")
    run_failure_propagation_pipeline(graph, scenario, candidates=[_candidate("dep-1", "B", "D")])

    assert {n.node_id for n in graph.nodes} == node_ids_before
    assert {e.edge_id for e in graph.edges} == edge_ids_before


def test_route_changes_bounded_to_former_neighbors_not_all_pairs() -> None:
    # E hangs off A too, but is not a neighbor of B -- must not appear in route_changes.
    graph = _graph(
        ["A", "B", "C", "D", "E"],
        [
            _edge("e_ab", "A", "B"),
            _edge("e_bd", "B", "D"),
            _edge("e_ac", "A", "C", 0.5),
            _edge("e_cd", "C", "D", 0.5),
            _edge("e_ae", "A", "E"),
        ],
    )
    scenario = FailureScenario(scenario_id="s8", failure_type=FailureType.NODE_FAILURE, target_node_id="B")

    result = run_failure_propagation_pipeline(graph, scenario, candidates=[])

    pair_nodes = {rc.source_node_id for rc in result.route_changes}
    assert len(result.route_changes) == 2
    assert pair_nodes == {"A", "D"}


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


def test_real_end_to_end_pipeline_over_discovered_topology(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    packets = [
        _pkt("p0", BASE, "10.0.0.1", 1000, "10.0.0.2", 80, TransportProtocol.TCP),
        _pkt("p1", BASE, "10.0.0.2", 80, "10.0.0.1", 1000, TransportProtocol.TCP),
    ]
    write_jsonl(packets_path(root, "cap-1"), packets)
    reconstruct_flows(root, "cap-1")
    graph = build_topology_graph(root, "cap-1", graph_id="g-real")

    node_a = next(n for n in graph.nodes if "10.0.0.1" in {str(ip) for ip in n.ip_addresses})
    scenario = FailureScenario(scenario_id="s9", failure_type=FailureType.NODE_FAILURE, target_node_id=node_a.node_id)

    result = run_failure_propagation_pipeline(graph, scenario, candidates=[])

    assert result.propagation_impacts[0].affected_node_id == node_a.node_id
    assert result.injection.removed_node_ids == [node_a.node_id]
