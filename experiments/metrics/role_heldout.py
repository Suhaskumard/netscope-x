"""Held-out (leave-one-node-out) role-inference evaluation (spec Phase 71).

Phase 68's `role_inference` metric fit `fit_role_model` on a set of labeled
fingerprints and then scored `classify_node_role` on those *same*
fingerprints (in-sample), which trivially reports `accuracy=1.0`. This
module supplies the genuine out-of-sample counterpart: for each labeled
node `i`, fit a fresh model on every OTHER labeled node, then classify node
`i`. Every held-out prediction therefore comes from a model that never saw
that node's fingerprint or label during fitting.

Both numbers are returned side by side (`RoleHeldOutEvaluation`), never
just one: `in_sample` reproduces Phase 68's original methodology exactly,
`held_out` is the leave-one-node-out measurement.

Roles that appear exactly once in the labeled set cannot be learned when
that lone node is held out -- the fold's model has no such class, so the
prediction is necessarily wrong. These are counted, not hidden:
`unseen_role_fold_count` reports how many folds this affected, and
`held_out_accuracy_seen_roles` reports accuracy over only the folds whose
true role was present in training, so a reader can separate "the
classifier generalizes poorly" from "the role was unlearnable in that fold".

Evaluation-only, like `role_calibration.py`: takes real labels as plain
parameters, never imports `simulator.ground_truth`, and never feeds back
into the classifier.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from backend.app.models.behavior import BehavioralFingerprint, ServiceRole
from backend.flowmind.classification.role_classifier import classify_node_role, fit_role_model
from experiments.metrics.role_calibration import RoleCalibrationEvaluation, evaluate_role_calibration


@dataclass(frozen=True)
class RoleHeldOutEvaluation:
    in_sample: RoleCalibrationEvaluation
    held_out: RoleCalibrationEvaluation
    held_out_accuracy_seen_roles: Optional[float]
    unseen_role_fold_count: int
    fold_count: int


def evaluate_role_held_out(labeled: List[Tuple[BehavioralFingerprint, ServiceRole]]) -> RoleHeldOutEvaluation:
    """Leave-one-node-out cross-validation of `fit_role_model`/
    `classify_node_role` over `labeled` (fingerprint, true role) pairs,
    reported alongside the in-sample score. Raises `ValueError` for fewer
    than 2 labeled examples: a held-out fold needs at least one training
    example left after removing the held-out node.
    """
    if len(labeled) < 2:
        raise ValueError("evaluate_role_held_out requires at least 2 labeled examples")

    true_roles = [role for _, role in labeled]

    full_model = fit_role_model(labeled)
    in_sample = evaluate_role_calibration([classify_node_role(full_model, fp) for fp, _ in labeled], true_roles)

    held_out_classifications = []
    seen_correct = 0
    seen_total = 0
    unseen = 0
    for i, (fp, true_role) in enumerate(labeled):
        training = labeled[:i] + labeled[i + 1 :]
        fold_model = fit_role_model(training)  # never contains labeled[i]
        prediction = classify_node_role(fold_model, fp)
        held_out_classifications.append(prediction)
        if true_role in fold_model.roles:
            seen_total += 1
            seen_correct += int(prediction.best_role == true_role)
        else:
            unseen += 1

    return RoleHeldOutEvaluation(
        in_sample=in_sample,
        held_out=evaluate_role_calibration(held_out_classifications, true_roles),
        held_out_accuracy_seen_roles=(seen_correct / seen_total) if seen_total else None,
        unseen_role_fold_count=unseen,
        fold_count=len(labeled),
    )
