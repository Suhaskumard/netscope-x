"""Role-classification calibration evaluation, for evaluation purposes only
(spec Phase 37, FR-1.14: "confidence must be calibrated"; RQ2).

This module is the evaluation-only counterpart to
`backend/flowmind/classification/role_classifier.py`'s real, fitted
temperature scaling: it MEASURES how well-calibrated a set of real
`RoleClassification` outputs are against real true-role labels, using the
standard multiclass Brier score and expected calibration error (ECE)
formulas -- it never fits, adjusts, or otherwise feeds back into the
classifier itself.

Mirrors Phase 32's `experiments/metrics/topology_comparison.py` precedent
exactly: returns a plain `RoleCalibrationEvaluation` dataclass, not a
`MetricResult` (`backend/app/models/metric.py`) -- `MetricResult.
experiment_id` is required, and no experiment registry exists anywhere in
this repository yet (`experiments/runners/` doesn't exist), so wrapping
this in a `MetricResult` would mean fabricating an experiment identity
with nothing real behind it, exactly what spec §21 ("No Fake Metrics")
forbids. `MetricResult.calibration_error`'s own docstring already scopes
that field to "the Phase 68 evaluation matrix," not this phase.

Never imported by anything under `backend/nettrace/`/`backend/app/` --
evaluation-only, matching FR-1.11/RQ2's "for evaluation purposes
only"/"Validation Engine" framing already established for the analogous
topology-comparison case. Takes real labels as a plain parameter; never
imports `simulator.ground_truth` itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from backend.app.models.behavior import RoleClassification, ServiceRole


@dataclass(frozen=True)
class RoleCalibrationEvaluation:
    sample_count: int
    accuracy: float
    brier_score: float
    expected_calibration_error: float


def _brier_score(classifications: List[RoleClassification], true_roles: List[ServiceRole]) -> float:
    """Real multiclass Brier score: mean squared error between each
    prediction's full probability vector and the true role's one-hot
    vector, summed over every candidate role that appeared in that
    prediction. 0.0 is perfect; higher is worse."""
    total = 0.0
    for classification, true_role in zip(classifications, true_roles):
        for role, probability in classification.role_probabilities.items():
            target = 1.0 if role == true_role else 0.0
            total += (probability - target) ** 2
    return total / len(classifications)


def _expected_calibration_error(
    classifications: List[RoleClassification], true_roles: List[ServiceRole], num_bins: int
) -> float:
    """Standard ECE: bin predictions by their `best_role` probability
    (confidence) into `num_bins` equal-width bins over [0, 1], then take
    the sample-count-weighted average, across bins, of the absolute gap
    between each bin's mean confidence and its actual accuracy (fraction
    of predictions in that bin whose `best_role` was correct). 0.0 is
    perfectly calibrated; higher means confidence and correctness diverge.
    """
    bins: List[List[float]] = [[] for _ in range(num_bins)]
    bin_correct: List[int] = [0] * num_bins

    for classification, true_role in zip(classifications, true_roles):
        confidence = classification.role_probabilities[classification.best_role]
        # confidence == 1.0 must land in the last bin, not one past it.
        bin_index = min(int(confidence * num_bins), num_bins - 1)
        bins[bin_index].append(confidence)
        if classification.best_role == true_role:
            bin_correct[bin_index] += 1

    total = len(classifications)
    ece = 0.0
    for bin_confidences, correct_count in zip(bins, bin_correct):
        if not bin_confidences:
            continue
        bin_size = len(bin_confidences)
        mean_confidence = sum(bin_confidences) / bin_size
        bin_accuracy = correct_count / bin_size
        ece += (bin_size / total) * abs(mean_confidence - bin_accuracy)
    return ece


def evaluate_role_calibration(
    classifications: List[RoleClassification],
    true_roles: List[ServiceRole],
    num_bins: int = 10,
) -> RoleCalibrationEvaluation:
    """Compares real `RoleClassification` outputs against real true-role
    labels (RQ2: "computed from Phase 36/37 output against ground-truth
    role labels ... never hand-assigned"). Raises `ValueError` on empty or
    mismatched-length input -- an evaluation genuinely cannot be computed
    from nothing, the same stance `fit_role_model`/`fit_temperature`
    already take for fitting.
    """
    if not classifications:
        raise ValueError("evaluate_role_calibration requires at least one classification")
    if len(classifications) != len(true_roles):
        raise ValueError(
            f"classifications ({len(classifications)}) and true_roles ({len(true_roles)}) "
            "must be the same length"
        )

    correct = sum(1 for c, t in zip(classifications, true_roles) if c.best_role == t)
    accuracy = correct / len(classifications)

    return RoleCalibrationEvaluation(
        sample_count=len(classifications),
        accuracy=accuracy,
        brier_score=_brier_score(classifications, true_roles),
        expected_calibration_error=_expected_calibration_error(classifications, true_roles, num_bins),
    )
