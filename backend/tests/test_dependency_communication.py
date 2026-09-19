"""Phase 50 communication relationship derivation unit tests (pure, no Docker)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.app.models.packet import Packet, PacketDirection, TransportProtocol
from backend.dependency.communication import derive_communication_relationships
from backend.nettrace.reconstruct import reconstruct_flows
from backend.nettrace.topology.discovery import discover_nodes
from backend.nettrace.topology.edges import discover_edges
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

    relationships = derive_communication_relationships(root, "cap-1")

    assert relationships == []


def test_single_exchange_matches_corresponding_edge(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    packets = [
        _pkt("p0", BASE, "10.0.0.1", 1000, "10.0.0.2", 80, TransportProtocol.TCP),
        _pkt("p1", BASE + timedelta(seconds=10), "10.0.0.2", 80, "10.0.0.1", 1000, TransportProtocol.TCP),
    ]
    write_jsonl(packets_path(root, "cap-1"), packets)
    reconstruct_flows(root, "cap-1")

    relationships = derive_communication_relationships(root, "cap-1")
    nodes = discover_nodes(root, "cap-1")
    edges = discover_edges(root, "cap-1", nodes)

    assert len(relationships) == 1
    assert len(edges) == 1
    edge = edges[0]
    rel = relationships[0]

    assert rel.source_node_id == edge.source_node_id
    assert rel.target_node_id == edge.target_node_id
    assert rel.persistence_seconds == (edge.last_observed - edge.first_observed).total_seconds()
    assert rel.frequency == edge.observation_count / rel.persistence_seconds


def test_two_independent_episodes_produce_two_relationships(tmp_path: Path) -> None:
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

    relationships = derive_communication_relationships(root, "cap-1")
    nodes = discover_nodes(root, "cap-1")
    edges = discover_edges(root, "cap-1", nodes)

    assert len(relationships) == 2
    assert len(edges) == 2
    pairs = {(r.source_node_id, r.target_node_id) for r in relationships}
    edge_pairs = {(e.source_node_id, e.target_node_id) for e in edges}
    assert pairs == edge_pairs


def test_zero_duration_flow_falls_back_to_observation_count(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    packets = [
        _pkt("p0", BASE, "10.0.0.1", 1000, "10.0.0.2", 80, TransportProtocol.TCP),
        _pkt("p1", BASE, "10.0.0.2", 80, "10.0.0.1", 1000, TransportProtocol.TCP),
    ]
    write_jsonl(packets_path(root, "cap-1"), packets)
    reconstruct_flows(root, "cap-1")

    relationships = derive_communication_relationships(root, "cap-1")

    assert len(relationships) == 1
    rel = relationships[0]
    assert rel.persistence_seconds == 0.0
    assert rel.frequency == 1.0  # falls back to observation_count (1 flow), never a ZeroDivisionError


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

    relationships = derive_communication_relationships(root, "cap-1", as_of=BASE + timedelta(seconds=50))

    assert len(relationships) == 1
    assert relationships[0].source_node_id != relationships[0].target_node_id


def test_relationship_fields_are_never_negative(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    packets = [
        _pkt("p0", BASE, "10.0.0.1", 1000, "10.0.0.2", 80, TransportProtocol.TCP),
        _pkt("p1", BASE + timedelta(seconds=5), "10.0.0.2", 80, "10.0.0.1", 1000, TransportProtocol.TCP),
    ]
    write_jsonl(packets_path(root, "cap-1"), packets)
    reconstruct_flows(root, "cap-1")

    relationships = derive_communication_relationships(root, "cap-1")

    assert relationships  # sanity: something fired
    for rel in relationships:
        assert rel.frequency >= 0
        assert rel.persistence_seconds >= 0


def test_never_carries_a_dependency_shaped_field(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    packets = [
        _pkt("p0", BASE, "10.0.0.1", 1000, "10.0.0.2", 80, TransportProtocol.TCP),
        _pkt("p1", BASE + timedelta(seconds=5), "10.0.0.2", 80, "10.0.0.1", 1000, TransportProtocol.TCP),
    ]
    write_jsonl(packets_path(root, "cap-1"), packets)
    reconstruct_flows(root, "cap-1")

    relationships = derive_communication_relationships(root, "cap-1")

    assert relationships
    field_names = set(type(relationships[0]).model_fields.keys())
    assert field_names == {"source_node_id", "target_node_id", "frequency", "persistence_seconds"}
