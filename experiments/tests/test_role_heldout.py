"""Phase 71 held-out role-inference evaluation unit tests (pure, no Docker)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Tuple

import pytest

from backend.app.models.behavior import BehavioralFingerprint, ObservationWindow, ServiceRole
from experiments.metrics import role_heldout
from experiments.metrics.role_heldout import evaluate_role_held_out

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _fp(node_id: str, destinations: int, ports, outbound: float = 0.5) -> BehavioralFingerprint:
    return BehavioralFingerprint(
        node_id=node_id,
        window=ObservationWindow.MEDIUM,
        computed_at=NOW,
        distinct_destinations=destinations,
        distinct_ports=list(ports),
        mean_flow_duration_seconds=1.0,
        outbound_byte_ratio=outbound,
        is_persistent_talker=False,
        distinct_protocols=["TCP"],
    )


def _separable() -> List[Tuple[BehavioralFingerprint, ServiceRole]]:
    data = []
    for i in range(4):
        data.append((_fp(f"dns{i}", 2 + i % 2, [53], 0.9), ServiceRole.DNS))
        data.append((_fp(f"db{i}", 40 + i, [5432, 6379], 0.1), ServiceRole.DATABASE))
    return data


def test_returns_both_in_sample_and_held_out_and_fold_per_node() -> None:
    result = evaluate_role_held_out(_separable())
    assert result.fold_count == 8
    assert result.in_sample.sample_count == 8
    assert result.held_out.sample_count == 8
    assert result.unseen_role_fold_count == 0
    assert result.held_out.accuracy == 1.0  # cleanly separable classes generalize


def test_held_out_predictions_come_from_models_that_never_saw_the_node(monkeypatch: pytest.MonkeyPatch) -> None:
    data = _separable()
    real_fit = role_heldout.fit_role_model
    seen_training_sizes: List[int] = []

    def spying_fit(labeled, *a, **kw):
        seen_training_sizes.append(len(labeled))
        return real_fit(labeled, *a, **kw)

    monkeypatch.setattr(role_heldout, "fit_role_model", spying_fit)
    real_classify = role_heldout.classify_node_role

    fold_models = []

    def spying_classify(model, fp, *a, **kw):
        fold_models.append((model, fp.node_id))
        return real_classify(model, fp, *a, **kw)

    monkeypatch.setattr(role_heldout, "classify_node_role", spying_classify)
    evaluate_role_held_out(data)

    # 1 full fit + 8 folds each trained on n-1 examples
    assert seen_training_sizes == [8] + [7] * 8
    assert len(fold_models) == 16  # 8 in-sample + 8 held-out


def test_held_out_accuracy_is_lower_than_in_sample_when_overlapping() -> None:
    # Two overlapping classes with a single distinctive outlier each: in-sample fits it, held-out cannot.
    data = [
        (_fp("a0", 5, [80], 0.5), ServiceRole.DNS),
        (_fp("a1", 6, [80], 0.5), ServiceRole.DNS),
        (_fp("a2", 30, [80], 0.5), ServiceRole.DNS),  # outlier
        (_fp("b0", 5, [80], 0.5), ServiceRole.DATABASE),
        (_fp("b1", 6, [80], 0.5), ServiceRole.DATABASE),
        (_fp("b2", 30, [80], 0.5), ServiceRole.DATABASE),
    ]
    result = evaluate_role_held_out(data)
    assert result.held_out.accuracy <= result.in_sample.accuracy


def test_lone_role_is_unlearnable_when_held_out_and_counted() -> None:
    data = _separable() + [(_fp("lb0", 10, [80]), ServiceRole.LOAD_BALANCER)]
    result = evaluate_role_held_out(data)
    assert result.unseen_role_fold_count == 1
    assert result.held_out.accuracy < 1.0  # that fold cannot be right
    assert result.held_out_accuracy_seen_roles == 1.0


def test_fewer_than_two_examples_raises() -> None:
    with pytest.raises(ValueError):
        evaluate_role_held_out([(_fp("n0", 1, [53]), ServiceRole.DNS)])
