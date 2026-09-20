"""Counterfactual Prediction Validation (spec Phase 66, FR-1.38 second half /
RQ7: "compare counterfactual predictions against actual controlled experiment
outcomes and shall not claim correctness without this measurement").

Mirrors `experiments/metrics/failure_propagation_validation.py` (Phase 63,
RQ6) closely, narrowed to three of its four metrics plus one resilience
component -- `path_degradation_score`/`bottleneck_node_ids`-style "actual"
values remain honestly un-evaluable from a minimal caller-supplied outcome,
exactly the reasoning Phase 63 already established for the RQ6 case.

The one genuinely new piece RQ7 requires beyond Phase 63's pattern: lab-
realizability gating. RQ7's own text (`docs/research/research_questions.md`)
is explicit: "Where a counterfactual is not realizable in the lab (e.g., a
purely hypothetical route that doesn't exist), report the prediction as
unvalidated rather than implying it was tested." Whether a given
`CounterfactualScenario` corresponds to something that could actually be
done in the lab is a caller judgment, not inferable from `CounterfactualAction`
alone (a `REMOVE_NODE` is usually realizable but not universally; an
`ADD_ROUTE` might correspond to real spare cabling in some lab topologies) --
so `ActualCounterfactualOutcome.lab_realizable` is caller-supplied, and
`False` short-circuits every metric to `None`/empty rather than computing
anything, an honest "not tested" rather than a fabricated score.

Returns a plain `@dataclass(frozen=True)`, never `MetricResult`
(`backend/app/models/metric.py`) -- no experiment registry exists yet;
`MetricContext.COUNTERFACTUAL` stays reserved and unpopulated, deferred to
Phase 68, exactly as `MetricContext.PATHFORGE` is for Phase 63's own module.

Never imports `simulator.ground_truth` (spec Sec4;
`scripts/check_ground_truth_boundary.py` would reject it if it did) -- the
actual outcome is caller-supplied, not self-fetched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple

from backend.simulation.counterfactual_comparison import CounterfactualComparisonResult

_NOT_LAB_REALIZABLE_REASON = "counterfactual not lab-realizable (RQ7)"


@dataclass(frozen=True)
class ActualCounterfactualOutcome:
    lab_realizable: bool
    actually_affected_node_ids: Set[str] = field(default_factory=set)
    actual_largest_component_node_ids: List[str] = field(default_factory=list)
    actual_reachable_pairs: Dict[Tuple[str, str], bool] = field(default_factory=dict)
    actual_affected_service_count: Optional[int] = None


@dataclass(frozen=True)
class CounterfactualValidationResult:
    scenario_id: str
    computed_at: datetime
    validated: bool
    unvalidated_reason: Optional[str]

    affected_node_precision: Optional[float]
    affected_node_recall: Optional[float]
    affected_node_f1: Optional[float]

    path_prediction_match_rate: Optional[float]
    path_prediction_pair_count: int

    connectivity_prediction_error: Optional[float]
    connectivity_prediction_accuracy: Optional[float]

    resilience_indicator_accuracy: Optional[float]
    resilience_indicator_components_evaluated: List[str]
    resilience_indicator_components_skipped: List[str]


def _precision_recall_f1(matched: int, predicted: int, actual: int) -> Tuple[float, float, float]:
    """Empty-vs-empty is perfect agreement (1.0/1.0/1.0); empty-vs-nonempty is
    0.0 on whichever side has nothing -- matching `topology_comparison.py`'s
    and `failure_propagation_validation.py`'s own established convention."""
    if predicted == 0 and actual == 0:
        return 1.0, 1.0, 1.0
    precision = (matched / predicted) if predicted else 0.0
    recall = (matched / actual) if actual else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return precision, recall, f1


def _affected_node_scores(
    predicted: CounterfactualComparisonResult, actual: ActualCounterfactualOutcome
) -> Tuple[float, float, float]:
    predicted_node_ids = {si.node_id for si in predicted.service_impacts}
    matched = len(predicted_node_ids & actual.actually_affected_node_ids)
    return _precision_recall_f1(matched, len(predicted_node_ids), len(actual.actually_affected_node_ids))


def _path_prediction_match_rate(
    predicted: CounterfactualComparisonResult, actual: ActualCounterfactualOutcome
) -> Tuple[float, int]:
    evaluated = 0
    correct = 0
    for route_change in predicted.route_changes:
        pair = (route_change.source_node_id, route_change.target_node_id)
        if pair not in actual.actual_reachable_pairs:
            continue
        evaluated += 1
        predicted_reachable = route_change.current_path is not None
        if predicted_reachable == actual.actual_reachable_pairs[pair]:
            correct += 1
    if evaluated == 0:
        return 1.0, 0
    return correct / evaluated, evaluated


def _connectivity_prediction_accuracy(
    predicted: CounterfactualComparisonResult, actual: ActualCounterfactualOutcome
) -> Tuple[float, float]:
    before_size = len(predicted.connectivity_before.largest_component_node_ids)
    after_size = len(predicted.connectivity_after.largest_component_node_ids)
    predicted_connectivity_ratio = 1.0 if before_size == 0 else after_size / before_size
    actual_connectivity_ratio = (
        1.0 if before_size == 0 else len(actual.actual_largest_component_node_ids) / before_size
    )

    original_node_ids: Set[str] = {
        node_id for component in predicted.connectivity_before.components for node_id in component
    }
    predicted_reachable_node_ids: Set[str] = {
        node_id for component in predicted.connectivity_after.components if len(component) >= 2 for node_id in component
    }
    predicted_reachable_node_ratio = (
        1.0 if not original_node_ids else len(predicted_reachable_node_ids) / len(original_node_ids)
    )
    actual_reachable_node_ratio = (
        1.0
        if not original_node_ids
        else len(actual.actual_largest_component_node_ids) / len(original_node_ids)
    )

    error = (
        abs(predicted_connectivity_ratio - actual_connectivity_ratio)
        + abs(predicted_reachable_node_ratio - actual_reachable_node_ratio)
    ) / 2
    return error, 1.0 - error


def _resilience_indicator_accuracy(
    predicted: CounterfactualComparisonResult, actual: ActualCounterfactualOutcome
) -> Tuple[Optional[float], List[str], List[str]]:
    evaluated: List[str] = []
    skipped: List[str] = ["path_degradation_score", "bottleneck_node_ids"]

    if actual.actual_affected_service_count is None:
        skipped.append("affected_service_count")
        return None, evaluated, skipped

    predicted_count = len(predicted.service_impacts)
    actual_count = actual.actual_affected_service_count
    denominator = max(predicted_count, actual_count, 1)
    score = 1.0 - abs(predicted_count - actual_count) / denominator
    evaluated.append("affected_service_count")
    return score, evaluated, skipped


def evaluate_counterfactual_prediction(
    predicted: CounterfactualComparisonResult,
    actual: ActualCounterfactualOutcome,
) -> CounterfactualValidationResult:
    """Scores a Phase 66 `CounterfactualComparisonResult` prediction against a
    caller-supplied `ActualCounterfactualOutcome`. Returns an honestly
    unvalidated result (`validated=False`, every metric `None`) when
    `actual.lab_realizable` is `False`, per RQ7's own "report as unvalidated"
    requirement.
    """
    scenario_id = predicted.scenario.scenario_id
    computed_at = datetime.now(timezone.utc)

    if not actual.lab_realizable:
        return CounterfactualValidationResult(
            scenario_id=scenario_id,
            computed_at=computed_at,
            validated=False,
            unvalidated_reason=_NOT_LAB_REALIZABLE_REASON,
            affected_node_precision=None,
            affected_node_recall=None,
            affected_node_f1=None,
            path_prediction_match_rate=None,
            path_prediction_pair_count=0,
            connectivity_prediction_error=None,
            connectivity_prediction_accuracy=None,
            resilience_indicator_accuracy=None,
            resilience_indicator_components_evaluated=[],
            resilience_indicator_components_skipped=["affected_service_count"],
        )

    precision, recall, f1 = _affected_node_scores(predicted, actual)
    match_rate, pair_count = _path_prediction_match_rate(predicted, actual)
    connectivity_error, connectivity_accuracy = _connectivity_prediction_accuracy(predicted, actual)
    resilience_accuracy, evaluated, skipped = _resilience_indicator_accuracy(predicted, actual)

    return CounterfactualValidationResult(
        scenario_id=scenario_id,
        computed_at=computed_at,
        validated=True,
        unvalidated_reason=None,
        affected_node_precision=precision,
        affected_node_recall=recall,
        affected_node_f1=f1,
        path_prediction_match_rate=match_rate,
        path_prediction_pair_count=pair_count,
        connectivity_prediction_error=connectivity_error,
        connectivity_prediction_accuracy=connectivity_accuracy,
        resilience_indicator_accuracy=resilience_accuracy,
        resilience_indicator_components_evaluated=evaluated,
        resilience_indicator_components_skipped=skipped,
    )
