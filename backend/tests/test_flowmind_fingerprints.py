"""Phase 35 node behavioral fingerprint assembly unit tests (pure, no Docker)."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.app.models.behavior import BehavioralFingerprint, ObservationWindow
from backend.app.models.flow import Flow, FlowFeatures
from backend.app.models.packet import Packet, PacketDirection, TransportProtocol
from backend.app.models.topology import Node
from backend.flowmind.features.windows import compute_node_features_for_window
from backend.flowmind.fingerprints.node_fingerprint import (
    assemble_all_node_fingerprints,
    assemble_node_fingerprint,
)
from backend.nettrace.reconstruct import reconstruct_flows
from backend.nettrace.topology.discovery import discover_nodes
from experiments.artifacts.io import read_jsonl, write_jsonl
from experiments.artifacts.paths import fingerprints_path, packets_path

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _node(node_id: str, ip: str) -> Node:
    return Node(node_id=node_id, ip_addresses=[ip], first_observed=BASE, last_observed=BASE)


def _flow(
    flow_id: str,
    src_ip: str,
    src_port: int,
    dst_ip: str,
    dst_port: int,
    last_seen=BASE,
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


def test_assemble_node_fingerprint_matches_computed_features_exactly() -> None:
    node = _node("n0", "10.0.0.1")
    flows = [
        _flow("f0", "10.0.0.1", 51000, "10.0.0.2", 443),
        _flow("f1", "10.0.0.1", 51001, "10.0.0.3", 8080, is_persistent=True),
    ]

    expected_features = compute_node_features_for_window(flows, node, ObservationWindow.MEDIUM)
    fingerprint = assemble_node_fingerprint(flows, node, ObservationWindow.MEDIUM)

    for field, value in asdict(expected_features).items():
        assert getattr(fingerprint, field) == value


def test_assemble_node_fingerprint_sets_identity_fields() -> None:
    node = _node("n0", "10.0.0.1")
    flows = [_flow("f0", "10.0.0.1", 51000, "10.0.0.2", 443)]

    before = datetime.now(timezone.utc)
    fingerprint = assemble_node_fingerprint(flows, node, ObservationWindow.SHORT)
    after = datetime.now(timezone.utc)

    assert fingerprint.node_id == "n0"
    assert fingerprint.window == ObservationWindow.SHORT
    assert before <= fingerprint.computed_at <= after


def test_assemble_all_node_fingerprints_covers_every_node_and_window() -> None:
    nodes = [_node("n0", "10.0.0.1"), _node("n1", "10.0.0.2")]
    flows = [_flow("f0", "10.0.0.1", 51000, "10.0.0.2", 443)]

    fingerprints = assemble_all_node_fingerprints(flows, nodes)

    assert len(fingerprints) == 6  # 2 nodes * 3 windows
    for node in nodes:
        windows_seen = {fp.window for fp in fingerprints if fp.node_id == node.node_id}
        assert windows_seen == {ObservationWindow.SHORT, ObservationWindow.MEDIUM, ObservationWindow.LONG}


def test_assemble_all_node_fingerprints_shares_one_computed_at() -> None:
    nodes = [_node("n0", "10.0.0.1"), _node("n1", "10.0.0.2")]
    flows = [_flow("f0", "10.0.0.1", 51000, "10.0.0.2", 443)]

    fingerprints = assemble_all_node_fingerprints(flows, nodes)

    timestamps = {fp.computed_at for fp in fingerprints}
    assert len(timestamps) == 1


def test_assemble_all_node_fingerprints_with_no_nodes_returns_empty_list() -> None:
    flows = [_flow("f0", "10.0.0.1", 51000, "10.0.0.2", 443)]
    assert assemble_all_node_fingerprints(flows, []) == []


def test_fingerprints_round_trip_through_jsonl(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    nodes = [_node("n0", "10.0.0.1")]
    flows = [_flow("f0", "10.0.0.1", 51000, "10.0.0.2", 443)]

    fingerprints = assemble_all_node_fingerprints(flows, nodes)
    path = fingerprints_path(root, "cap-1")
    write_jsonl(path, fingerprints)

    round_tripped = read_jsonl(path, BehavioralFingerprint)
    assert round_tripped == fingerprints


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
        _pkt(
            "p3",
            BASE + timedelta(seconds=2, milliseconds=10),
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

    fingerprints = assemble_all_node_fingerprints(flows, nodes)

    assert len(fingerprints) == len(nodes) * 3
    for fp in fingerprints:
        assert isinstance(fp, BehavioralFingerprint)
        assert 0.0 <= fp.outbound_byte_ratio <= 1.0
