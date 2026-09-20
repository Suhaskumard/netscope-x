"""Digital Twin Validation (spec Phase 63, FR-1.38: "compare digital-twin/
counterfactual predictions against actual controlled experiment outcomes and
shall not claim correctness without this measurement" -- RQ6 half only; RQ7's
counterfactual half is Phase 66, out of scope here; `CounterfactualAction`/
`CounterfactualScenario` (`backend/app/models/simulation.py`) are untouched).

Honesty / limitations -- read first, this is the most important fact about
this module: RQ6's own experiment design has four steps -- (1) record the
digital twin's predicted propagation, (2) execute the real failure in the
isolated lab, (3) capture the actual impact, (4) score prediction against
reality. Steps (2)/(3) cannot be performed this session: `simulator/
ground_truth/` has never captured a post-failure "actual outcome" (only
static steady-state topology/roles/paths), and this session has no Docker.
This mirrors an extremely well-established project convention (e.g. Phase
36/37's role classifier, "verified only against synthetic labeled fixtures,
no Docker"). This module implements and verifies only step (4): a real,
deterministic scoring function over a caller-supplied `ActualFailureOutcome`.
It does NOT build a real capture mechanism -- fabricating one now, with no
Docker to verify it against, would itself risk violating spec §21 ("No Fake
Metrics"). `ActualFailureOutcome` is deliberately capture-mechanism-agnostic
so a future phase (real Docker-lab work, or Phase 68's evaluation matrix) can
populate it for real without this module changing. This does not make the
module fake work: the scoring logic itself is real, deterministic, and
unit-tested here, exactly as Phase 36/37's classifier/calibration code was
real despite no real lab data being available to fit/score it against.

Follows the exact precedent of `experiments/metrics/topology_comparison.py`
(Phase 32), `role_calibration.py` (Phase 37), `anomaly_evaluation.py` (Phase
42): pure function, no I/O, returns a plain `@dataclass(frozen=True)`, never
`MetricResult` (`backend/app/models/metric.py`) -- its `experiment_id` is
required/non-optional and no experiment registry exists anywhere in this
repository yet (`experiments/runners/` doesn't exist); inventing one would be
exactly the "metric that looks legitimate but isn't" spec §21 forbids.
`MetricContext.PATHFORGE` already exists as a reserved enum value for this
eventual wrapping but stays unpopulated here, deferred to Phase 68.

Never imports `simulator.ground_truth` -- not needed, since `ActualFailureOutcome`
is caller-supplied, not self-fetched (`scripts/check_ground_truth_boundary.py`
would reject it if it did).

Four metrics, one function:

- **Affected-node-prediction accuracy**: precision/recall/f1 (the same
  `_precision_recall_f1` empty-vs-empty=perfect, empty-vs-nonempty=0.0
  convention `topology_comparison.py` established) between the *union* of
  `predicted.service_impacts` node ids and `predicted.newly_unreachable_
  node_ids`, and `actual.actually_affected_node_ids`. Union, not either
  alone: `newly_unreachable_node_ids` can include nodes with no itemized
  `ServiceImpact` entry (Phase 61's routing impact is connectivity-based,
  separate from service itemization), so union is the more faithful
  "everything the twin predicted as affected."

- **Path-prediction accuracy**: a fraction-correct match rate, not
  precision/recall -- reachability is a binary per-pair fact, not a
  set-membership problem. For each `predicted.route_changes` pair, predicted
  reachability (`current_path is not None`) is compared against
  `actual.actual_reachable_pairs[(source, target)]`; a predicted pair absent
  from `actual`'s dict is excluded from both the numerator and
  `path_prediction_pair_count`, never silently scored either way.

- **Connectivity-prediction accuracy**: `1 - connectivity_prediction_error`,
  where the error averages the absolute differences between
  `predicted_resilience.connectivity_ratio`/`reachable_node_ratio` and their
  actual-side equivalents derived from `actual.actual_largest_component_
  node_ids` (the same self-relative formula Phase 62 uses for the predicted
  side). `actual_reachable_node_ratio` is a documented conservative
  approximation (`actual_largest_component_node_ids` over total original node
  count) since the minimal `ActualFailureOutcome` shape carries only the
  largest actual component, not the full partition -- it undercounts any
  healthy non-largest islands, a deliberate simplification, not an oversight.

- **Resilience-indicator accuracy**: explicitly scoped to avoid
  double-counting `connectivity_ratio`/`reachable_node_ratio` (already fully
  covered above). Only evaluates what's honestly derivable from
  `ActualFailureOutcome`: `affected_service_count` (normalized relative
  error) and `alternative_path_available` (binary match), each only if the
  caller supplied the corresponding optional `actual` field.
  `path_degradation_score` and `bottleneck_node_ids` are explicitly NOT
  evaluable from this minimal shape (no honest source of "actual path cost
  delta" or "actual articulation-point diff") -- never scored, always listed
  in `resilience_indicator_components_skipped`. The result is the mean of
  whichever components were supplied, or `None` if none were -- never a
  fabricated score.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple

from backend.app.models.failure import ResilienceIndicators
from backend.simulation.failure_propagation_pipeline import FailurePipelineResult


@dataclass(frozen=True)
class ActualFailureOutcome:
    actually_affected_node_ids: Set[str]
    actual_largest_component_node_ids: List[str]
    actual_reachable_pairs: Dict[Tuple[str, str], bool]
    actual_affected_service_count: Optional[int] = None
    actual_alternative_path_available: Optional[bool] = None


@dataclass(frozen=True)
class FailurePropagationValidationResult:
    scenario_id: str
    computed_at: datetime

    affected_node_precision: float
    affected_node_recall: float
    affected_node_f1: float

    path_prediction_match_rate: float
    path_prediction_pair_count: int

    connectivity_prediction_error: float
    connectivity_prediction_accuracy: float

    resilience_indicator_accuracy: Optional[float]
    resilience_indicator_components_evaluated: List[str]
    resilience_indicator_components_skipped: List[str]


def _precision_recall_f1(matched: int, predicted: int, actual: int) -> Tuple[float, float, float]:
    """Empty-vs-empty (nothing to disagree on) is perfect agreement (1.0/1.0/1.0);
    empty-vs-nonempty is 0.0 on whichever side has nothing -- both conventions
    stated explicitly, matching `experiments/metrics/topology_comparison.py`."""
    if predicted == 0 and actual == 0:
        return 1.0, 1.0, 1.0
    precision = (matched / predicted) if predicted else 0.0
    recall = (matched / actual) if actual else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return precision, recall, f1


def _affected_node_scores(predicted: FailurePipelineResult, actual: ActualFailureOutcome) -> Tuple[float, float, float]:
    predicted_node_ids = {si.node_id for si in predicted.service_impacts} | set(predicted.newly_unreachable_node_ids)
    matched = len(predicted_node_ids & actual.actually_affected_node_ids)
    return _precision_recall_f1(matched, len(predicted_node_ids), len(actual.actually_affected_node_ids))


def _path_prediction_match_rate(
    predicted: FailurePipelineResult, actual: ActualFailureOutcome
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
    predicted: FailurePipelineResult, predicted_resilience: ResilienceIndicators, actual: ActualFailureOutcome
) -> Tuple[float, float]:
    before_size = len(predicted.connectivity_before.largest_component_node_ids)
    actual_connectivity_ratio = (
        1.0 if before_size == 0 else len(actual.actual_largest_component_node_ids) / before_size
    )

    original_node_ids: Set[str] = {
        node_id for component in predicted.connectivity_before.components for node_id in component
    }
    actual_reachable_node_ratio = (
        1.0
        if not original_node_ids
        else len(actual.actual_largest_component_node_ids) / len(original_node_ids)
    )

    error = (
        abs(predicted_resilience.connectivity_ratio - actual_connectivity_ratio)
        + abs(predicted_resilience.reachable_node_ratio - actual_reachable_node_ratio)
    ) / 2
    return error, 1.0 - error


def _resilience_indicator_accuracy(
    predicted_resilience: ResilienceIndicators, actual: ActualFailureOutcome
) -> Tuple[Optional[float], List[str], List[str]]:
    evaluated: List[str] = []
    skipped: List[str] = ["path_degradation_score", "bottleneck_node_ids"]
    component_scores: List[float] = []

    if actual.actual_affected_service_count is not None:
        predicted_count = predicted_resilience.affected_service_count
        actual_count = actual.actual_affected_service_count
        denominator = max(predicted_count, actual_count, 1)
        component_scores.append(1.0 - abs(predicted_count - actual_count) / denominator)
        evaluated.append("affected_service_count")
    else:
        skipped.append("affected_service_count")

    if actual.actual_alternative_path_available is not None:
        component_scores.append(
            1.0 if predicted_resilience.alternative_path_available == actual.actual_alternative_path_available else 0.0
        )
        evaluated.append("alternative_path_available")
    else:
        skipped.append("alternative_path_available")

    if not component_scores:
        return None, evaluated, skipped
    return sum(component_scores) / len(component_scores), evaluated, skipped


def evaluate_failure_propagation_prediction(
    predicted: FailurePipelineResult,
    predicted_resilience: ResilienceIndicators,
    actual: ActualFailureOutcome,
) -> FailurePropagationValidationResult:
    """Scores a Phase 61 `FailurePipelineResult`/Phase 62 `ResilienceIndicators`
    prediction against a caller-supplied `ActualFailureOutcome` on RQ6's four
    named axes. Does no I/O; never mutates any argument."""
    precision, recall, f1 = _affected_node_scores(predicted, actual)
    match_rate, pair_count = _path_prediction_match_rate(predicted, actual)
    connectivity_error, connectivity_accuracy = _connectivity_prediction_accuracy(
        predicted, predicted_resilience, actual
    )
    resilience_accuracy, evaluated, skipped = _resilience_indicator_accuracy(predicted_resilience, actual)

    return FailurePropagationValidationResult(
        scenario_id=predicted.scenario.scenario_id,
        computed_at=datetime.now(timezone.utc),
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
