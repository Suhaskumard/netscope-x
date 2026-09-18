"""Phase 34 multi-window behavior modeling unit tests (pure, no Docker)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.app.models.behavior import ObservationWindow
from backend.app.models.flow import Flow, FlowFeatures
from backend.app.models.packet import Packet, PacketDirection, TransportProtocol
from backend.app.models.topology import Node
from backend.flowmind.features.windows import (
    DEFAULT_WINDOW_SECONDS,
    compute_node_features_all_windows,
    compute_node_features_for_window,
)
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
    last_seen,
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
        first_seen=last_seen - timedelta(seconds=duration_seconds),
        last_seen=last_seen,
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


def test_trailing_short_window_excludes_older_flows() -> None:
    node = _node("n0", "10.0.0.1")
    recent = _flow("f0", "10.0.0.1", 51000, "10.0.0.2", 443, last_seen=BASE)
    old = _flow("f1", "10.0.0.1", 51001, "10.0.0.3", 443, last_seen=BASE - timedelta(seconds=30))
    flows = [recent, old]

    short = compute_node_features_for_window(flows, node, ObservationWindow.SHORT)

    # Only the recent flow (destination 10.0.0.2) should count -- the old one (30s
    # before the anchor, outside the 10s short window) must be excluded.
    assert short.distinct_destinations == 1


def test_anchor_is_nodes_own_latest_activity_not_unrelated_traffic() -> None:
    node = _node("n0", "10.0.0.1")
    our_flow = _flow("f0", "10.0.0.1", 51000, "10.0.0.2", 443, last_seen=BASE)
    # Unrelated node's much-later traffic elsewhere in the same flow list.
    unrelated_later = _flow(
        "f1", "10.0.0.9", 51000, "10.0.0.8", 443, last_seen=BASE + timedelta(seconds=1000)
    )
    flows = [our_flow, unrelated_later]

    short = compute_node_features_for_window(flows, node, ObservationWindow.SHORT)

    # If the anchor were wrongly taken from the whole flow list (including the
    # unrelated node's much-later traffic), our_flow would fall far outside a
    # 10s trailing window and distinct_destinations would be 0.
    assert short.distinct_destinations == 1


def test_windows_are_nested_long_superset_of_medium_superset_of_short() -> None:
    node = _node("n0", "10.0.0.1")
    anchor = BASE
    flows = [
        _flow("f0", "10.0.0.1", 51000, "10.0.0.2", 443, last_seen=anchor),  # within all windows
        _flow(
            "f1", "10.0.0.1", 51001, "10.0.0.3", 443, last_seen=anchor - timedelta(seconds=30)
        ),  # within medium/long only
        _flow(
            "f2", "10.0.0.1", 51002, "10.0.0.4", 443, last_seen=anchor - timedelta(seconds=200)
        ),  # within long only
    ]

    results = compute_node_features_all_windows(flows, node)

    assert results[ObservationWindow.SHORT].distinct_destinations == 1
    assert results[ObservationWindow.MEDIUM].distinct_destinations == 2
    assert results[ObservationWindow.LONG].distinct_destinations == 3


def test_compute_node_features_all_windows_returns_exactly_three_windows() -> None:
    node = _node("n0", "10.0.0.1")
    flows = [_flow("f0", "10.0.0.1", 51000, "10.0.0.2", 443, last_seen=BASE)]

    results = compute_node_features_all_windows(flows, node)

    assert set(results.keys()) == {ObservationWindow.SHORT, ObservationWindow.MEDIUM, ObservationWindow.LONG}


def test_node_with_no_touching_flows_returns_honest_zeros_for_all_windows() -> None:
    node = _node("n0", "10.0.0.1")
    flows = [_flow("f0", "10.0.0.5", 51000, "10.0.0.6", 443, last_seen=BASE)]

    results = compute_node_features_all_windows(flows, node)

    for window in ObservationWindow:
        features = results[window]
        assert features.distinct_ports == []
        assert features.distinct_destinations == 0
        assert features.is_persistent_talker is False


def test_custom_window_seconds_override_changes_windowing() -> None:
    node = _node("n0", "10.0.0.1")
    flows = [
        _flow("f0", "10.0.0.1", 51000, "10.0.0.2", 443, last_seen=BASE),
        _flow("f1", "10.0.0.1", 51001, "10.0.0.3", 443, last_seen=BASE - timedelta(seconds=30)),
    ]

    default_short = compute_node_features_for_window(flows, node, ObservationWindow.SHORT)
    widened_short = compute_node_features_for_window(
        flows, node, ObservationWindow.SHORT, window_seconds={ObservationWindow.SHORT: 60.0}
    )

    assert default_short.distinct_destinations == 1
    assert widened_short.distinct_destinations == 2


def test_default_window_seconds_matches_settings_defaults() -> None:
    assert DEFAULT_WINDOW_SECONDS[ObservationWindow.SHORT] == 10.0
    assert DEFAULT_WINDOW_SECONDS[ObservationWindow.MEDIUM] == 60.0
    assert DEFAULT_WINDOW_SECONDS[ObservationWindow.LONG] == 300.0


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
        # A second, much later flow -- outside the default short window, inside medium/long.
        _pkt(
            "p2",
            BASE + timedelta(seconds=45),
            "10.0.0.1",
            51001,
            "10.0.0.3",
            53,
            TransportProtocol.UDP,
        ),
        _pkt(
            "p3",
            BASE + timedelta(seconds=45, milliseconds=10),
            "10.0.0.3",
            53,
            "10.0.0.1",
            51001,
            TransportProtocol.UDP,
        ),
    ]
    write_jsonl(packets_path(root, "cap-1"), packets)
    flows = reconstruct_flows(root, "cap-1")
    nodes = discover_nodes(root, "cap-1")

    node_1 = next(n for n in nodes if str(n.ip_addresses[0]) == "10.0.0.1")
    results = compute_node_features_all_windows(flows, node_1)

    assert results[ObservationWindow.SHORT].distinct_destinations == 1
    assert results[ObservationWindow.MEDIUM].distinct_destinations == 2
    assert results[ObservationWindow.LONG].distinct_destinations == 2
