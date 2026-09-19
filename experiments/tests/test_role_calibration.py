"""Phase 37 role-calibration evaluation unit tests (pure, no Docker)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.app.models.behavior import RoleClassification, ServiceRole
from experiments.metrics.role_calibration import evaluate_role_calibration

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _classification(node_id: str, probabilities) -> RoleClassification:
    return RoleClassification(node_id=node_id, computed_at=NOW, role_probabilities=probabilities)


def test_perfect_confident_predictions_have_high_accuracy_and_low_error() -> None:
    classifications = [
        _classification("n0", {ServiceRole.DNS: 0.999, ServiceRole.DATABASE: 0.001}),
        _classification("n1", {ServiceRole.DATABASE: 0.999, ServiceRole.DNS: 0.001}),
        _classification("n2", {ServiceRole.DNS: 0.999, ServiceRole.DATABASE: 0.001}),
    ]
    true_roles = [ServiceRole.DNS, ServiceRole.DATABASE, ServiceRole.DNS]

    result = evaluate_role_calibration(classifications, true_roles)

    assert result.accuracy == 1.0
    assert result.brier_score < 0.01
    assert result.expected_calibration_error < 0.01
    assert result.sample_count == 3


def test_confident_but_wrong_predictions_have_worse_metrics_than_perfect_case() -> None:
    perfect = [
        _classification("n0", {ServiceRole.DNS: 0.99, ServiceRole.DATABASE: 0.01}),
        _classification("n1", {ServiceRole.DNS: 0.99, ServiceRole.DATABASE: 0.01}),
    ]
    perfect_result = evaluate_role_calibration(perfect, [ServiceRole.DNS, ServiceRole.DNS])

    confidently_wrong = [
        _classification("n0", {ServiceRole.DNS: 0.99, ServiceRole.DATABASE: 0.01}),
        _classification("n1", {ServiceRole.DNS: 0.99, ServiceRole.DATABASE: 0.01}),
    ]
    wrong_result = evaluate_role_calibration(confidently_wrong, [ServiceRole.DATABASE, ServiceRole.DATABASE])

    assert wrong_result.accuracy < perfect_result.accuracy
    assert wrong_result.brier_score > perfect_result.brier_score
    assert wrong_result.expected_calibration_error > perfect_result.expected_calibration_error


def test_empty_input_raises_value_error() -> None:
    with pytest.raises(ValueError):
        evaluate_role_calibration([], [])


def test_mismatched_lengths_raise_value_error() -> None:
    classifications = [_classification("n0", {ServiceRole.DNS: 1.0})]
    with pytest.raises(ValueError):
        evaluate_role_calibration(classifications, [ServiceRole.DNS, ServiceRole.DATABASE])


def test_hand_computed_accuracy_and_brier_score() -> None:
    classifications = [
        _classification("n0", {ServiceRole.DNS: 0.9, ServiceRole.DATABASE: 0.1}),
        _classification("n1", {ServiceRole.DNS: 0.6, ServiceRole.DATABASE: 0.4}),
        _classification("n2", {ServiceRole.DNS: 0.2, ServiceRole.DATABASE: 0.8}),
        _classification("n3", {ServiceRole.DNS: 0.55, ServiceRole.DATABASE: 0.45}),
    ]
    true_roles = [ServiceRole.DNS, ServiceRole.DATABASE, ServiceRole.DATABASE, ServiceRole.DNS]

    result = evaluate_role_calibration(classifications, true_roles)

    # n0: correct (DNS 0.9 > 0.1). n1: incorrect (best_role=DNS, true=DATABASE).
    # n2: correct (DATABASE 0.8 > 0.2). n3: correct (DNS 0.55 > 0.45).
    assert result.accuracy == pytest.approx(0.75)

    expected_brier = (
        ((0.9 - 1) ** 2 + (0.1 - 0) ** 2)
        + ((0.6 - 0) ** 2 + (0.4 - 1) ** 2)
        + ((0.2 - 0) ** 2 + (0.8 - 1) ** 2)
        + ((0.55 - 1) ** 2 + (0.45 - 0) ** 2)
    ) / 4
    assert result.brier_score == pytest.approx(expected_brier)
