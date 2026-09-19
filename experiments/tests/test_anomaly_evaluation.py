"""Phase 42 FLOWMIND evaluation unit tests (pure, no Docker)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.app.models.anomaly import Anomaly, AnomalyClass, AnomalyDimension
from experiments.metrics.anomaly_evaluation import LabeledAnomalyEvent, evaluate_anomaly_detection

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _anomaly(
    node_id: str,
    dimension: AnomalyDimension,
    detected_at: datetime,
    score: float = 0.8,
) -> Anomaly:
    return Anomaly(
        node_id=node_id,
        anomaly_id=f"{node_id}:{dimension.value}:{detected_at.isoformat()}",
        detected_at=detected_at,
        dimension=dimension,
        anomaly_class=AnomalyClass.TRANSIENT_ANOMALY,
        evidence=["synthetic evidence for test purposes"],
        evidence_values={},
        score=score,
    )


def _event(node_id: str, dimension: AnomalyDimension, onset_at: datetime) -> LabeledAnomalyEvent:
    return LabeledAnomalyEvent(node_id=node_id, dimension=dimension, onset_at=onset_at)


def test_perfect_detection_scores_all_metrics_as_one() -> None:
    events = [
        _event("n0", AnomalyDimension.DESTINATIONS, BASE),
        _event("n1", AnomalyDimension.PORTS, BASE),
    ]
    detected = [
        _anomaly("n0", AnomalyDimension.DESTINATIONS, BASE + timedelta(seconds=5)),
        _anomaly("n1", AnomalyDimension.PORTS, BASE + timedelta(seconds=10)),
    ]

    result = evaluate_anomaly_detection(detected, events)

    assert result.true_positive_count == 2
    assert result.false_positive_count == 0
    assert result.false_negative_count == 0
    assert result.precision == 1.0
    assert result.recall == 1.0
    assert result.f1 == 1.0
    assert result.false_negative_rate == 0.0


def test_missed_label_reduces_recall_not_precision() -> None:
    events = [
        _event("n0", AnomalyDimension.DESTINATIONS, BASE),
        _event("n1", AnomalyDimension.PORTS, BASE),
    ]
    # Only n0's anomaly is ever detected; n1's is missed entirely.
    detected = [_anomaly("n0", AnomalyDimension.DESTINATIONS, BASE + timedelta(seconds=5))]

    result = evaluate_anomaly_detection(detected, events)

    assert result.true_positive_count == 1
    assert result.false_negative_count == 1
    assert result.false_positive_count == 0
    assert result.precision == 1.0
    assert result.recall == pytest.approx(0.5)


def test_extra_detection_reduces_precision_not_recall() -> None:
    events = [_event("n0", AnomalyDimension.DESTINATIONS, BASE)]
    detected = [
        _anomaly("n0", AnomalyDimension.DESTINATIONS, BASE + timedelta(seconds=5)),
        # Spurious: no corresponding label for n1/PORTS.
        _anomaly("n1", AnomalyDimension.PORTS, BASE + timedelta(seconds=5)),
    ]

    result = evaluate_anomaly_detection(detected, events)

    assert result.true_positive_count == 1
    assert result.false_positive_count == 1
    assert result.false_negative_count == 0
    assert result.recall == 1.0
    assert result.precision == pytest.approx(0.5)


def test_detection_before_onset_does_not_count_as_match() -> None:
    events = [_event("n0", AnomalyDimension.DESTINATIONS, BASE)]
    # Fired 5 seconds BEFORE the labeled onset -- cannot be credited.
    detected = [_anomaly("n0", AnomalyDimension.DESTINATIONS, BASE - timedelta(seconds=5))]

    result = evaluate_anomaly_detection(detected, events)

    assert result.true_positive_count == 0
    assert result.false_negative_count == 1
    assert result.false_positive_count == 1
    assert result.recall == 0.0
    assert result.precision == 0.0


def test_empty_labeled_events_raises_value_error() -> None:
    with pytest.raises(ValueError):
        evaluate_anomaly_detection([], [])


def test_hand_computed_detection_latency() -> None:
    events = [
        _event("n0", AnomalyDimension.DESTINATIONS, BASE),
        _event("n1", AnomalyDimension.TIMING, BASE + timedelta(seconds=100)),
    ]
    detected = [
        _anomaly("n0", AnomalyDimension.DESTINATIONS, BASE + timedelta(seconds=10)),
        _anomaly("n1", AnomalyDimension.TIMING, BASE + timedelta(seconds=100, milliseconds=500)),
    ]

    result = evaluate_anomaly_detection(detected, events)

    assert result.mean_detection_latency_seconds == pytest.approx((10.0 + 0.5) / 2)


def test_mean_latency_is_none_with_zero_true_positives() -> None:
    events = [_event("n0", AnomalyDimension.DESTINATIONS, BASE)]
    result = evaluate_anomaly_detection([], events)

    assert result.true_positive_count == 0
    assert result.mean_detection_latency_seconds is None


def test_false_positive_rate_requires_total_checks() -> None:
    events = [_event("n0", AnomalyDimension.DESTINATIONS, BASE)]
    detected = [_anomaly("n0", AnomalyDimension.DESTINATIONS, BASE + timedelta(seconds=5))]

    without_total = evaluate_anomaly_detection(detected, events)
    assert without_total.false_positive_rate is None

    with_total = evaluate_anomaly_detection(detected, events, total_checks=10)
    # TP=1, FP=0, FN=0 -> TN = 10 - 1 = 9 -> FPR = 0 / (0 + 9) = 0.0
    assert with_total.false_positive_rate == pytest.approx(0.0)


def test_inconsistent_total_checks_raises_value_error() -> None:
    events = [
        _event("n0", AnomalyDimension.DESTINATIONS, BASE),
        _event("n1", AnomalyDimension.PORTS, BASE),
    ]
    detected = [
        _anomaly("n0", AnomalyDimension.DESTINATIONS, BASE + timedelta(seconds=5)),
        _anomaly("n1", AnomalyDimension.PORTS, BASE + timedelta(seconds=5)),
    ]

    with pytest.raises(ValueError):
        # TP=2, FP=0, FN=0 -> accounted_for=2, but total_checks=1 is too small.
        evaluate_anomaly_detection(detected, events, total_checks=1)


def test_real_end_to_end_via_detect_node_anomalies() -> None:
    from backend.app.models.behavior import BehavioralFingerprint, ObservationWindow
    from backend.flowmind.anomaly.node_anomaly import detect_node_anomalies
    from backend.flowmind.baseline.node_baseline import build_node_baseline

    def _fp(destinations: int) -> BehavioralFingerprint:
        return BehavioralFingerprint(
            node_id="n-real",
            window=ObservationWindow.MEDIUM,
            computed_at=BASE,
            distinct_ports=[80],
            distinct_protocols=["TCP"],
            distinct_destinations=destinations,
            mean_flow_duration_seconds=1.0,
            outbound_byte_ratio=0.5,
            is_persistent_talker=False,
            total_byte_count=1000,
        )

    history = [_fp(3 + (i % 3)) for i in range(10)]  # jitters 3-5, median 4
    baseline = build_node_baseline(history)

    deviating = _fp(100)
    real_anomalies = detect_node_anomalies(baseline, deviating)
    destination_anomalies = [a for a in real_anomalies if a.dimension == AnomalyDimension.DESTINATIONS]
    assert len(destination_anomalies) == 1

    # A genuine test harness would know the injected anomaly's true onset,
    # slightly before the fingerprint's own computed_at/detected_at.
    labeled_event = _event(
        "n-real", AnomalyDimension.DESTINATIONS, BASE - timedelta(seconds=2)
    )

    result = evaluate_anomaly_detection(real_anomalies, [labeled_event])

    assert result.true_positive_count == 1
    assert result.precision == 1.0
    assert result.recall == 1.0
    assert result.mean_detection_latency_seconds == pytest.approx(2.0)
