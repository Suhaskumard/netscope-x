"""Phase 57 digital twin model unit tests (pure, no Docker)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.app.models.behavior import ObservationWindow
from backend.app.models.packet import Packet, PacketDirection, TransportProtocol
from backend.archaeology.snapshots import create_snapshot, read_snapshot_graph
from backend.digital_twin.twin import build_digital_twin
from backend.flowmind.fingerprints.node_fingerprint import assemble_node_fingerprint
from backend.nettrace.reconstruct import reconstruct_flows
from backend.nettrace.topology.discovery import discover_nodes
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
    fixture Phase 43-47's own tests use."""
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


def test_twin_anchored_at_earlier_snapshot_shows_only_first_episode(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _seed_two_episodes(root)

    early = create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=50))
    twin = build_digital_twin(root, "cap-1", early)

    ips = {str(ip) for node in twin.topology.nodes for ip in node.ip_addresses}
    assert ips == {"10.0.0.1", "10.0.0.2"}
    assert len(twin.dependencies) == 1


def test_twin_anchored_at_later_snapshot_shows_both_episodes(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _seed_two_episodes(root)

    late = create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=200))
    twin = build_digital_twin(root, "cap-1", late)

    ips = {str(ip) for node in twin.topology.nodes for ip in node.ip_addresses}
    assert ips == {"10.0.0.1", "10.0.0.2", "10.0.0.3", "10.0.0.4"}
    assert len(twin.dependencies) == 2


def test_history_filtered_to_events_up_to_anchoring_snapshot(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _seed_two_episodes(root)

    s1 = create_snapshot(root, "cap-1", captured_at=BASE - timedelta(seconds=1))
    s2 = create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=50))
    s3 = create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=200))

    twin_at_s2 = build_digital_twin(root, "cap-1", s2)
    # Only the s1 -> s2 transition (episode 1 arriving) should be visible.
    assert len(twin_at_s2.history) > 0
    assert all(event.occurred_at <= s2.captured_at for event in twin_at_s2.history)

    twin_at_s3 = build_digital_twin(root, "cap-1", s3)
    assert len(twin_at_s3.history) > len(twin_at_s2.history)


def test_topology_matches_read_snapshot_graph_directly(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _seed_two_episodes(root)

    snapshot = create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=200))
    twin = build_digital_twin(root, "cap-1", snapshot)

    direct_graph = read_snapshot_graph(root, "cap-1", snapshot)
    assert twin.topology == direct_graph


def test_behavioral_fingerprints_pass_through_unchanged(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _seed_two_episodes(root)

    snapshot = create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=200))
    nodes = discover_nodes(root, "cap-1")

    fingerprints = [
        assemble_node_fingerprint([], nodes[0], ObservationWindow.MEDIUM, computed_at=BASE)
    ]

    twin = build_digital_twin(root, "cap-1", snapshot, behavioral_fingerprints=fingerprints)

    assert twin.behavioral_fingerprints is fingerprints


def test_missing_capture_produces_empty_twin_not_error(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    snapshot = create_snapshot(root, "no-such-capture", captured_at=BASE)

    twin = build_digital_twin(root, "no-such-capture", snapshot)

    assert twin.topology.nodes == []
    assert twin.dependencies == []
    assert twin.history == []
    assert twin.behavioral_fingerprints == []


def test_generated_at_is_real_and_distinct_from_snapshot_captured_at(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _seed_two_episodes(root)
    snapshot = create_snapshot(root, "cap-1", captured_at=BASE)

    before = datetime.now(timezone.utc)
    twin = build_digital_twin(root, "cap-1", snapshot)
    after = datetime.now(timezone.utc)

    assert before <= twin.generated_at <= after
    assert twin.generated_at != snapshot.captured_at


def test_deterministic_content_across_repeated_calls(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _seed_two_episodes(root)
    snapshot = create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=200))

    first = build_digital_twin(root, "cap-1", snapshot)
    second = build_digital_twin(root, "cap-1", snapshot)

    assert first.topology == second.topology
    assert first.dependencies == second.dependencies
    assert first.history == second.history


def test_real_end_to_end_with_real_fingerprints(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _seed_two_episodes(root)
    snapshot = create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=200))

    nodes = discover_nodes(root, "cap-1")
    flows = reconstruct_flows(root, "cap-1")
    fingerprints = [
        assemble_node_fingerprint(flows, node, ObservationWindow.MEDIUM, computed_at=BASE)
        for node in nodes
    ]

    twin = build_digital_twin(root, "cap-1", snapshot, behavioral_fingerprints=fingerprints)

    assert len(twin.behavioral_fingerprints) == len(nodes)
    topology_node_ids = {n.node_id for n in twin.topology.nodes}
    for dependency in twin.dependencies:
        assert dependency.source_node_id in topology_node_ids
        assert dependency.target_node_id in topology_node_ids
