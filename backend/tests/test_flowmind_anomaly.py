"""Phase 40 multi-dimensional anomaly detection unit tests (pure, no Docker)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.app.models.anomaly import AnomalyClass, AnomalyDimension
from backend.app.models.behavior import BehavioralFingerprint, ObservationWindow
from backend.app.models.flow import Flow, FlowFeatures
from backend.app.models.packet import TransportProtocol
from backend.app.models.topology import Node
from backend.flowmind.anomaly.node_anomaly import detect_node_anomalies, detect_node_anomalies_with_drift
from backend.flowmind.baseline.node_baseline import build_node_baseline
from backend.flowmind.fingerprints.node_fingerprint import assemble_node_fingerprint

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _fp(
    node_id: str = "n0",
    window: ObservationWindow = ObservationWindow.MEDIUM,
    computed_at=BASE,
    ports=(80,),
    protocols=("TCP",),
    destinations: int = 3,
    duration: float = 1.0,
    ratio: float = 0.5,
    persistent: bool = False,
    volume: int = 1000,
) -> BehavioralFingerprint:
    return BehavioralFingerprint(
        node_id=node_id,
        window=window,
        computed_at=computed_at,
        distinct_ports=list(ports),
        distinct_protocols=list(protocols),
        distinct_destinations=destinations,
        mean_flow_duration_seconds=duration,
        outbound_byte_ratio=ratio,
        is_persistent_talker=persistent,
        total_byte_count=volume,
    )


def _stable_history(n: int = 10):
    # Slight jitter, not perfectly identical values -- a real (small but
    # non-zero) MAD, so a deviation's z-score is large-but-finite rather
    # than a degenerate divide-by-mad_floor infinity.
    return [
        _fp(
            destinations=3 + (i % 3),
            duration=1.0 + 0.1 * (i % 3),
            ratio=0.5 + 0.01 * (i % 3),
            volume=1000 + 10 * (i % 3),
        )
        for i in range(n)
    ]


def test_cold_start_returns_no_anomalies() -> None:
    history = _stable_history(3)  # below default min_observations=5
    baseline = build_node_baseline(history)

    result = detect_node_anomalies(baseline, _fp(destinations=100))

    assert result == []


def test_destinations_anomaly_has_expected_evidence_values() -> None:
    baseline = build_node_baseline(_stable_history())
    deviating = _fp(destinations=100)

    anomalies = detect_node_anomalies(baseline, deviating)

    destination_anomalies = [a for a in anomalies if a.dimension == AnomalyDimension.DESTINATIONS]
    assert len(destination_anomalies) == 1
    anomaly = destination_anomalies[0]
    # _stable_history's destinations jitter between 3-5, median 4.0.
    assert anomaly.evidence_values["historical_destinations"] == "4.000"
    assert anomaly.evidence_values["current_destinations"] == "100.000"


def test_timing_anomaly_fires_on_deviating_duration() -> None:
    baseline = build_node_baseline(_stable_history())
    deviating = _fp(duration=500.0)

    anomalies = detect_node_anomalies(baseline, deviating)

    assert any(a.dimension == AnomalyDimension.TIMING for a in anomalies)


def test_behavior_anomaly_fires_on_deviating_byte_ratio() -> None:
    baseline = build_node_baseline(_stable_history())
    deviating = _fp(ratio=0.999)

    anomalies = detect_node_anomalies(baseline, deviating)

    assert any(a.dimension == AnomalyDimension.BEHAVIOR for a in anomalies)


def test_traffic_volume_anomaly_fires_on_deviating_byte_count() -> None:
    baseline = build_node_baseline(_stable_history())
    deviating = _fp(volume=10_000_000)

    anomalies = detect_node_anomalies(baseline, deviating)

    assert any(a.dimension == AnomalyDimension.TRAFFIC_VOLUME for a in anomalies)


def test_ports_anomaly_fires_only_for_new_ports() -> None:
    baseline = build_node_baseline(_stable_history())  # historical_ports = {80}

    no_new_port = _fp(ports=(80,))
    assert not any(a.dimension == AnomalyDimension.PORTS for a in detect_node_anomalies(baseline, no_new_port))

    new_port = _fp(ports=(80, 4444))
    port_anomalies = [a for a in detect_node_anomalies(baseline, new_port) if a.dimension == AnomalyDimension.PORTS]
    assert len(port_anomalies) == 1
    assert "4444" in port_anomalies[0].evidence_values["new_ports"]


def test_protocols_anomaly_fires_only_for_new_protocols() -> None:
    baseline = build_node_baseline(_stable_history())  # historical_protocols = {TCP}

    new_protocol = _fp(protocols=("TCP", "UDP"))
    protocol_anomalies = [
        a for a in detect_node_anomalies(baseline, new_protocol) if a.dimension == AnomalyDimension.PROTOCOLS
    ]
    assert len(protocol_anomalies) == 1
    assert "UDP" in protocol_anomalies[0].evidence_values["new_protocols"]


def test_scores_are_bounded_and_never_reach_exactly_one() -> None:
    baseline = build_node_baseline(_stable_history())
    # Deviating, but not so extreme that 1 - exp(-huge) underflows to exactly
    # 1.0 at float64 precision (the same saturation property already tested
    # for Phase 30/31's confidence scores, at a magnitude that stays
    # representable).
    deviating = _fp(destinations=50, duration=5.0, ratio=0.0001, volume=500, ports=(4444,), protocols=("UDP",))

    anomalies = detect_node_anomalies(baseline, deviating)

    assert anomalies  # sanity: something fired
    for anomaly in anomalies:
        assert 0.0 <= anomaly.score <= 1.0
        assert anomaly.score < 1.0


def test_detect_node_anomalies_always_provisional_transient() -> None:
    baseline = build_node_baseline(_stable_history())
    deviating = _fp(destinations=100)

    anomalies = detect_node_anomalies(baseline, deviating)

    assert anomalies
    assert all(a.anomaly_class == AnomalyClass.TRANSIENT_ANOMALY for a in anomalies)


def test_detect_with_drift_upgrades_sustained_deviation_to_concept_drift() -> None:
    baseline = build_node_baseline(_stable_history())
    sustained = [_fp(destinations=100, computed_at=BASE + timedelta(seconds=i)) for i in range(20)]

    anomalies = detect_node_anomalies_with_drift(baseline, sustained)

    destination_anomalies = [a for a in anomalies if a.dimension == AnomalyDimension.DESTINATIONS]
    assert len(destination_anomalies) == 1
    assert destination_anomalies[0].anomaly_class == AnomalyClass.CONCEPT_DRIFT


def test_no_topology_anomaly_is_ever_produced() -> None:
    baseline = build_node_baseline(_stable_history())
    deviating = _fp(destinations=100000, duration=1_000_000.0, ratio=0.0001, volume=1, ports=(4444,), protocols=("UDP",))

    anomalies = detect_node_anomalies(baseline, deviating)

    assert not any(a.dimension == AnomalyDimension.TOPOLOGY for a in anomalies)


def _pkt(pid, t, src_ip, src_port, dst_ip, dst_port, protocol, size=100):
    from backend.app.models.packet import Packet, PacketDirection

    return Packet(
        packet_id=pid,
        capture_id="cap-1",
        timestamp=t,
        src_ip=src_ip,
        dst_ip=dst_ip,
        src_port=src_port,
        dst_port=dst_port,
        protocol=protocol,
        size_bytes=size,
        direction=PacketDirection.UNKNOWN,
    )


def test_real_end_to_end_via_assemble_node_fingerprint() -> None:
    node = Node(node_id="n-real", ip_addresses=["10.0.0.1"], first_observed=BASE, last_observed=BASE)

    def _flows(num_dest_ips, dst_port=80, protocol=TransportProtocol.TCP):
        return [
            Flow(
                flow_id=f"f-{i}",
                capture_id="cap-1",
                src_ip="10.0.0.1",
                dst_ip=f"10.0.1.{i}",
                src_port=51000,
                dst_port=dst_port,
                protocol=protocol,
                first_seen=BASE,
                last_seen=BASE + timedelta(seconds=1),
                features=FlowFeatures(
                    packet_count=2,
                    byte_count=100,
                    duration_seconds=1.0,
                    burstiness=0.0,
                    mean_inter_arrival_seconds=0.1,
                    forward_byte_ratio=0.5,
                    destination_diversity=1,
                    port_diversity=1,
                    is_persistent=False,
                ),
            )
            for i in range(num_dest_ips)
        ]

    history = [
        assemble_node_fingerprint(_flows(3), node, ObservationWindow.MEDIUM) for _ in range(10)
    ]
    baseline = build_node_baseline(history)

    deviating = assemble_node_fingerprint(_flows(200), node, ObservationWindow.MEDIUM)
    anomalies = detect_node_anomalies(baseline, deviating)

    assert any(a.dimension == AnomalyDimension.DESTINATIONS for a in anomalies)
