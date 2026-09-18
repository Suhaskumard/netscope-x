"""Phase 30 edge discovery unit tests (pure, no Docker)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.app.models.packet import Packet, PacketDirection, TransportProtocol
from backend.nettrace.reconstruct import reconstruct_flows
from backend.nettrace.topology.discovery import discover_nodes
from backend.nettrace.topology.edges import discover_edges
from experiments.artifacts.io import write_jsonl
from experiments.artifacts.paths import packets_path

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


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


def _seed(root: Path, capture_id: str, packets) -> None:
    write_jsonl(packets_path(root, capture_id), packets)


def _prepare(root: Path, capture_id: str, packets):
    """Seeds packets, then runs the real pipeline: reconstruct_flows + discover_nodes,
    returning (nodes, edges) so tests exercise discover_edges against real upstream output."""
    _seed(root, capture_id, packets)
    reconstruct_flows(root, capture_id)
    nodes = discover_nodes(root, capture_id)
    edges = discover_edges(root, capture_id, nodes)
    return nodes, edges


def test_discover_edges_finds_edge_between_two_communicating_nodes(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    packets = [
        _pkt("p0", BASE, "10.0.0.1", 1000, "10.0.0.2", 80, TransportProtocol.TCP),
        _pkt("p1", BASE + timedelta(seconds=1), "10.0.0.2", 80, "10.0.0.1", 1000, TransportProtocol.TCP),
    ]
    nodes, edges = _prepare(root, "cap-1", packets)

    node_ids = {str(n.ip_addresses[0]): n.node_id for n in nodes}
    assert len(edges) == 1
    edge = edges[0]
    assert {edge.source_node_id, edge.target_node_id} == {
        node_ids["10.0.0.1"],
        node_ids["10.0.0.2"],
    }


def test_discover_edges_finds_multiple_distinct_node_pairs(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    packets = [
        _pkt("p0", BASE, "10.0.0.1", 1000, "10.0.0.2", 80, TransportProtocol.TCP),
        _pkt("p1", BASE, "10.0.0.2", 80, "10.0.0.1", 1000, TransportProtocol.TCP),
        _pkt("p2", BASE + timedelta(seconds=1), "10.0.0.3", 2000, "10.0.0.4", 53, TransportProtocol.UDP),
        _pkt("p3", BASE + timedelta(seconds=1), "10.0.0.4", 53, "10.0.0.3", 2000, TransportProtocol.UDP),
    ]
    _, edges = _prepare(root, "cap-1", packets)

    assert len(edges) == 2
    pairs = {frozenset((e.source_node_id, e.target_node_id)) for e in edges}
    assert len(pairs) == 2


def test_discover_edges_aggregates_multiple_flows_for_same_pair(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    packets = [
        _pkt("p0", BASE, "10.0.0.1", 1000, "10.0.0.2", 80, TransportProtocol.TCP),
        _pkt("p1", BASE, "10.0.0.2", 80, "10.0.0.1", 1000, TransportProtocol.TCP),
        _pkt(
            "p2",
            BASE + timedelta(seconds=30),
            "10.0.0.1",
            1001,
            "10.0.0.2",
            80,
            TransportProtocol.TCP,
        ),
        _pkt(
            "p3",
            BASE + timedelta(seconds=30, milliseconds=10),
            "10.0.0.2",
            80,
            "10.0.0.1",
            1001,
            TransportProtocol.TCP,
        ),
    ]
    _, edges = _prepare(root, "cap-1", packets)

    assert len(edges) == 1
    edge = edges[0]
    assert edge.observation_count == 2
    assert len(edge.evidence) == 2
    assert edge.first_observed == BASE
    assert edge.last_observed == BASE + timedelta(seconds=30, milliseconds=10)


def test_discover_edges_protocols_and_observation_count_grow_with_more_flows(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    packets = [
        _pkt("p0", BASE, "10.0.0.1", 1000, "10.0.0.2", 80, TransportProtocol.TCP),
        _pkt("p1", BASE, "10.0.0.2", 80, "10.0.0.1", 1000, TransportProtocol.TCP),
        _pkt("p2", BASE + timedelta(seconds=1), "10.0.0.1", 2000, "10.0.0.2", 53, TransportProtocol.UDP),
        _pkt("p3", BASE + timedelta(seconds=1), "10.0.0.2", 53, "10.0.0.1", 2000, TransportProtocol.UDP),
        _pkt(
            "p4",
            BASE + timedelta(seconds=2),
            "10.0.0.1",
            1001,
            "10.0.0.2",
            80,
            TransportProtocol.TCP,
        ),
        _pkt(
            "p5",
            BASE + timedelta(seconds=2),
            "10.0.0.2",
            80,
            "10.0.0.1",
            1001,
            TransportProtocol.TCP,
        ),
    ]
    _, edges = _prepare(root, "cap-1", packets)

    assert len(edges) == 1
    edge = edges[0]
    assert edge.observation_count == 3
    assert edge.protocols == ["TCP", "UDP"]


def test_discover_edges_deterministic_ordering_and_ids(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    packets = [
        _pkt("p0", BASE, "10.0.0.9", 1000, "10.0.0.5", 80, TransportProtocol.TCP),
        _pkt("p1", BASE, "10.0.0.5", 80, "10.0.0.9", 1000, TransportProtocol.TCP),
        _pkt("p2", BASE + timedelta(seconds=1), "10.0.0.3", 2000, "10.0.0.7", 53, TransportProtocol.UDP),
        _pkt("p3", BASE + timedelta(seconds=1), "10.0.0.7", 53, "10.0.0.3", 2000, TransportProtocol.UDP),
    ]
    _seed(root, "cap-1", packets)
    reconstruct_flows(root, "cap-1")
    nodes = discover_nodes(root, "cap-1")

    first_run = discover_edges(root, "cap-1", nodes)
    second_run = discover_edges(root, "cap-1", nodes)

    assert first_run == second_run
    assert [e.edge_id for e in first_run] == ["cap-1:edge:0", "cap-1:edge:1"]


def test_discover_edges_missing_flows_file_returns_empty_list(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    assert discover_edges(root, "no-such-capture", []) == []


def test_discover_edges_empty_flows_file_returns_empty_list(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _seed(root, "cap-1", [])
    reconstruct_flows(root, "cap-1")
    nodes = discover_nodes(root, "cap-1")
    assert discover_edges(root, "cap-1", nodes) == []


def test_discover_edges_icmp_only_capture_produces_zero_edges_despite_nodes_found(
    tmp_path: Path,
) -> None:
    root = tmp_path / "artifacts"
    packets = [
        _pkt("p0", BASE, "10.0.0.1", None, "10.0.0.2", None, TransportProtocol.ICMP),
    ]
    nodes, edges = _prepare(root, "cap-1", packets)

    # Documented asymmetry (docs/architecture/node_discovery.md): nodes come from
    # packets.jsonl directly, edges come from flows.jsonl -- ICMP is excluded from
    # flow reconstruction, so it can produce nodes but never edges.
    assert len(nodes) == 2
    assert edges == []


def test_discover_edges_self_referential_flow_produces_no_self_loop_edge(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    packets = [
        _pkt("p0", BASE, "10.0.0.5", 1000, "10.0.0.5", 80, TransportProtocol.TCP),
        _pkt("p1", BASE, "10.0.0.5", 80, "10.0.0.5", 1000, TransportProtocol.TCP),
    ]
    nodes, edges = _prepare(root, "cap-1", packets)

    assert len(nodes) == 1
    assert edges == []


def test_discover_edges_confidence_increases_with_more_observed_packets(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    packets = [
        # Pair A-B: one small exchange.
        _pkt("p0", BASE, "10.0.0.1", 1000, "10.0.0.2", 80, TransportProtocol.TCP),
        _pkt("p1", BASE, "10.0.0.2", 80, "10.0.0.1", 1000, TransportProtocol.TCP),
        # Pair C-D: many packets on one flow.
        *[
            _pkt(
                f"q{i}",
                BASE + timedelta(seconds=i),
                "10.0.0.3" if i % 2 == 0 else "10.0.0.4",
                2000,
                "10.0.0.4" if i % 2 == 0 else "10.0.0.3",
                2000,
                TransportProtocol.UDP,
            )
            for i in range(40)
        ],
    ]
    _, edges = _prepare(root, "cap-1", packets)

    assert len(edges) == 2
    light, heavy = sorted(edges, key=lambda e: e.confidence)
    assert "40 packets" in heavy.evidence[0]
    assert "2 packets" in light.evidence[0]
    assert heavy.confidence > light.confidence


def test_discover_edges_confidence_always_strictly_between_zero_and_one(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    packets = [
        _pkt("p0", BASE, "10.0.0.1", 1000, "10.0.0.2", 80, TransportProtocol.TCP),
        _pkt("p1", BASE, "10.0.0.2", 80, "10.0.0.1", 1000, TransportProtocol.TCP),
        *[
            _pkt(
                f"q{i}",
                BASE + timedelta(seconds=i),
                "10.0.0.3" if i % 2 == 0 else "10.0.0.4",
                2000,
                "10.0.0.4" if i % 2 == 0 else "10.0.0.3",
                2000,
                TransportProtocol.UDP,
            )
            for i in range(500)
        ],
    ]
    _, edges = _prepare(root, "cap-1", packets)

    for edge in edges:
        assert 0.0 <= edge.confidence <= 1.0
        assert edge.confidence < 1.0


def test_discover_edges_flow_with_ip_not_in_nodes_is_skipped(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    packets = [
        _pkt("p0", BASE, "10.0.0.1", 1000, "10.0.0.2", 80, TransportProtocol.TCP),
        _pkt("p1", BASE, "10.0.0.2", 80, "10.0.0.1", 1000, TransportProtocol.TCP),
    ]
    _seed(root, "cap-1", packets)
    reconstruct_flows(root, "cap-1")
    all_nodes = discover_nodes(root, "cap-1")
    partial_nodes = [n for n in all_nodes if str(n.ip_addresses[0]) != "10.0.0.2"]

    edges = discover_edges(root, "cap-1", partial_nodes)
    assert edges == []
