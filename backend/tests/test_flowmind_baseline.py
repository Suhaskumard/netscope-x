"""Phase 38 behavioral baseline unit tests (pure, no Docker)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List

import pytest

from backend.app.models.behavior import BehavioralFingerprint, ObservationWindow
from backend.app.models.flow import Flow, FlowFeatures
from backend.app.models.packet import TransportProtocol
from backend.app.models.topology import Node
from backend.flowmind.baseline.node_baseline import build_node_baseline
from backend.flowmind.fingerprints.node_fingerprint import assemble_node_fingerprint

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


def test_build_node_baseline_raises_on_empty_history() -> None:
    with pytest.raises(ValueError):
        build_node_baseline([])


def test_build_node_baseline_raises_on_mixed_node_ids() -> None:
    history = [_fp(node_id="n0"), _fp(node_id="n1")]
    with pytest.raises(ValueError):
        build_node_baseline(history)


def test_build_node_baseline_raises_on_mixed_windows() -> None:
    history = [
        _fp(window=ObservationWindow.SHORT),
        _fp(window=ObservationWindow.LONG),
    ]
    with pytest.raises(ValueError):
        build_node_baseline(history)


def test_median_and_mad_hand_computed() -> None:
    history = [_fp(destinations=d) for d in (1, 2, 3, 4, 100)]

    baseline = build_node_baseline(history)

    # sorted: 1,2,3,4,100 -> median 3
    # abs deviations: 2,1,0,1,97 -> sorted 0,1,1,2,97 -> median 1
    assert baseline.distinct_destinations.median == 3.0
    assert baseline.distinct_destinations.mad == 1.0


def test_historical_ports_and_protocols_accumulate_union() -> None:
    history = [
        _fp(ports=(80,), protocols=("TCP",)),
        _fp(ports=(443,), protocols=("TCP",)),
        _fp(ports=(53,), protocols=("UDP",)),
    ]

    baseline = build_node_baseline(history)

    assert baseline.historical_ports == frozenset({80, 443, 53})
    assert baseline.historical_protocols == frozenset({"TCP", "UDP"})


def test_persistent_talker_frequency_computed_correctly() -> None:
    history = [
        _fp(persistent=True),
        _fp(persistent=True),
        _fp(persistent=False),
        _fp(persistent=True),
    ]

    baseline = build_node_baseline(history)

    assert baseline.persistent_talker_frequency == pytest.approx(0.75)


def test_is_sufficient_reflects_min_observations() -> None:
    history = [_fp() for _ in range(3)]

    below_threshold = build_node_baseline(history, min_observations=5)
    at_threshold = build_node_baseline(history, min_observations=3)

    assert below_threshold.observation_count == 3
    assert below_threshold.is_sufficient is False
    assert at_threshold.is_sufficient is True


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

    def _flow(flow_id, dst_port, protocol, num_dest_ips) -> List[Flow]:
        flows = []
        for i in range(num_dest_ips):
            flows.append(
                Flow(
                    flow_id=f"{flow_id}-{i}",
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
            )
        return flows

    history = [
        assemble_node_fingerprint(_flow("f1", 80, TransportProtocol.TCP, 1), node, ObservationWindow.MEDIUM),
        assemble_node_fingerprint(_flow("f2", 80, TransportProtocol.TCP, 2), node, ObservationWindow.MEDIUM),
        assemble_node_fingerprint(_flow("f3", 80, TransportProtocol.TCP, 3), node, ObservationWindow.MEDIUM),
    ]

    baseline = build_node_baseline(history)

    assert baseline.node_id == "n-real"
    assert baseline.observation_count == 3
    assert baseline.historical_ports == frozenset()  # destination-only ports; node never contacted
    assert baseline.distinct_destinations.median == 2.0
