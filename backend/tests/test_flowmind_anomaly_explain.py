"""Phase 41 explainable-anomaly report rendering tests (pure, no Docker)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.app.models.anomaly import Anomaly, AnomalyClass, AnomalyDimension
from backend.app.models.behavior import ObservationWindow
from backend.flowmind.anomaly.explain import format_anomaly_report
from backend.flowmind.anomaly.node_anomaly import detect_node_anomalies
from backend.flowmind.baseline.node_baseline import build_node_baseline

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _anomaly(
    node_id: str = "API-2",
    dimension: AnomalyDimension = AnomalyDimension.DESTINATIONS,
    evidence=("destinations moved from 4 to 9",),
    evidence_values=None,
    score: float = 0.8,
) -> Anomaly:
    return Anomaly(
        node_id=node_id,
        anomaly_id=f"{node_id}:{dimension.value}:1",
        detected_at=BASE,
        dimension=dimension,
        anomaly_class=AnomalyClass.TRANSIENT_ANOMALY,
        evidence=list(evidence),
        evidence_values=evidence_values or {"historical_destinations": "4", "current_destinations": "9"},
        score=score,
    )


def test_empty_list_raises_value_error() -> None:
    with pytest.raises(ValueError):
        format_anomaly_report([])


def test_mixed_node_ids_raises_value_error() -> None:
    with pytest.raises(ValueError):
        format_anomaly_report([_anomaly(node_id="API-1"), _anomaly(node_id="API-2")])


def test_single_destinations_anomaly_renders_expected_lines() -> None:
    report = format_anomaly_report([_anomaly()])

    lines = report.splitlines()
    assert lines[0] == "Node: API-2"
    assert "Historical destinations: 4" in lines
    assert "Current destinations: 9" in lines
    assert "Evidence:" in lines
    assert "- destinations moved from 4 to 9" in lines


def test_single_ports_anomaly_names_specific_new_port() -> None:
    anomaly = _anomaly(
        dimension=AnomalyDimension.PORTS,
        evidence=["new port(s) observed, not present in the historical set: 4444"],
        evidence_values={
            "new_ports": "4444",
            "historical_port_count": "1",
            "current_port_count": "2",
        },
    )

    report = format_anomaly_report([anomaly])
    lines = report.splitlines()

    assert "New ports: 4444" in lines
    assert "Historical port count: 1" in lines
    assert "Current port count: 2" in lines
    assert any("4444" in line for line in lines if line.startswith("-"))


def test_combined_report_matches_master_spec_worked_example_shape() -> None:
    """Reproduces the master spec's own PHASE 41 worked example: a single
    node ("API-2") with both a destination-count deviation and a named new
    port, combined into one report."""
    destinations_anomaly = _anomaly()
    ports_anomaly = _anomaly(
        dimension=AnomalyDimension.PORTS,
        evidence=["new port(s) observed, not present in the historical set: 4444"],
        evidence_values={
            "new_ports": "4444",
            "historical_port_count": "1",
            "current_port_count": "2",
        },
    )

    report = format_anomaly_report([destinations_anomaly, ports_anomaly])
    lines = report.splitlines()

    assert lines[0] == "Node: API-2"
    assert "Historical destinations: 4" in lines
    assert "Current destinations: 9" in lines
    assert "New ports: 4444" in lines
    assert "Evidence:" in lines
    assert "- destinations moved from 4 to 9" in lines
    assert "- new port(s) observed, not present in the historical set: 4444" in lines


def test_report_is_deterministic_across_repeated_calls() -> None:
    anomalies = [_anomaly()]

    first = format_anomaly_report(anomalies)
    second = format_anomaly_report(anomalies)

    assert first == second


def test_real_end_to_end_via_detect_node_anomalies() -> None:
    """A real detector-produced anomaly (not a hand-built fixture) renders
    into a clean, integer-valued report -- the concrete Phase 41 fix over
    Phase 40's original `.3f`-everywhere formatting."""
    from backend.app.models.behavior import BehavioralFingerprint

    def _fp(destinations: int) -> BehavioralFingerprint:
        return BehavioralFingerprint(
            node_id="API-2",
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

    anomalies = detect_node_anomalies(baseline, _fp(9))
    destination_anomalies = [a for a in anomalies if a.dimension == AnomalyDimension.DESTINATIONS]
    assert len(destination_anomalies) == 1

    report = format_anomaly_report(destination_anomalies)

    assert "Node: API-2" in report
    assert "Historical destinations: 4" in report
    assert "Current destinations: 9" in report
    # The count fields render as clean integers (the concrete Phase 41 fix);
    # z_score is a genuine statistic and keeps its decimal precision.
    assert "Historical destinations: 4.000" not in report
    assert "Current destinations: 9.000" not in report
