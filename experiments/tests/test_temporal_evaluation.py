"""Phase 68 temporal-analysis evaluation unit tests (pure, no Docker)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.app.models.snapshot import ChangeType, GraphChangeEvent
from experiments.metrics.temporal_evaluation import LabeledTopologyEvent, evaluate_temporal_analysis

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _event(change_type: ChangeType, node_id=None, edge_id=None, occurred_at=BASE) -> GraphChangeEvent:
    return GraphChangeEvent(
        event_id=f"evt-{node_id or edge_id}-{change_type.value}",
        from_snapshot_id="s0",
        to_snapshot_id="s1",
        occurred_at=occurred_at,
        change_type=change_type,
        affected_node_id=node_id,
        affected_edge_id=edge_id,
        evidence=["synthetic"],
    )


def test_exact_match_is_true_positive_with_latency() -> None:
    labeled = [LabeledTopologyEvent(change_type=ChangeType.NODE_ADDED, node_id="n1", onset_at=BASE)]
    detected = [_event(ChangeType.NODE_ADDED, node_id="n1", occurred_at=BASE + timedelta(seconds=5))]

    result = evaluate_temporal_analysis(detected, labeled)

    assert result.true_positive_count == 1
    assert result.false_negative_count == 0
    assert result.precision == 1.0
    assert result.recall == 1.0
    assert result.mean_detection_latency_seconds == 5.0


def test_detection_before_onset_does_not_count() -> None:
    labeled = [LabeledTopologyEvent(change_type=ChangeType.NODE_ADDED, node_id="n1", onset_at=BASE)]
    detected = [_event(ChangeType.NODE_ADDED, node_id="n1", occurred_at=BASE - timedelta(seconds=5))]

    result = evaluate_temporal_analysis(detected, labeled)

    assert result.true_positive_count == 0
    assert result.false_negative_count == 1
    assert result.false_positive_count == 1


def test_unmatched_detection_is_false_positive() -> None:
    labeled = [LabeledTopologyEvent(change_type=ChangeType.NODE_ADDED, node_id="n1", onset_at=BASE)]
    detected = [
        _event(ChangeType.NODE_ADDED, node_id="n1", occurred_at=BASE),
        _event(ChangeType.NODE_ADDED, node_id="n2", occurred_at=BASE),
    ]

    result = evaluate_temporal_analysis(detected, labeled)

    assert result.true_positive_count == 1
    assert result.false_positive_count == 1
    assert result.precision == 0.5


def test_wrong_change_type_does_not_match() -> None:
    labeled = [LabeledTopologyEvent(change_type=ChangeType.EDGE_ADDED, edge_id="e1", onset_at=BASE)]
    detected = [_event(ChangeType.EDGE_REMOVED, edge_id="e1", occurred_at=BASE)]

    result = evaluate_temporal_analysis(detected, labeled)

    assert result.true_positive_count == 0
    assert result.false_negative_count == 1


def test_empty_labeled_events_raises() -> None:
    with pytest.raises(ValueError):
        evaluate_temporal_analysis([], [])
