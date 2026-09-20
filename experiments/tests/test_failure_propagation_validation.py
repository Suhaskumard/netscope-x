"""Phase 63 digital twin validation unit tests (pure, no Docker).

No real end-to-end test exists in this file: there is no mechanism anywhere
in this codebase to capture a real post-failure "actual" outcome from the
lab (this session has no Docker either). Each test runs the real Phase
61->62 pipeline for the "predicted" side against a synthetic `TopologyGraph`,
then hand-constructs (or hand-overrides via `dataclasses.replace`) an
`ActualFailureOutcome` fixture for the "actual" side -- the closest honest
equivalent to an end-to-end test available this session.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timezone

from backend.app.models.failure import FailureScenario, FailureType
from backend.app.models.topology import Edge, Node, TopologyGraph
from backend.dependency.causal_candidates import CausalCandidate
from backend.simulation.failure_propagation_pipeline import run_failure_propagation_pipeline
from backend.simulation.resilience_indicators import compute_resilience_indicators
from experiments.metrics.failure_propagation_validation import (
    ActualFailureOutcome,
    evaluate_failure_propagation_prediction,
)

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


def _candidate(dependency_id: str, source: str, target: str) -> CausalCandidate:
    return CausalCandidate(
        dependency_id=dependency_id,
        source_node_id=source,
        target_node_id=target,
        strength=0.8,
        temporal_precedence_score=0.6,
        rationale=["synthetic rationale"],
    )


def _diamond_b_failure():
    graph = _diamond_graph()
    scenario = FailureScenario(scenario_id="s1", failure_type=FailureType.NODE_FAILURE, target_node_id="B")
    result = run_failure_propagation_pipeline(graph, scenario, candidates=[_candidate("dep-1", "B", "D")])
    resilience = compute_resilience_indicators(graph, result)
    return graph, result, resilience


def _perfect_actual_outcome() -> ActualFailureOutcome:
    return ActualFailureOutcome(
        actually_affected_node_ids={"B", "D"},
        actual_largest_component_node_ids=["A", "C", "D"],
        actual_reachable_pairs={("A", "B"): False, ("D", "B"): False},
        actual_affected_service_count=2,
        actual_alternative_path_available=False,
    )


def test_perfect_match_scores_near_one_on_all_four_metrics() -> None:
    _, result, resilience = _diamond_b_failure()
    actual = _perfect_actual_outcome()

    scores = evaluate_failure_propagation_prediction(result, resilience, actual)

    assert scores.affected_node_f1 == 1.0
    assert scores.path_prediction_match_rate == 1.0
    assert scores.path_prediction_pair_count == 2
    assert scores.connectivity_prediction_accuracy == 1.0
    assert scores.resilience_indicator_accuracy == 1.0
    assert scores.resilience_indicator_components_evaluated == ["affected_service_count", "alternative_path_available"]


def test_affected_node_mismatch_drops_only_that_metric() -> None:
    _, result, resilience = _diamond_b_failure()
    actual = dataclasses.replace(_perfect_actual_outcome(), actually_affected_node_ids={"B"})

    scores = evaluate_failure_propagation_prediction(result, resilience, actual)

    assert scores.affected_node_precision == 0.5
    assert scores.affected_node_recall == 1.0
    assert scores.affected_node_f1 < 1.0
    assert scores.path_prediction_match_rate == 1.0
    assert scores.connectivity_prediction_accuracy == 1.0
    assert scores.resilience_indicator_accuracy == 1.0


def test_path_prediction_mismatch_drops_only_that_metric() -> None:
    _, result, resilience = _diamond_b_failure()
    actual = dataclasses.replace(
        _perfect_actual_outcome(), actual_reachable_pairs={("A", "B"): True, ("D", "B"): False}
    )

    scores = evaluate_failure_propagation_prediction(result, resilience, actual)

    assert scores.affected_node_f1 == 1.0
    assert scores.path_prediction_match_rate == 0.5
    assert scores.connectivity_prediction_accuracy == 1.0
    assert scores.resilience_indicator_accuracy == 1.0


def test_connectivity_mismatch_drops_only_that_metric() -> None:
    _, result, resilience = _diamond_b_failure()
    actual = dataclasses.replace(_perfect_actual_outcome(), actual_largest_component_node_ids=["A"])

    scores = evaluate_failure_propagation_prediction(result, resilience, actual)

    assert scores.affected_node_f1 == 1.0
    assert scores.path_prediction_match_rate == 1.0
    assert scores.connectivity_prediction_accuracy < 1.0
    assert scores.connectivity_prediction_error > 0.0
    assert scores.resilience_indicator_accuracy == 1.0


def test_resilience_indicator_mismatch_drops_only_that_metric() -> None:
    _, result, resilience = _diamond_b_failure()
    actual = dataclasses.replace(
        _perfect_actual_outcome(), actual_affected_service_count=5, actual_alternative_path_available=True
    )

    scores = evaluate_failure_propagation_prediction(result, resilience, actual)

    assert scores.affected_node_f1 == 1.0
    assert scores.path_prediction_match_rate == 1.0
    assert scores.connectivity_prediction_accuracy == 1.0
    assert scores.resilience_indicator_accuracy is not None
    assert scores.resilience_indicator_accuracy < 1.0


def test_empty_vs_empty_reports_perfect_node_and_path_scores() -> None:
    graph, result, _ = _diamond_b_failure()
    empty_result = dataclasses.replace(result, service_impacts=[], newly_unreachable_node_ids=[], route_changes=[])
    empty_resilience = compute_resilience_indicators(graph, empty_result)
    actual = ActualFailureOutcome(
        actually_affected_node_ids=set(),
        actual_largest_component_node_ids=[],
        actual_reachable_pairs={},
    )

    scores = evaluate_failure_propagation_prediction(empty_result, empty_resilience, actual)

    assert scores.affected_node_f1 == 1.0
    assert scores.path_prediction_match_rate == 1.0
    assert scores.path_prediction_pair_count == 0
    assert scores.resilience_indicator_accuracy is None
    assert set(scores.resilience_indicator_components_skipped) == {
        "path_degradation_score",
        "bottleneck_node_ids",
        "affected_service_count",
        "alternative_path_available",
    }


def test_resilience_indicator_not_evaluable_when_both_optional_fields_unsupplied() -> None:
    _, result, resilience = _diamond_b_failure()
    actual = dataclasses.replace(
        _perfect_actual_outcome(), actual_affected_service_count=None, actual_alternative_path_available=None
    )

    scores = evaluate_failure_propagation_prediction(result, resilience, actual)

    assert scores.resilience_indicator_accuracy is None
    assert scores.resilience_indicator_components_evaluated == []
    assert "affected_service_count" in scores.resilience_indicator_components_skipped
    assert "alternative_path_available" in scores.resilience_indicator_components_skipped


def test_resilience_indicator_partial_evaluation() -> None:
    _, result, resilience = _diamond_b_failure()
    actual = dataclasses.replace(_perfect_actual_outcome(), actual_alternative_path_available=None)

    scores = evaluate_failure_propagation_prediction(result, resilience, actual)

    assert scores.resilience_indicator_accuracy == 1.0
    assert scores.resilience_indicator_components_evaluated == ["affected_service_count"]
    assert "alternative_path_available" in scores.resilience_indicator_components_skipped


def test_evaluate_never_mutates_inputs() -> None:
    _, result, resilience = _diamond_b_failure()
    actual = _perfect_actual_outcome()

    service_impacts_before = list(result.service_impacts)
    route_changes_before = list(result.route_changes)
    actual_pairs_before = dict(actual.actual_reachable_pairs)

    evaluate_failure_propagation_prediction(result, resilience, actual)

    assert result.service_impacts == service_impacts_before
    assert result.route_changes == route_changes_before
    assert actual.actual_reachable_pairs == actual_pairs_before


def test_pair_missing_from_actual_excluded_not_silently_scored() -> None:
    _, result, resilience = _diamond_b_failure()
    actual = dataclasses.replace(_perfect_actual_outcome(), actual_reachable_pairs={("A", "B"): False})

    scores = evaluate_failure_propagation_prediction(result, resilience, actual)

    assert scores.path_prediction_pair_count == 1
    assert scores.path_prediction_match_rate == 1.0
