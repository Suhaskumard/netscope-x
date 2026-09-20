"""Phase 66 counterfactual outcome comparison unit tests (pure, no Docker)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.app.models.packet import Packet, PacketDirection, TransportProtocol
from backend.app.models.simulation import CounterfactualAction, CounterfactualScenario
from backend.app.models.topology import Edge, Node, TopologyGraph
from backend.dependency.causal_candidates import CausalCandidate
from backend.dependency.failure_propagation import propagate_failure
from backend.nettrace.reconstruct import reconstruct_flows
from backend.nettrace.topology.graph import build_topology_graph
from backend.simulation.counterfactual_comparison import compare_counterfactual_outcome
from backend.simulation.counterfactual_engine import execute_counterfactual_scenario
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
    return _graph(
        ["A", "B", "C", "D"],
        [
            _edge("e_ab", "A", "B", 0.9),
            _edge("e_bd", "B", "D", 0.9),
            _edge("e_ac", "A", "C", 0.5),
            _edge("e_cd", "C", "D", 0.5),
        ],
    )


def _diamond_plus_isolated_e_graph() -> TopologyGraph:
    graph = _diamond_graph()
    return TopologyGraph(
        graph_id="g1",
        generated_at=BASE,
        nodes=graph.nodes + [_node("E")],
        edges=graph.edges,
    )


def _chain_graph() -> TopologyGraph:
    return _graph(["A", "B", "C"], [_edge("e0", "A", "B"), _edge("e1", "B", "C")])


def _scenario(action: CounterfactualAction, scenario_id: str = "cf1", **kwargs) -> CounterfactualScenario:
    return CounterfactualScenario(
        scenario_id=scenario_id,
        action=action,
        baseline_graph_id="g1",
        isolated_graph_id=f"g1-{scenario_id}",
        created_at=BASE,
        **kwargs,
    )


def _candidate(dependency_id: str, source: str, target: str) -> CausalCandidate:
    return CausalCandidate(
        dependency_id=dependency_id,
        source_node_id=source,
        target_node_id=target,
        strength=0.8,
        temporal_precedence_score=0.6,
        rationale=["synthetic rationale"],
    )


def test_remove_node_creates_new_bottleneck_and_changes_routes() -> None:
    graph = _diamond_graph()
    scenario = _scenario(CounterfactualAction.REMOVE_NODE, target_node_id="B")
    execution = execute_counterfactual_scenario(graph, scenario)

    result = compare_counterfactual_outcome(graph, execution)

    assert "C" in result.bottleneck_node_ids
    assert len(result.route_changes) == 2
    assert all(rc.current_path is None for rc in result.route_changes)
    assert result.total_latency_delta > 0
    assert result.newly_unreachable_node_ids == []


def test_remove_node_splits_connectivity_and_propagates_structurally() -> None:
    graph = _chain_graph()
    scenario = _scenario(CounterfactualAction.REMOVE_NODE, target_node_id="B")
    execution = execute_counterfactual_scenario(graph, scenario)

    result = compare_counterfactual_outcome(graph, execution)

    assert result.connectivity_before.is_fully_connected is True
    assert result.connectivity_after.is_fully_connected is False
    assert result.newly_unreachable_node_ids == ["C"]
    assert len(result.structural_propagation_impacts) == 1
    impact = result.structural_propagation_impacts[0]
    assert impact.node_id == "C"
    assert impact.hop_distance == 1
    assert impact.order == "SECONDARY"

    service_impact_by_node = {si.node_id: si for si in result.service_impacts}
    assert service_impact_by_node["C"].reason == "newly_unreachable+route_changed"
    assert service_impact_by_node["B"].reason == "removed+route_changed"


def test_remove_edge_with_alternate_route_shows_real_cost_delta() -> None:
    graph = _diamond_graph()
    scenario = _scenario(CounterfactualAction.REMOVE_EDGE, target_edge_id="e_ab")
    execution = execute_counterfactual_scenario(graph, scenario)

    result = compare_counterfactual_outcome(graph, execution)

    assert result.connectivity_before.largest_component_node_ids == result.connectivity_after.largest_component_node_ids
    assert len(result.route_changes) == 1
    route_change = result.route_changes[0]
    assert route_change.changed is True
    assert route_change.cost_delta == pytest.approx(result.total_latency_delta)
    assert result.total_latency_delta > 0


def test_increase_latency_adapter_produces_nonzero_delta_with_unchanged_connectivity() -> None:
    graph = _diamond_graph()
    scenario = _scenario(CounterfactualAction.INCREASE_LATENCY, target_node_id="B", magnitude=100.0)
    execution = execute_counterfactual_scenario(graph, scenario)

    result = compare_counterfactual_outcome(graph, execution)

    assert result.connectivity_before.largest_component_node_ids == result.connectivity_after.largest_component_node_ids
    assert len(result.route_changes) == 2
    for rc in result.route_changes:
        assert rc.cost_delta == pytest.approx(1.0)
    assert result.total_latency_delta == pytest.approx(2.0)


def test_reduce_bandwidth_out_of_range_magnitude_raises() -> None:
    graph = _diamond_graph()
    scenario = _scenario(CounterfactualAction.REDUCE_BANDWIDTH, target_node_id="B", magnitude=1.5)
    execution = execute_counterfactual_scenario(graph, scenario)

    with pytest.raises(ValidationError):
        compare_counterfactual_outcome(graph, execution)


def test_increase_traffic_has_no_adapter_and_zero_latency_delta() -> None:
    graph = _diamond_graph()
    scenario = _scenario(CounterfactualAction.INCREASE_TRAFFIC, target_node_id="B", magnitude=2.0)
    execution = execute_counterfactual_scenario(graph, scenario)

    result = compare_counterfactual_outcome(graph, execution)

    assert result.total_latency_delta == pytest.approx(0.0)
    assert all(rc.changed is False for rc in result.route_changes)


def test_add_route_shows_new_route_and_no_structural_propagation() -> None:
    graph = _diamond_plus_isolated_e_graph()
    scenario = _scenario(CounterfactualAction.ADD_ROUTE, source_node_id="D", target_node_id="E")
    execution = execute_counterfactual_scenario(graph, scenario)

    result = compare_counterfactual_outcome(graph, execution)

    assert len(result.route_changes) == 1
    route_change = result.route_changes[0]
    assert route_change.baseline_path is None
    assert route_change.current_path is not None
    assert route_change.changed is True
    assert result.structural_propagation_impacts == []
    assert result.newly_unreachable_node_ids == []


def test_propagation_axis_structural_only_without_candidates() -> None:
    graph = _chain_graph()
    scenario = _scenario(CounterfactualAction.REMOVE_NODE, target_node_id="B")
    execution = execute_counterfactual_scenario(graph, scenario)

    result = compare_counterfactual_outcome(graph, execution, candidates=None)

    assert result.causal_propagation_evaluated is False
    assert result.causal_propagation_impacts == []
    assert len(result.structural_propagation_impacts) == 1


def test_propagation_axis_causal_matches_direct_propagate_failure_call() -> None:
    graph = _chain_graph()
    scenario = _scenario(CounterfactualAction.REMOVE_NODE, target_node_id="B")
    execution = execute_counterfactual_scenario(graph, scenario)
    candidates = [_candidate("dep-1", "B", "C")]

    result = compare_counterfactual_outcome(graph, execution, candidates=candidates)

    assert result.causal_propagation_evaluated is True
    expected = propagate_failure(candidates, scenario.scenario_id, "B")
    assert result.causal_propagation_impacts == expected


def test_baseline_graph_id_mismatch_raises() -> None:
    graph = _chain_graph()
    scenario = _scenario(CounterfactualAction.REMOVE_NODE, target_node_id="B")
    execution = execute_counterfactual_scenario(graph, scenario)

    other_graph = TopologyGraph(graph_id="not-g1", generated_at=BASE, nodes=graph.nodes, edges=graph.edges)

    with pytest.raises(ValueError):
        compare_counterfactual_outcome(other_graph, execution)


def test_comparison_never_mutates_inputs() -> None:
    graph = _diamond_graph()
    scenario = _scenario(CounterfactualAction.REMOVE_NODE, target_node_id="B")
    execution = execute_counterfactual_scenario(graph, scenario)

    node_ids_before = {n.node_id for n in graph.nodes}
    edge_ids_before = {e.edge_id for e in graph.edges}
    execution_node_ids_before = {n.node_id for n in execution.graph.nodes}
    execution_edge_ids_before = {e.edge_id for e in execution.graph.edges}

    compare_counterfactual_outcome(graph, execution)

    assert {n.node_id for n in graph.nodes} == node_ids_before
    assert {e.edge_id for e in graph.edges} == edge_ids_before
    assert {n.node_id for n in execution.graph.nodes} == execution_node_ids_before
    assert {e.edge_id for e in execution.graph.edges} == execution_edge_ids_before


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
    execution = execute_counterfactual_scenario(graph, scenario)

    result = compare_counterfactual_outcome(graph, execution)

    assert result.scenario.scenario_id == "cf-real"
