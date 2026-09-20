"""Phase 58 digital twin synchronization unit tests (pure, no Docker)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.app.models.behavior import ObservationWindow
from backend.app.models.packet import Packet, PacketDirection, TransportProtocol
from backend.app.models.snapshot import ChangeType
from backend.archaeology.behavior_evolution import track_node_behavioral_evolution
from backend.archaeology.diff import diff_snapshots
from backend.archaeology.snapshots import create_snapshot, read_snapshot_graph
from backend.digital_twin.sync import sync_digital_twin
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


def _episode_1(extra: int = 0) -> list:
    """A<->B at t=0, plus `extra` additional A<->B packets at t=60s (after
    the t=50s early snapshot but before the t=200s later one) -- enough to
    change the A<->B edge's confidence between two snapshots without
    changing its topology membership."""
    packets = [
        _pkt("p0", BASE, "10.0.0.1", 1000, "10.0.0.2", 80, TransportProtocol.TCP),
        _pkt("p1", BASE, "10.0.0.2", 80, "10.0.0.1", 1000, TransportProtocol.TCP),
    ]
    for i in range(extra):
        t = BASE + timedelta(seconds=60, milliseconds=i)
        packets.append(_pkt(f"p0x{i}", t, "10.0.0.1", 1000, "10.0.0.2", 80, TransportProtocol.TCP))
        packets.append(_pkt(f"p1x{i}", t, "10.0.0.2", 80, "10.0.0.1", 1000, TransportProtocol.TCP))
    return packets


def _episode_2() -> list:
    """C<->D at t=100s -- the same fixture Phase 43-47's own tests use."""
    return [
        _pkt("p2", BASE + timedelta(seconds=100), "10.0.0.3", 2000, "10.0.0.4", 53, TransportProtocol.UDP),
        _pkt("p3", BASE + timedelta(seconds=100), "10.0.0.4", 53, "10.0.0.3", 2000, TransportProtocol.UDP),
    ]


def _seed(root: Path, capture_id: str, extra_episode_1: int = 0, include_episode_2: bool = True) -> None:
    packets = _episode_1(extra_episode_1)
    if include_episode_2:
        packets += _episode_2()
    write_jsonl(packets_path(root, capture_id), packets)
    reconstruct_flows(root, capture_id)


def test_sync_reports_additions_for_a_new_episode(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _seed(root, "cap-1", include_episode_2=False)

    early = create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=50))
    twin = build_digital_twin(root, "cap-1", early)

    _seed(root, "cap-1", include_episode_2=True)
    later = create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=200))

    result = sync_digital_twin(root, twin, later)

    node_added = {e.affected_node_id for e in result.structural_changes if e.change_type == ChangeType.NODE_ADDED}
    edge_added = [e for e in result.structural_changes if e.change_type == ChangeType.EDGE_ADDED]
    assert len(node_added) == 2  # nodes C and D
    assert len(edge_added) == 1  # the new C<->D edge

    ips = {str(ip) for node in result.twin.topology.nodes for ip in node.ip_addresses}
    assert ips == {"10.0.0.1", "10.0.0.2", "10.0.0.3", "10.0.0.4"}
    assert result.twin.snapshot == later
    assert result.twin.topology == read_snapshot_graph(root, "cap-1", later)


def test_sync_reports_confidence_change_on_a_surviving_edge(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _seed(root, "cap-1", extra_episode_1=0, include_episode_2=True)

    early = create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=50))
    twin = build_digital_twin(root, "cap-1", early)

    _seed(root, "cap-1", extra_episode_1=20, include_episode_2=True)
    later = create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=200))

    result = sync_digital_twin(root, twin, later)

    confidence_events = [
        e
        for e in result.structural_changes
        if e.change_type == ChangeType.ATTRIBUTE_CHANGED and e.attribute_name == "confidence"
    ]
    assert len(confidence_events) == 1
    assert float(confidence_events[0].new_value) > float(confidence_events[0].previous_value)


def test_sync_reports_behavior_change_for_a_resupplied_fingerprint(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _seed(root, "cap-1")

    snapshot = create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=200))
    nodes = discover_nodes(root, "cap-1")
    node_a = next(n for n in nodes if "10.0.0.1" in {str(ip) for ip in n.ip_addresses})

    old_fp = assemble_node_fingerprint([], node_a, ObservationWindow.MEDIUM, computed_at=BASE)
    twin = build_digital_twin(root, "cap-1", snapshot, behavioral_fingerprints=[old_fp])

    later = create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=201))
    flows = reconstruct_flows(root, "cap-1")
    new_fp = assemble_node_fingerprint(
        flows, node_a, ObservationWindow.MEDIUM, computed_at=BASE + timedelta(seconds=201)
    )

    result = sync_digital_twin(root, twin, later, new_behavioral_fingerprints=[new_fp])

    expected = track_node_behavioral_evolution([old_fp, new_fp])
    assert len(result.behavior_changes) == len(expected)
    assert {e.feature_name for e in result.behavior_changes} == {e.feature_name for e in expected}
    assert any(fp.node_id == node_a.node_id and fp is new_fp for fp in result.twin.behavioral_fingerprints)


def test_sync_carries_forward_a_fingerprint_not_resupplied(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _seed(root, "cap-1")

    snapshot = create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=200))
    nodes = discover_nodes(root, "cap-1")
    node_a = next(n for n in nodes if "10.0.0.1" in {str(ip) for ip in n.ip_addresses})

    old_fp = assemble_node_fingerprint([], node_a, ObservationWindow.MEDIUM, computed_at=BASE)
    twin = build_digital_twin(root, "cap-1", snapshot, behavioral_fingerprints=[old_fp])

    later = create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=201))
    result = sync_digital_twin(root, twin, later)

    assert result.behavior_changes == []
    assert result.twin.behavioral_fingerprints == [old_fp]


def test_sync_produces_no_behavior_change_for_a_brand_new_node(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _seed(root, "cap-1", include_episode_2=False)

    early = create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=50))
    twin = build_digital_twin(root, "cap-1", early)

    _seed(root, "cap-1", include_episode_2=True)
    later = create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=200))
    flows = reconstruct_flows(root, "cap-1")
    nodes = discover_nodes(root, "cap-1")
    node_c = next(n for n in nodes if "10.0.0.3" in {str(ip) for ip in n.ip_addresses})
    new_fp = assemble_node_fingerprint(
        flows, node_c, ObservationWindow.MEDIUM, computed_at=BASE + timedelta(seconds=200)
    )

    result = sync_digital_twin(root, twin, later, new_behavioral_fingerprints=[new_fp])

    assert result.behavior_changes == []
    assert new_fp in result.twin.behavioral_fingerprints


def test_real_end_to_end_sync_matches_standalone_diffs(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _seed(root, "cap-1", extra_episode_1=0, include_episode_2=False)

    early = create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=50))
    early_flows = reconstruct_flows(root, "cap-1")
    early_nodes = discover_nodes(root, "cap-1")
    node_a = next(n for n in early_nodes if "10.0.0.1" in {str(ip) for ip in n.ip_addresses})
    old_fp = assemble_node_fingerprint(early_flows, node_a, ObservationWindow.MEDIUM, computed_at=BASE)
    twin = build_digital_twin(root, "cap-1", early, behavioral_fingerprints=[old_fp])

    _seed(root, "cap-1", extra_episode_1=20, include_episode_2=True)
    later = create_snapshot(root, "cap-1", captured_at=BASE + timedelta(seconds=200))
    later_flows = reconstruct_flows(root, "cap-1")
    new_fp = assemble_node_fingerprint(
        later_flows, node_a, ObservationWindow.MEDIUM, computed_at=BASE + timedelta(seconds=200)
    )

    result = sync_digital_twin(root, twin, later, new_behavioral_fingerprints=[new_fp])

    expected_structural = diff_snapshots(root, "cap-1", early, later)
    expected_behavior = track_node_behavioral_evolution([old_fp, new_fp])

    assert result.structural_changes == expected_structural
    assert result.behavior_changes == expected_behavior
    assert len(result.structural_changes) > 0
    assert len(result.behavior_changes) > 0
