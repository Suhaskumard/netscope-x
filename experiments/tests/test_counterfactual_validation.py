"""Phase 66 counterfactual prediction validation unit tests (pure, no Docker)."""

from __future__ import annotations

import dataclasses
from datetime import datetime, timezone

from backend.app.models.simulation import CounterfactualAction, CounterfactualScenario
from backend.app.models.topology import Edge, Node, TopologyGraph
from backend.simulation.counterfactual_comparison import compare_counterfactual_outcome
from backend.simulation.counterfactual_engine import execute_counterfactual_scenario
from experiments.metrics.counterfactual_validation import (
    ActualCounterfactualOutcome,
    evaluate_counterfactual_prediction,
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
    # A-(0.9)-B-(0.9)-D cheap route; A-(0.5)-C-(0.5)-D expensive route.
    # Removing B leaves a single connected component {A,C,D} -- no fragmentation
    # into singleton components, so the "largest component" approximation used
    # by ActualCounterfactualOutcome exactly matches the predicted side.
    return _graph(
        ["A", "B", "C", "D"],
        [
            _edge("e_ab", "A", "B", 0.9),
            _edge("e_bd", "B", "D", 0.9),
            _edge("e_ac", "A", "C", 0.5),
            _edge("e_cd", "C", "D", 0.5),
        ],
    )


def _diamond_remove_node_b_prediction():
    graph = _diamond_graph()
    scenario = CounterfactualScenario(
        scenario_id="cf1",
        action=CounterfactualAction.REMOVE_NODE,
        baseline_graph_id="g1",
        isolated_graph_id="g1-cf1",
        target_node_id="B",
        created_at=BASE,
    )
    execution = execute_counterfactual_scenario(graph, scenario)
    return compare_counterfactual_outcome(graph, execution)


# Kept as the shared fixture name used by every other test in this file.
_chain_remove_node_b_prediction = _diamond_remove_node_b_prediction


def _perfect_actual_outcome() -> ActualCounterfactualOutcome:
    predicted = _diamond_remove_node_b_prediction()
    return ActualCounterfactualOutcome(
        lab_realizable=True,
        actually_affected_node_ids={si.node_id for si in predicted.service_impacts},
        actual_largest_component_node_ids=list(predicted.connectivity_after.largest_component_node_ids),
        actual_reachable_pairs={
            (rc.source_node_id, rc.target_node_id): rc.current_path is not None for rc in predicted.route_changes
        },
        actual_affected_service_count=len(predicted.service_impacts),
    )


def test_not_lab_realizable_reports_unvalidated() -> None:
    predicted = _chain_remove_node_b_prediction()
    actual = ActualCounterfactualOutcome(lab_realizable=False)

    result = evaluate_counterfactual_prediction(predicted, actual)

    assert result.validated is False
    assert result.unvalidated_reason is not None
    assert result.affected_node_precision is None
    assert result.path_prediction_match_rate is None
    assert result.connectivity_prediction_accuracy is None
    assert result.resilience_indicator_accuracy is None
    assert result.path_prediction_pair_count == 0


def test_perfect_match_scores_near_one_on_all_metrics() -> None:
    predicted = _chain_remove_node_b_prediction()
    actual = _perfect_actual_outcome()

    result = evaluate_counterfactual_prediction(predicted, actual)

    assert result.validated is True
    assert result.affected_node_f1 == 1.0
    assert result.path_prediction_match_rate == 1.0
    assert result.connectivity_prediction_accuracy == 1.0
    assert result.resilience_indicator_accuracy == 1.0
    assert result.resilience_indicator_components_evaluated == ["affected_service_count"]


def test_mismatch_reports_degraded_scores() -> None:
    predicted = _chain_remove_node_b_prediction()
    actual = dataclasses.replace(_perfect_actual_outcome(), actually_affected_node_ids={"B"})

    result = evaluate_counterfactual_prediction(predicted, actual)

    assert result.affected_node_f1 < 1.0
    assert result.path_prediction_match_rate == 1.0
    assert result.connectivity_prediction_accuracy == 1.0


def test_empty_vs_empty_affected_nodes_is_perfect_agreement() -> None:
    predicted = _chain_remove_node_b_prediction()
    modified = dataclasses.replace(predicted, service_impacts=[])
    actual = dataclasses.replace(_perfect_actual_outcome(), actually_affected_node_ids=set())

    result = evaluate_counterfactual_prediction(modified, actual)

    assert result.affected_node_precision == 1.0
    assert result.affected_node_recall == 1.0
    assert result.affected_node_f1 == 1.0


def test_resilience_indicator_skipped_when_not_supplied() -> None:
    predicted = _chain_remove_node_b_prediction()
    actual = dataclasses.replace(_perfect_actual_outcome(), actual_affected_service_count=None)

    result = evaluate_counterfactual_prediction(predicted, actual)

    assert result.resilience_indicator_accuracy is None
    assert result.resilience_indicator_components_evaluated == []
    assert "affected_service_count" in result.resilience_indicator_components_skipped


def test_pair_missing_from_actual_excluded_not_silently_scored() -> None:
    predicted = _chain_remove_node_b_prediction()
    actual = dataclasses.replace(_perfect_actual_outcome(), actual_reachable_pairs={("A", "B"): False})

    result = evaluate_counterfactual_prediction(predicted, actual)

    assert result.path_prediction_pair_count == 1
    assert result.path_prediction_match_rate == 1.0
