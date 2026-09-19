"""Phase 45 graph difference engine unit tests (pure, no Docker)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.app.models.packet import Packet, PacketDirection, TransportProtocol
from backend.app.models.snapshot import ChangeType
from backend.archaeology.diff import diff_snapshots
from backend.archaeology.snapshots import create_snapshot, read_snapshot_graph
from backend.nettrace.reconstruct import reconstruct_flows
from experiments.artifacts.io import write_jsonl
from experiments.artifacts.paths import packets_path

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _pkt(pid, t, src_ip, src_port, dst_ip, dst_port, protocol) -> Packet:
    return Packet(
        packet_id=pid,
        capture_id="cap-1",
        timestamp=t,
        src_ip=src_ip,
        dst_ip=dst_ip,
        src_port=src_port,
        dst_port=dst_port,
        protocol=protocol,
        size_bytes=100,
        direction=PacketDirection.UNKNOWN,
    )


def _seed_two_episodes(root: Path, capture_id: str = "cap-1") -> None:
    """Episode 1 (A<->B) at t=0; episode 2 (C<->D) at t=100s -- the same
    fixture Phase 43/44's own tests use."""
    packets = [
        _pkt("p0", BASE, "10.0.0.1", 1000, "10.0.0.2", 80, TransportProtocol.TCP),
        _pkt("p1", BASE, "10.0.0.2", 80, "10.0.0.1", 1000, TransportProtocol.TCP),
        _pkt(
            "p2",
            BASE + timedelta(seconds=100),
            "10.0.0.3",
            2000,
            "10.0.0.4",
            53,
            TransportProtocol.UDP,
        ),
        _pkt(
            "p3",
            BASE + timedelta(seconds=100),
            "10.0.0.4",
            53,
            "10.0.0.3",
            2000,
            TransportProtocol.UDP,
        ),
    ]
    write_jsonl(packets_path(root, capture_id), packets)
    reconstruct_flows(root, capture_id)


def test_node_and_edge_ids_are_stable_across_growing_as_of(tmp_path: Path) -> None:
    """The property diff_snapshots' entire algorithm depends on: an
    already-observed node/edge keeps the exact same id at a later as_of."""
    root = tmp_path / "artifacts"
    _seed_two_episodes(root)

    early = create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=50))
    late = create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=200))

    early_graph = read_snapshot_graph(root, "cap-1", early)
    late_graph = read_snapshot_graph(root, "cap-1", late)

    early_node_ids_by_ip = {str(n.ip_addresses[0]): n.node_id for n in early_graph.nodes}
    late_node_ids_by_ip = {str(n.ip_addresses[0]): n.node_id for n in late_graph.nodes}
    for ip, node_id in early_node_ids_by_ip.items():
        assert late_node_ids_by_ip[ip] == node_id

    assert len(early_graph.edges) == 1
    early_edge_id = early_graph.edges[0].edge_id
    late_edge_ids = {e.edge_id for e in late_graph.edges}
    assert early_edge_id in late_edge_ids


def test_diff_detects_node_additions(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _seed_two_episodes(root)

    early = create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=50))
    late = create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=200))

    events = diff_snapshots(root, "cap-1", early, late)

    node_added = [e for e in events if e.change_type == ChangeType.NODE_ADDED]
    assert len(node_added) == 2
    added_node_ids = {e.affected_node_id for e in node_added}
    late_node_ids = {n.node_id for n in read_snapshot_graph(root, "cap-1", late).nodes}
    assert added_node_ids <= late_node_ids


def test_diff_detects_edge_additions(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _seed_two_episodes(root)

    early = create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=50))
    late = create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=200))

    events = diff_snapshots(root, "cap-1", early, late)

    edge_added = [e for e in events if e.change_type == ChangeType.EDGE_ADDED]
    assert len(edge_added) == 1


def test_diff_no_changes_between_identical_snapshots(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _seed_two_episodes(root)

    first = create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=50))
    second = create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=50))

    events = diff_snapshots(root, "cap-1", first, second)

    assert events == []


def test_diff_detects_edge_confidence_attribute_change(tmp_path: Path) -> None:
    """Reuses Phase 43's own confidence-growth fixture pattern: a second
    flow joins an already-existing edge's bucket between two as_of values."""
    root = tmp_path / "artifacts"
    packets = [
        _pkt("p0", BASE, "10.0.0.1", 1000, "10.0.0.2", 9999, TransportProtocol.TCP),
        _pkt("p1", BASE, "10.0.0.2", 9999, "10.0.0.1", 1000, TransportProtocol.TCP),
        *[
            _pkt(
                f"q{i}",
                BASE + timedelta(seconds=30 + i),
                "10.0.0.1" if i % 2 == 0 else "10.0.0.2",
                1001 if i % 2 == 0 else 9999,
                "10.0.0.2" if i % 2 == 0 else "10.0.0.1",
                9999 if i % 2 == 0 else 1001,
                TransportProtocol.TCP,
            )
            for i in range(20)
        ],
    ]
    write_jsonl(packets_path(root, "cap-1"), packets)
    reconstruct_flows(root, "cap-1")

    early = create_snapshot(root, "cap-1", captured_at=BASE)
    late = create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=60))

    events = diff_snapshots(root, "cap-1", early, late)

    confidence_events = [
        e
        for e in events
        if e.change_type == ChangeType.ATTRIBUTE_CHANGED and e.attribute_name == "confidence"
    ]
    assert len(confidence_events) == 1
    event = confidence_events[0]
    assert float(event.previous_value) < float(event.new_value)


def test_diff_detects_edge_protocol_attribute_change(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    packets = [
        _pkt("p0", BASE, "10.0.0.1", 1000, "10.0.0.2", 80, TransportProtocol.TCP),
        _pkt("p1", BASE, "10.0.0.2", 80, "10.0.0.1", 1000, TransportProtocol.TCP),
        _pkt(
            "p2",
            BASE + timedelta(seconds=10),
            "10.0.0.1",
            2000,
            "10.0.0.2",
            53,
            TransportProtocol.UDP,
        ),
        _pkt(
            "p3",
            BASE + timedelta(seconds=10),
            "10.0.0.2",
            53,
            "10.0.0.1",
            2000,
            TransportProtocol.UDP,
        ),
    ]
    write_jsonl(packets_path(root, "cap-1"), packets)
    reconstruct_flows(root, "cap-1")

    early = create_snapshot(root, "cap-1", captured_at=BASE)
    late = create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=20))

    events = diff_snapshots(root, "cap-1", early, late)

    protocol_events = [
        e
        for e in events
        if e.change_type == ChangeType.ATTRIBUTE_CHANGED and e.attribute_name == "protocols"
    ]
    assert len(protocol_events) == 1
    assert protocol_events[0].previous_value == "TCP"
    assert protocol_events[0].new_value == "TCP,UDP"


def test_diff_never_produces_node_attribute_changed_events(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    packets = [
        _pkt("p0", BASE, "10.0.0.1", 1000, "10.0.0.2", 80, TransportProtocol.TCP),
        _pkt(
            "p1",
            BASE + timedelta(seconds=50),
            "10.0.0.1",
            1000,
            "10.0.0.2",
            80,
            TransportProtocol.TCP,
        ),
    ]
    write_jsonl(packets_path(root, "cap-1"), packets)
    reconstruct_flows(root, "cap-1")

    early = create_snapshot(root, "cap-1", captured_at=BASE)
    late = create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=100))

    early_graph = read_snapshot_graph(root, "cap-1", early)
    late_graph = read_snapshot_graph(root, "cap-1", late)
    # Sanity: last_observed genuinely advanced for the shared node.
    assert late_graph.nodes[0].last_observed > early_graph.nodes[0].last_observed

    events = diff_snapshots(root, "cap-1", early, late)

    node_attribute_events = [
        e
        for e in events
        if e.change_type == ChangeType.ATTRIBUTE_CHANGED and e.affected_node_id is not None
    ]
    assert node_attribute_events == []


def test_diff_reversed_order_produces_removed_events(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _seed_two_episodes(root)

    early = create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=50))
    late = create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=200))

    reversed_events = diff_snapshots(root, "cap-1", late, early)

    node_removed = [e for e in reversed_events if e.change_type == ChangeType.NODE_REMOVED]
    edge_removed = [e for e in reversed_events if e.change_type == ChangeType.EDGE_REMOVED]
    assert len(node_removed) == 2
    assert len(edge_removed) == 1
    assert not any(e.change_type == ChangeType.NODE_ADDED for e in reversed_events)
    assert not any(e.change_type == ChangeType.EDGE_ADDED for e in reversed_events)


def test_diff_every_event_has_non_empty_evidence(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _seed_two_episodes(root)

    early = create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=50))
    late = create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=200))

    events = diff_snapshots(root, "cap-1", early, late)

    assert events  # sanity: something fired
    for event in events:
        assert len(event.evidence) >= 1
        assert all(len(e) > 0 for e in event.evidence)


def test_diff_is_deterministic_across_repeated_calls(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _seed_two_episodes(root)

    early = create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=50))
    late = create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=200))

    first_run = diff_snapshots(root, "cap-1", early, late)
    second_run = diff_snapshots(root, "cap-1", early, late)

    assert first_run == second_run
