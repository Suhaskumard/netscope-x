"""Phase 51 dependency strength estimation unit tests (pure, no Docker)."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.app.models.packet import Packet, PacketDirection, TransportProtocol
from backend.dependency.communication import derive_communication_relationships
from backend.dependency.strength import (
    _DEFAULT_DEPENDENCY_SIGNAL_STRENGTH,
    _DEFAULT_FREQUENCY_SCALE,
    _DEFAULT_PERSISTENCE_SCALE,
    estimate_dependency_strength,
)
from backend.nettrace.reconstruct import reconstruct_flows
from backend.nettrace.topology.discovery import discover_nodes
from backend.nettrace.topology.edges import _bidirectionality, bucket_flows_by_node_pair, discover_edges
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


def test_no_packets_returns_empty(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"

    dependencies = estimate_dependency_strength(root, "cap-1")

    assert dependencies == []


def test_single_exchange_matches_hand_computed_fields(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    packets = [
        _pkt("p0", BASE, "10.0.0.1", 1000, "10.0.0.2", 80, TransportProtocol.TCP),
        _pkt("p1", BASE + timedelta(seconds=10), "10.0.0.2", 80, "10.0.0.1", 1000, TransportProtocol.TCP),
    ]
    write_jsonl(packets_path(root, "cap-1"), packets)
    reconstruct_flows(root, "cap-1")

    dependencies = estimate_dependency_strength(root, "cap-1")
    relationships = derive_communication_relationships(root, "cap-1")
    nodes = discover_nodes(root, "cap-1")
    edges = discover_edges(root, "cap-1", nodes)
    buckets = bucket_flows_by_node_pair(root, "cap-1", nodes)

    assert len(dependencies) == 1
    dep = dependencies[0]
    edge = edges[0]
    rel = relationships[0]

    assert dep.source_node_id == edge.source_node_id
    assert dep.target_node_id == edge.target_node_id
    assert dep.frequency == rel.frequency
    assert dep.persistence_seconds == rel.persistence_seconds
    assert dep.temporal_precedence_score == 0.0

    bucket_flows = buckets[(edge.source_node_id, edge.target_node_id)]
    mean_ratio = sum(f.features.forward_byte_ratio for f in bucket_flows) / len(bucket_flows)
    expected_directionality = 1 - _bidirectionality(mean_ratio)
    assert dep.directionality_score == expected_directionality

    p_frequency = 1 - math.exp(-rel.frequency / _DEFAULT_FREQUENCY_SCALE)
    p_persistence = 1 - math.exp(-rel.persistence_seconds / _DEFAULT_PERSISTENCE_SCALE)
    s = _DEFAULT_DEPENDENCY_SIGNAL_STRENGTH
    survival = (1 - p_frequency) * (1 - s * p_persistence) * (1 - s * expected_directionality) * (1 - s * edge.confidence)
    expected_strength = 1 - survival
    assert dep.strength == expected_strength
    assert 0.0 <= dep.strength <= 1.0


def test_two_independent_episodes_produce_two_dependency_edges(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
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
    write_jsonl(packets_path(root, "cap-1"), packets)
    reconstruct_flows(root, "cap-1")

    dependencies = estimate_dependency_strength(root, "cap-1")

    assert len(dependencies) == 2
    dependency_ids = {d.dependency_id for d in dependencies}
    assert len(dependency_ids) == 2
    for dep in dependencies:
        assert dep.temporal_precedence_score == 0.0


def test_as_of_excludes_later_communication(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
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
    write_jsonl(packets_path(root, "cap-1"), packets)
    reconstruct_flows(root, "cap-1")

    dependencies = estimate_dependency_strength(root, "cap-1", as_of=BASE + timedelta(seconds=50))

    assert len(dependencies) == 1


def test_one_way_traffic_scores_near_maximal_directionality(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    # Many packets one direction, none the other -> forward_byte_ratio near 0 or 1.
    packets = [_pkt(f"p{i}", BASE + timedelta(seconds=i), "10.0.0.1", 1000, "10.0.0.2", 80, TransportProtocol.UDP) for i in range(5)]
    write_jsonl(packets_path(root, "cap-1"), packets)
    reconstruct_flows(root, "cap-1")

    dependencies = estimate_dependency_strength(root, "cap-1")

    assert len(dependencies) == 1
    assert dependencies[0].directionality_score > 0.9


def test_balanced_traffic_scores_near_minimal_directionality(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    packets = [
        _pkt("p0", BASE, "10.0.0.1", 1000, "10.0.0.2", 80, TransportProtocol.TCP),
        _pkt("p1", BASE + timedelta(seconds=1), "10.0.0.2", 80, "10.0.0.1", 1000, TransportProtocol.TCP),
    ]
    write_jsonl(packets_path(root, "cap-1"), packets)
    reconstruct_flows(root, "cap-1")

    dependencies = estimate_dependency_strength(root, "cap-1")

    assert len(dependencies) == 1
    # Equal packet sizes in both directions -> forward_byte_ratio == 0.5 -> minimal directionality.
    assert dependencies[0].directionality_score < 0.1


def test_never_raises_for_missing_capture(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"

    assert estimate_dependency_strength(root, "cap-nonexistent") == []
