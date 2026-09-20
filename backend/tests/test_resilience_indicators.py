"""Phase 62 resilience indicators unit tests (pure, no Docker)."""

from __future__ import annotations

import dataclasses
import math
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.app.models.failure import FailureScenario, FailureType, ResilienceIndicators
from backend.app.models.packet import Packet, PacketDirection, TransportProtocol
from backend.app.models.topology import Edge, Node, TopologyGraph
from backend.dependency.causal_candidates import CausalCandidate
from backend.nettrace.reconstruct import reconstruct_flows
from backend.nettrace.topology.graph import build_topology_graph
from backend.simulation.failure_injection import apply_failure_scenario
from backend.simulation.failure_propagation_pipeline import run_failure_propagation_pipeline
from backend.simulation.path_engine import compute_route_change
from backend.simulation.resilience_indicators import (
    _UNREACHABLE_PATH_PENALTY,
    compute_resilience_indicators,
)
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


def _bowtie_graph() -> TopologyGraph:
    # B -(0.9)- A -(0.9)- M -(0.9)- D -(0.9)- E ; M is the sole bridge node.
    return _graph(
        ["A", "B", "M", "D", "E"],
        [
            _edge("e_ab", "A", "B"),
            _edge("e_am", "A", "M"),
            _edge("e_md", "M", "D"),
            _edge("e_de", "D", "E"),
        ],
    )


def _triangle_chain_graph() -> TopologyGraph:
    # Triangle A-B-C (redundant), then a plain chain C-D-E.
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


def _candidate(dependency_id: str, source: str, target: str) -> CausalCandidate:
    return CausalCandidate(
        dependency_id=dependency_id,
        source_node_id=source,
        target_node_id=target,
        strength=0.8,
        temporal_precedence_score=0.6,
        rationale=["synthetic rationale"],
    )


def test_diamond_node_failure_reports_full_metrics() -> None:
    graph = _diamond_graph()
    scenario = FailureScenario(scenario_id="s1", failure_type=FailureType.NODE_FAILURE, target_node_id="B")
    result = run_failure_propagation_pipeline(graph, scenario, candidates=[_candidate("dep-1", "B", "D")])

    indicators = compute_resilience_indicators(graph, result)

    assert isinstance(indicators, ResilienceIndicators)
    assert indicators.scenario_id == "s1"
    assert 0.0 <= indicators.connectivity_ratio <= 1.0
    assert 0.0 <= indicators.reachable_node_ratio <= 1.0
    assert indicators.affected_service_count == len(result.service_impacts)
    assert indicators.path_degradation_score >= 0.0
    assert indicators.bottleneck_node_ids == ["C"]  # C becomes the sole cut-vertex once B is gone
    assert isinstance(indicators.alternative_path_available, bool)


def test_chain_node_failure_reports_reduced_connectivity() -> None:
    graph = _chain_graph()
    scenario = FailureScenario(scenario_id="s2", failure_type=FailureType.NODE_FAILURE, target_node_id="B")
    result = run_failure_propagation_pipeline(graph, scenario, candidates=[])

    indicators = compute_resilience_indicators(graph, result)

    assert indicators.connectivity_ratio == pytest.approx(1 / 3)
    assert indicators.reachable_node_ratio == pytest.approx(0.0)


def test_connectivity_ratio_and_reachable_node_ratio_diverge_on_fragmenting_failure() -> None:
    graph = _bowtie_graph()
    scenario = FailureScenario(scenario_id="s3", failure_type=FailureType.NODE_FAILURE, target_node_id="M")
    result = run_failure_propagation_pipeline(graph, scenario, candidates=[])

    indicators = compute_resilience_indicators(graph, result)

    assert indicators.connectivity_ratio == pytest.approx(0.4)
    assert indicators.reachable_node_ratio == pytest.approx(0.8)
    assert indicators.connectivity_ratio != indicators.reachable_node_ratio


def test_affected_service_count_matches_len_service_impacts() -> None:
    graph = _diamond_graph()
    scenario = FailureScenario(scenario_id="s4", failure_type=FailureType.NODE_FAILURE, target_node_id="B")
    result = run_failure_propagation_pipeline(graph, scenario, candidates=[_candidate("dep-1", "B", "D")])

    indicators = compute_resilience_indicators(graph, result)

    assert indicators.affected_service_count == len(result.service_impacts)
    assert indicators.affected_service_count > 0


def test_path_degradation_score_penalizes_fully_unreachable_route_not_zero() -> None:
    graph = _chain_graph()
    scenario = FailureScenario(scenario_id="s5", failure_type=FailureType.NODE_FAILURE, target_node_id="B")
    result = run_failure_propagation_pipeline(graph, scenario, candidates=[])

    indicators = compute_resilience_indicators(graph, result)

    assert len(result.route_changes) == 2
    assert indicators.path_degradation_score == pytest.approx(2 * _UNREACHABLE_PATH_PENALTY)


def test_path_degradation_score_sums_positive_deltas_for_still_reachable_routes() -> None:
    graph = _diamond_graph()
    scenario = FailureScenario(
        scenario_id="s6", failure_type=FailureType.LATENCY_INJECTION, target_node_id="B", latency_ms=100.0
    )
    result = run_failure_propagation_pipeline(graph, scenario, candidates=[])

    indicators = compute_resilience_indicators(graph, result)

    injection = apply_failure_scenario(graph, scenario)
    expected = sum(
        max(compute_route_change(graph, injection.graph, rc.source_node_id, rc.target_node_id, failure=injection).cost_delta, 0.0)
        for rc in result.route_changes
    )
    assert expected > 0.0
    assert indicators.path_degradation_score == pytest.approx(expected)


def test_path_degradation_score_ignores_pairs_with_no_baseline_route() -> None:
    graph = _diamond_graph()
    scenario = FailureScenario(scenario_id="s7", failure_type=FailureType.NODE_FAILURE, target_node_id="B")
    result = run_failure_propagation_pipeline(graph, scenario, candidates=[])

    no_baseline_route_change = dataclasses.replace(
        result.route_changes[0], baseline_path=None, current_path=None, changed=False, cost_delta=None
    )
    modified_result = dataclasses.replace(result, route_changes=[no_baseline_route_change])

    indicators = compute_resilience_indicators(graph, modified_result)

    assert indicators.path_degradation_score == pytest.approx(0.0)


def test_bottleneck_node_ids_reports_newly_emergent_articulation_point() -> None:
    graph = _triangle_chain_graph()
    scenario = FailureScenario(scenario_id="s8", failure_type=FailureType.EDGE_FAILURE, target_edge_id="e_ac")
    result = run_failure_propagation_pipeline(graph, scenario, candidates=[])

    indicators = compute_resilience_indicators(graph, result)

    assert "B" in indicators.bottleneck_node_ids


def test_bottleneck_node_ids_excludes_preexisting_articulation_points() -> None:
    graph = _triangle_chain_graph()
    scenario = FailureScenario(scenario_id="s9", failure_type=FailureType.EDGE_FAILURE, target_edge_id="e_ac")
    result = run_failure_propagation_pipeline(graph, scenario, candidates=[])

    indicators = compute_resilience_indicators(graph, result)

    assert "C" not in indicators.bottleneck_node_ids


def test_alternative_path_available_true_when_genuine_second_route_exists() -> None:
    graph = _diamond_graph()
    scenario = FailureScenario(
        scenario_id="s10", failure_type=FailureType.LATENCY_INJECTION, target_node_id="A", latency_ms=50.0
    )
    result = run_failure_propagation_pipeline(graph, scenario, candidates=[])

    indicators = compute_resilience_indicators(graph, result)

    assert indicators.alternative_path_available is True


def test_alternative_path_available_false_when_only_one_route_survives() -> None:
    graph = _chain_graph()
    scenario = FailureScenario(
        scenario_id="s11", failure_type=FailureType.LATENCY_INJECTION, target_node_id="B", latency_ms=50.0
    )
    result = run_failure_propagation_pipeline(graph, scenario, candidates=[])

    indicators = compute_resilience_indicators(graph, result)

    assert indicators.alternative_path_available is False


def test_alternative_path_available_false_when_route_changes_empty() -> None:
    graph = _diamond_graph()
    scenario = FailureScenario(scenario_id="s12", failure_type=FailureType.NODE_FAILURE, target_node_id="B")
    result = run_failure_propagation_pipeline(graph, scenario, candidates=[])
    modified_result = dataclasses.replace(result, route_changes=[])

    indicators = compute_resilience_indicators(graph, modified_result)

    assert indicators.alternative_path_available is False


def test_compute_resilience_indicators_never_mutates_inputs() -> None:
    graph = _diamond_graph()
    node_ids_before = {n.node_id for n in graph.nodes}
    edge_ids_before = {e.edge_id for e in graph.edges}

    scenario = FailureScenario(scenario_id="s13", failure_type=FailureType.NODE_FAILURE, target_node_id="B")
    result = run_failure_propagation_pipeline(graph, scenario, candidates=[_candidate("dep-1", "B", "D")])
    injection_node_ids_before = {n.node_id for n in result.injection.graph.nodes}
    injection_edge_ids_before = {e.edge_id for e in result.injection.graph.edges}

    compute_resilience_indicators(graph, result)

    assert {n.node_id for n in graph.nodes} == node_ids_before
    assert {e.edge_id for e in graph.edges} == edge_ids_before
    assert {n.node_id for n in result.injection.graph.nodes} == injection_node_ids_before
    assert {e.edge_id for e in result.injection.graph.edges} == injection_edge_ids_before


def test_resilience_indicators_schema_validates() -> None:
    graph = _diamond_graph()
    scenario = FailureScenario(scenario_id="s14", failure_type=FailureType.NODE_FAILURE, target_node_id="B")
    result = run_failure_propagation_pipeline(graph, scenario, candidates=[_candidate("dep-1", "B", "D")])

    indicators = compute_resilience_indicators(graph, result)

    round_tripped = ResilienceIndicators(**indicators.model_dump())
    assert round_tripped == indicators


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


def test_end_to_end_over_reconstructed_topology(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    packets = [
        _pkt("p0", BASE, "10.0.0.1", 1000, "10.0.0.2", 80, TransportProtocol.TCP),
        _pkt("p1", BASE, "10.0.0.2", 80, "10.0.0.1", 1000, TransportProtocol.TCP),
    ]
    write_jsonl(packets_path(root, "cap-1"), packets)
    reconstruct_flows(root, "cap-1")
    graph = build_topology_graph(root, "cap-1", graph_id="g-real")

    node_a = next(n for n in graph.nodes if "10.0.0.1" in {str(ip) for ip in n.ip_addresses})
    scenario = FailureScenario(scenario_id="s15", failure_type=FailureType.NODE_FAILURE, target_node_id=node_a.node_id)
    result = run_failure_propagation_pipeline(graph, scenario, candidates=[])

    indicators = compute_resilience_indicators(graph, result)

    assert isinstance(indicators, ResilienceIndicators)
    assert indicators.scenario_id == "s15"
