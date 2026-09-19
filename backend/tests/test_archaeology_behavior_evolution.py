"""Phase 46 behavioral evolution tracking unit tests (pure, no Docker)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

import pytest

from backend.app.models.behavior import BehavioralFingerprint, ObservationWindow
from backend.app.models.flow import Flow, FlowFeatures
from backend.app.models.packet import TransportProtocol
from backend.app.models.topology import Node
from backend.archaeology.behavior_evolution import track_node_behavioral_evolution
from backend.flowmind.fingerprints.node_fingerprint import assemble_node_fingerprint

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _fp(
    node_id: str = "n0",
    window: ObservationWindow = ObservationWindow.MEDIUM,
    computed_at: datetime = BASE,
    ports=(80,),
    protocols=("TCP",),
    destinations: int = 1,
    duration: float = 1.0,
    ratio: float = 0.5,
    persistent: bool = False,
    total_bytes: int = 100,
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
        total_byte_count=total_bytes,
    )


def test_raises_on_empty_history() -> None:
    with pytest.raises(ValueError):
        track_node_behavioral_evolution([])


def test_raises_on_mixed_node_ids() -> None:
    history = [_fp(node_id="n0"), _fp(node_id="n1", computed_at=BASE + timedelta(seconds=1))]
    with pytest.raises(ValueError):
        track_node_behavioral_evolution(history)


def test_raises_on_mixed_windows() -> None:
    history = [
        _fp(window=ObservationWindow.SHORT),
        _fp(window=ObservationWindow.LONG, computed_at=BASE + timedelta(seconds=1)),
    ]
    with pytest.raises(ValueError):
        track_node_behavioral_evolution(history)


def test_single_fingerprint_returns_no_events() -> None:
    assert track_node_behavioral_evolution([_fp()]) == []


def test_no_events_when_nothing_changed() -> None:
    history = [_fp(computed_at=BASE), _fp(computed_at=BASE + timedelta(seconds=60))]
    assert track_node_behavioral_evolution(history) == []


def test_changed_continuous_feature_produces_one_event() -> None:
    history = [
        _fp(computed_at=BASE, ratio=0.3),
        _fp(computed_at=BASE + timedelta(seconds=60), ratio=0.9),
    ]

    events = track_node_behavioral_evolution(history)

    ratio_events = [e for e in events if e.feature_name == "outbound_byte_ratio"]
    assert len(ratio_events) == 1
    event = ratio_events[0]
    assert event.previous_value == "0.3"
    assert event.new_value == "0.9"
    assert event.from_computed_at == BASE
    assert event.to_computed_at == BASE + timedelta(seconds=60)


def test_changed_port_set_produces_evidence_naming_ports() -> None:
    history = [
        _fp(computed_at=BASE, ports=(80,)),
        _fp(computed_at=BASE + timedelta(seconds=60), ports=(80, 443)),
    ]

    events = track_node_behavioral_evolution(history)

    port_events = [e for e in events if e.feature_name == "distinct_ports"]
    assert len(port_events) == 1
    assert "443" in port_events[0].evidence[0]
    assert "added" in port_events[0].evidence[0]


def test_removed_protocol_produces_evidence_naming_it() -> None:
    history = [
        _fp(computed_at=BASE, protocols=("TCP", "UDP")),
        _fp(computed_at=BASE + timedelta(seconds=60), protocols=("TCP",)),
    ]

    events = track_node_behavioral_evolution(history)

    protocol_events = [e for e in events if e.feature_name == "distinct_protocols"]
    assert len(protocol_events) == 1
    assert "removed" in protocol_events[0].evidence[0]
    assert "UDP" in protocol_events[0].evidence[0]


def test_persistent_talker_flip_detected() -> None:
    history = [
        _fp(computed_at=BASE, persistent=False),
        _fp(computed_at=BASE + timedelta(seconds=60), persistent=True),
    ]

    events = track_node_behavioral_evolution(history)

    flip_events = [e for e in events if e.feature_name == "is_persistent_talker"]
    assert len(flip_events) == 1
    assert flip_events[0].previous_value == "False"
    assert flip_events[0].new_value == "True"


def test_every_event_has_non_empty_evidence() -> None:
    history = [
        _fp(computed_at=BASE, ports=(80,), destinations=1, ratio=0.1),
        _fp(computed_at=BASE + timedelta(seconds=60), ports=(443,), destinations=5, ratio=0.9),
    ]

    events = track_node_behavioral_evolution(history)

    assert events  # sanity: something fired
    for event in events:
        assert len(event.evidence) >= 1
        assert all(len(e) > 0 for e in event.evidence)


def test_multiple_transitions_are_chronological_and_deterministic() -> None:
    history = [
        _fp(computed_at=BASE, destinations=1),
        _fp(computed_at=BASE + timedelta(seconds=60), destinations=2),
        _fp(computed_at=BASE + timedelta(seconds=120), destinations=3),
    ]

    first_run = track_node_behavioral_evolution(history)
    second_run = track_node_behavioral_evolution(history)

    assert first_run == second_run
    assert [e.to_computed_at for e in first_run] == sorted(e.to_computed_at for e in first_run)


def test_real_end_to_end_via_assemble_node_fingerprint() -> None:
    node = Node(node_id="n-real", ip_addresses=["10.0.0.1"], first_observed=BASE, last_observed=BASE)

    def _flows(dst_ports: List[int]) -> List[Flow]:
        return [
            Flow(
                flow_id=f"f-{port}",
                capture_id="cap-1",
                src_ip="10.0.1.0",
                dst_ip="10.0.0.1",
                src_port=51000,
                dst_port=port,
                protocol=TransportProtocol.TCP,
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
            for port in dst_ports
        ]

    history = [
        assemble_node_fingerprint(_flows([80]), node, ObservationWindow.MEDIUM, computed_at=BASE),
        assemble_node_fingerprint(
            _flows([80, 443]), node, ObservationWindow.MEDIUM, computed_at=BASE + timedelta(seconds=60)
        ),
    ]

    events = track_node_behavioral_evolution(history)

    port_events = [e for e in events if e.feature_name == "distinct_ports"]
    assert len(port_events) == 1
    assert "443" in port_events[0].evidence[0]
