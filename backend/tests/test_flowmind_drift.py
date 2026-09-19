"""Phase 39 concept drift detection unit tests (pure, no Docker)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.app.models.anomaly import AnomalyClass
from backend.app.models.behavior import BehavioralFingerprint, ObservationWindow
from backend.flowmind.baseline.node_baseline import RobustFeatureBaseline, build_node_baseline
from backend.flowmind.drift.node_drift import track_feature_drift, track_node_drift

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _fp(
    node_id: str = "n0",
    window: ObservationWindow = ObservationWindow.MEDIUM,
    ports=(80,),
    protocols=("TCP",),
    destinations: int = 1,
    duration: float = 1.0,
    ratio: float = 0.5,
    persistent: bool = False,
) -> BehavioralFingerprint:
    return BehavioralFingerprint(
        node_id=node_id,
        window=window,
        computed_at=BASE,
        distinct_ports=list(ports),
        distinct_protocols=list(protocols),
        distinct_destinations=destinations,
        mean_flow_duration_seconds=duration,
        outbound_byte_ratio=ratio,
        is_persistent_talker=persistent,
    )


def test_track_feature_drift_raises_on_empty_observed_values() -> None:
    baseline = RobustFeatureBaseline(median=10.0, mad=1.0)
    with pytest.raises(ValueError):
        track_feature_drift(baseline, "x", [])


def test_reverting_deviation_classifies_as_transient_anomaly() -> None:
    baseline = RobustFeatureBaseline(median=10.0, mad=1.0)
    observed = [20.0] + [10.0] * 7  # one blip, then back to normal

    result = track_feature_drift(baseline, "x", observed, alpha=0.05)

    assert result.anomaly_class == AnomalyClass.TRANSIENT_ANOMALY


def test_sustained_deviation_classifies_as_concept_drift() -> None:
    baseline = RobustFeatureBaseline(median=10.0, mad=1.0)
    observed = [20.0] * 20  # sustained shift, many observations

    result = track_feature_drift(baseline, "x", observed, alpha=0.05)

    assert result.anomaly_class == AnomalyClass.CONCEPT_DRIFT


def test_ewma_trace_hand_computed() -> None:
    baseline = RobustFeatureBaseline(median=10.0, mad=1.0)

    result = track_feature_drift(baseline, "x", [20.0, 20.0, 20.0], alpha=0.5)

    # ewma0 = 0.5*20 + 0.5*10 = 15
    # ewma1 = 0.5*20 + 0.5*15 = 17.5
    # ewma2 = 0.5*20 + 0.5*17.5 = 18.75
    assert result.ewma_trace == pytest.approx([15.0, 17.5, 18.75])
    assert result.final_ewma == pytest.approx(18.75)
    assert result.baseline_median == 10.0


def test_track_node_drift_raises_on_empty_fingerprints() -> None:
    history = [_fp(destinations=d) for d in (1, 2, 3, 4, 5)]
    baseline = build_node_baseline(history)
    with pytest.raises(ValueError):
        track_node_drift(baseline, [])


def test_track_node_drift_raises_on_node_id_mismatch() -> None:
    history = [_fp(node_id="n0") for _ in range(5)]
    baseline = build_node_baseline(history)
    mismatched = [_fp(node_id="n1")]
    with pytest.raises(ValueError):
        track_node_drift(baseline, mismatched)


def test_track_node_drift_raises_on_window_mismatch() -> None:
    history = [_fp(window=ObservationWindow.MEDIUM) for _ in range(5)]
    baseline = build_node_baseline(history)
    mismatched = [_fp(window=ObservationWindow.LONG)]
    with pytest.raises(ValueError):
        track_node_drift(baseline, mismatched)


def test_track_node_drift_covers_all_five_continuous_features() -> None:
    history = [_fp(destinations=d) for d in (1, 2, 3, 4, 5)]
    baseline = build_node_baseline(history)
    new_fingerprints = [_fp(destinations=3) for _ in range(3)]

    results = track_node_drift(baseline, new_fingerprints)

    assert set(results.keys()) == {
        "distinct_destinations",
        "mean_flow_duration_seconds",
        "outbound_byte_ratio",
        "port_count",
        "total_byte_count",
    }


def test_one_feature_drifts_while_another_stays_stable() -> None:
    # Baseline built from stable history: destinations ~1-5, duration always 1.0.
    history = [_fp(destinations=d, duration=1.0) for d in (1, 2, 3, 4, 5)]
    baseline = build_node_baseline(history)

    # New fingerprints: destinations sustained far outside history (drift),
    # duration unchanged (stable).
    new_fingerprints = [_fp(destinations=100, duration=1.0) for _ in range(20)]

    results = track_node_drift(baseline, new_fingerprints, alpha=0.05)

    assert results["distinct_destinations"].anomaly_class == AnomalyClass.CONCEPT_DRIFT
    assert results["mean_flow_duration_seconds"].anomaly_class == AnomalyClass.TRANSIENT_ANOMALY
