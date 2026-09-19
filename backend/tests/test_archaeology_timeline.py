"""Phase 47 topology event timeline unit tests (pure, no Docker)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.app.models.packet import Packet, PacketDirection, TransportProtocol
from backend.app.models.snapshot import ChangeType
from backend.archaeology.diff import diff_snapshots
from backend.archaeology.snapshots import create_snapshot
from backend.archaeology.timeline import build_topology_event_timeline, read_topology_event_timeline
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
    fixture Phase 43-46's own tests use."""
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


def test_no_snapshots_returns_empty_timeline(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _seed_two_episodes(root)

    events = build_topology_event_timeline(root, "cap-1")

    assert events == []


def test_single_snapshot_returns_empty_timeline(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _seed_two_episodes(root)
    create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=50))

    events = build_topology_event_timeline(root, "cap-1")

    assert events == []


def test_three_snapshots_match_concatenated_pairwise_diffs(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _seed_two_episodes(root)

    s1 = create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=10))
    s2 = create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=100))
    s3 = create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=200))

    timeline = build_topology_event_timeline(root, "cap-1")

    expected = diff_snapshots(root, "cap-1", s1, s2) + diff_snapshots(root, "cap-1", s2, s3)
    assert timeline == expected


def test_timeline_groups_events_by_consecutive_pair_in_order(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _seed_two_episodes(root)

    create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=10))
    create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=100))
    create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=200))

    timeline = build_topology_event_timeline(root, "cap-1")

    # First pair (s1->s2) introduces the second episode's node/edge additions;
    # the second pair (s2->s3) introduces nothing new (no further packets) --
    # confirming events appear in generation-pair order, not re-sorted globally.
    node_added = [e for e in timeline if e.change_type == ChangeType.NODE_ADDED]
    assert len(node_added) == 2
    assert all(e.to_snapshot_id == timeline[0].to_snapshot_id for e in node_added)


def test_read_topology_event_timeline_round_trips(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _seed_two_episodes(root)
    create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=10))
    create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=200))

    built = build_topology_event_timeline(root, "cap-1")
    read_back = read_topology_event_timeline(root, "cap-1")

    assert read_back == built


def test_read_topology_event_timeline_missing_returns_empty(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"

    assert read_topology_event_timeline(root, "cap-nonexistent") == []


def test_build_is_deterministic_across_repeated_calls(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _seed_two_episodes(root)
    create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=10))
    create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=200))

    first_run = build_topology_event_timeline(root, "cap-1")
    second_run = build_topology_event_timeline(root, "cap-1")

    assert first_run == second_run


def test_every_event_has_non_empty_evidence(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _seed_two_episodes(root)
    create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=10))
    create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=200))

    timeline = build_topology_event_timeline(root, "cap-1")

    assert timeline  # sanity: something fired
    for event in timeline:
        assert len(event.evidence) >= 1
        assert all(len(e) > 0 for e in event.evidence)
