"""Phase 44 network snapshot engine unit tests (pure, no Docker)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.app.models.packet import Packet, PacketDirection, TransportProtocol
from backend.archaeology.snapshots import create_snapshot, list_snapshots, read_snapshot_graph
from backend.nettrace.reconstruct import reconstruct_flows
from experiments.artifacts.io import read_json, write_jsonl
from experiments.artifacts.paths import packets_path, snapshot_path

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
    """Episode 1 (A<->B) at t=0; episode 2 (C<->D) at t=100s -- mirrors
    Phase 43's own temporal-graph test fixture."""
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


def test_create_snapshot_starts_at_version_one(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _seed_two_episodes(root)

    snapshot = create_snapshot(root, "cap-1", captured_at=BASE)

    assert snapshot.version == 1
    assert snapshot.snapshot_id == "cap-1-snapshot-1"
    assert snapshot.graph_id == "cap-1-snapshot-1"


def test_create_snapshot_increments_version_on_each_call(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _seed_two_episodes(root)

    first = create_snapshot(root, "cap-1", captured_at=BASE)
    second = create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=200))

    assert first.version == 1
    assert second.version == 2


def test_create_snapshot_persists_graph_and_snapshot_round_trip(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _seed_two_episodes(root)

    snapshot = create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=200))

    from backend.app.models.snapshot import NetworkSnapshot

    reread_snapshot = read_json(snapshot_path(root, "cap-1", snapshot.snapshot_id), NetworkSnapshot)
    assert reread_snapshot == snapshot

    graph = read_snapshot_graph(root, "cap-1", snapshot)
    assert graph.graph_id == snapshot.graph_id
    ips = {str(ip) for node in graph.nodes for ip in node.ip_addresses}
    assert ips == {"10.0.0.1", "10.0.0.2", "10.0.0.3", "10.0.0.4"}


def test_create_snapshot_captured_at_genuinely_bounds_the_graph(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _seed_two_episodes(root)

    early = create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=50))
    late = create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=200))

    early_graph = read_snapshot_graph(root, "cap-1", early)
    late_graph = read_snapshot_graph(root, "cap-1", late)

    assert len(early_graph.nodes) == 2
    assert len(early_graph.edges) == 1
    assert len(late_graph.nodes) == 4
    assert len(late_graph.edges) == 2


def test_list_snapshots_returns_empty_for_no_snapshots(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    assert list_snapshots(root, "no-such-capture") == []


def test_list_snapshots_ordered_by_version(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _seed_two_episodes(root)

    create_snapshot(root, "cap-1", captured_at=BASE)
    create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=200))
    create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=300))

    snapshots = list_snapshots(root, "cap-1")

    assert [s.version for s in snapshots] == [1, 2, 3]


def test_create_snapshot_defaults_captured_at_to_now(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _seed_two_episodes(root)

    before = datetime.now(timezone.utc)
    snapshot = create_snapshot(root, "cap-1")
    after = datetime.now(timezone.utc)

    assert before <= snapshot.captured_at <= after


def test_create_snapshot_independent_versioning_across_captures(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _seed_two_episodes(root, capture_id="cap-1")
    _seed_two_episodes(root, capture_id="cap-2")

    cap1_snapshot = create_snapshot(root, "cap-1", captured_at=BASE)
    cap2_snapshot = create_snapshot(root, "cap-2", captured_at=BASE)

    assert cap1_snapshot.version == 1
    assert cap2_snapshot.version == 1


def test_create_snapshot_missing_capture_produces_empty_graph_not_an_error(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"

    snapshot = create_snapshot(root, "no-such-capture", captured_at=BASE)

    assert snapshot.version == 1
    graph = read_snapshot_graph(root, "no-such-capture", snapshot)
    assert graph.nodes == []
    assert graph.edges == []
