"""Phase 33 behavioral feature store unit tests (pure, no Docker)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.app.models.flow import Flow, FlowFeatures
from backend.app.models.packet import Packet, PacketDirection, TransportProtocol
from backend.app.models.topology import Node
from backend.flowmind.features.node_features import compute_node_behavioral_features
from backend.nettrace.reconstruct import reconstruct_flows
from backend.nettrace.topology.discovery import discover_nodes
from experiments.artifacts.io import write_jsonl
from experiments.artifacts.paths import packets_path

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _node(node_id: str, ip: str) -> Node:
    return Node(node_id=node_id, ip_addresses=[ip], first_observed=BASE, last_observed=BASE)


def _flow(
    flow_id: str,
    src_ip: str,
    src_port: int,
    dst_ip: str,
    dst_port: int,
    protocol=TransportProtocol.TCP,
    byte_count: int = 100,
    duration_seconds: float = 1.0,
    forward_byte_ratio: float = 0.5,
    is_persistent: bool = False,
) -> Flow:
    return Flow(
        flow_id=flow_id,
        capture_id="cap-1",
        src_ip=src_ip,
        dst_ip=dst_ip,
        src_port=src_port,
        dst_port=dst_port,
        protocol=protocol,
        first_seen=BASE,
        last_seen=BASE + timedelta(seconds=duration_seconds),
        features=FlowFeatures(
            packet_count=2,
            byte_count=byte_count,
            duration_seconds=duration_seconds,
            burstiness=0.0,
            mean_inter_arrival_seconds=0.1,
            forward_byte_ratio=forward_byte_ratio,
            destination_diversity=1,
            port_diversity=1,
            is_persistent=is_persistent,
        ),
    )


def test_distinct_ports_only_counts_ports_where_node_is_destination() -> None:
    node = _node("n0", "10.0.0.1")
    flows = [
        _flow("f0", "10.0.0.2", 51000, "10.0.0.1", 443),  # node is dst on 443
        _flow("f1", "10.0.0.1", 51000, "10.0.0.3", 9999),  # node is src; 9999 is NOT node's port
    ]

    features = compute_node_behavioral_features(flows, node)

    assert features.distinct_ports == [443]


def test_distinct_protocols_aggregates_across_both_directions() -> None:
    node = _node("n0", "10.0.0.1")
    flows = [
        _flow("f0", "10.0.0.2", 51000, "10.0.0.1", 443, protocol=TransportProtocol.TCP),
        _flow("f1", "10.0.0.1", 51000, "10.0.0.4", 53, protocol=TransportProtocol.UDP),
    ]

    features = compute_node_behavioral_features(flows, node)

    assert features.distinct_protocols == ["TCP", "UDP"]


def test_distinct_destinations_only_counts_outbound_flows() -> None:
    node = _node("n0", "10.0.0.1")
    flows = [
        _flow("f0", "10.0.0.1", 51000, "10.0.0.2", 443),  # outbound to .2
        _flow("f1", "10.0.0.1", 51001, "10.0.0.3", 443),  # outbound to .3
        _flow("f2", "10.0.0.9", 51002, "10.0.0.1", 443),  # inbound from .9 -- not a "destination"
    ]

    features = compute_node_behavioral_features(flows, node)

    assert features.distinct_destinations == 2


def test_mean_flow_duration_seconds_averages_across_touching_flows() -> None:
    node = _node("n0", "10.0.0.1")
    flows = [
        _flow("f0", "10.0.0.1", 51000, "10.0.0.2", 443, duration_seconds=2.0),
        _flow("f1", "10.0.0.2", 443, "10.0.0.1", 51000, duration_seconds=4.0),
    ]

    features = compute_node_behavioral_features(flows, node)

    assert features.mean_flow_duration_seconds == 3.0


def test_outbound_byte_ratio_hand_computed() -> None:
    node = _node("n0", "10.0.0.1")
    flows = [
        # node is source: sends forward_byte_ratio * byte_count = 0.8 * 100 = 80
        _flow("f0", "10.0.0.1", 51000, "10.0.0.2", 443, byte_count=100, forward_byte_ratio=0.8),
        # node is destination: sends (1 - forward_byte_ratio) * byte_count = 0.5 * 50 = 25
        _flow("f1", "10.0.0.3", 51001, "10.0.0.1", 8080, byte_count=50, forward_byte_ratio=0.5),
    ]

    features = compute_node_behavioral_features(flows, node)

    # total sent = 80 + 25 = 105; total bytes = 100 + 50 = 150; ratio = 0.7
    assert abs(features.outbound_byte_ratio - 0.7) < 1e-9


def test_is_persistent_talker_true_when_any_touching_flow_is_persistent() -> None:
    node = _node("n0", "10.0.0.1")

    not_persistent = compute_node_behavioral_features(
        [_flow("f0", "10.0.0.1", 51000, "10.0.0.2", 443, is_persistent=False)], node
    )
    assert not_persistent.is_persistent_talker is False

    persistent = compute_node_behavioral_features(
        [
            _flow("f0", "10.0.0.1", 51000, "10.0.0.2", 443, is_persistent=False),
            _flow("f1", "10.0.0.1", 51001, "10.0.0.3", 53, is_persistent=True),
        ],
        node,
    )
    assert persistent.is_persistent_talker is True


def test_node_with_no_touching_flows_returns_honest_zero_values() -> None:
    node = _node("n0", "10.0.0.1")
    flows = [_flow("f0", "10.0.0.2", 51000, "10.0.0.3", 443)]  # touches neither ip

    features = compute_node_behavioral_features(flows, node)

    assert features.distinct_ports == []
    assert features.distinct_protocols == []
    assert features.distinct_destinations == 0
    assert features.mean_flow_duration_seconds == 0.0
    assert features.outbound_byte_ratio == 0.0
    assert features.is_persistent_talker is False


def test_unrelated_flows_are_excluded_from_every_feature() -> None:
    node = _node("n0", "10.0.0.1")
    relevant = _flow("f0", "10.0.0.1", 51000, "10.0.0.2", 443, duration_seconds=2.0)
    unrelated = _flow("f1", "10.0.0.5", 51000, "10.0.0.6", 9999, duration_seconds=100.0)

    with_unrelated = compute_node_behavioral_features([relevant, unrelated], node)
    without_unrelated = compute_node_behavioral_features([relevant], node)

    assert with_unrelated == without_unrelated


def _pkt(pid, t, src_ip, src_port, dst_ip, dst_port, protocol, size=100) -> Packet:
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


def test_real_end_to_end_through_reconstruct_flows_and_discover_nodes(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    packets = [
        _pkt("p0", BASE, "10.0.0.1", 51000, "10.0.0.2", 80, TransportProtocol.TCP),
        _pkt("p1", BASE + timedelta(seconds=1), "10.0.0.2", 80, "10.0.0.1", 51000, TransportProtocol.TCP),
        _pkt("p2", BASE + timedelta(seconds=2), "10.0.0.1", 51001, "10.0.0.3", 53, TransportProtocol.UDP),
    ]
    write_jsonl(packets_path(root, "cap-1"), packets)
    flows = reconstruct_flows(root, "cap-1")
    nodes = discover_nodes(root, "cap-1")

    node_1 = next(n for n in nodes if str(n.ip_addresses[0]) == "10.0.0.1")
    features = compute_node_behavioral_features(flows, node_1)

    assert "TCP" in features.distinct_protocols
    assert "UDP" in features.distinct_protocols
    assert features.distinct_destinations == 2  # .2 and .3
    assert features.mean_flow_duration_seconds >= 0.0
