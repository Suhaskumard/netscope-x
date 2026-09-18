"""Phase 29 node discovery unit tests (pure, no Docker)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.app.models.packet import Packet, PacketDirection, TransportProtocol
from backend.nettrace.reconstruct import reconstruct_flows
from backend.nettrace.topology.discovery import discover_nodes
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


def test_discover_nodes_finds_multiple_distinct_ips(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    packets = [
        _pkt("p0", BASE, "10.0.0.1", 1000, "10.0.0.2", 80, TransportProtocol.TCP),
        _pkt(
            "p1",
            BASE + timedelta(seconds=1),
            "10.0.0.3",
            1000,
            "10.0.0.4",
            53,
            TransportProtocol.UDP,
        ),
    ]
    _seed(root, "cap-1", packets)

    nodes = discover_nodes(root, "cap-1")

    ips = {ip for node in nodes for ip in [str(a) for a in node.ip_addresses]}
    assert ips == {"10.0.0.1", "10.0.0.2", "10.0.0.3", "10.0.0.4"}
    assert len(nodes) == 4
    assert all(len(node.ip_addresses) == 1 for node in nodes)


def test_discover_nodes_first_last_observed_across_multiple_packets(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    packets = [
        _pkt("p0", BASE, "10.0.0.1", 1000, "10.0.0.2", 80, TransportProtocol.TCP),
        _pkt(
            "p1",
            BASE + timedelta(seconds=5),
            "10.0.0.2",
            80,
            "10.0.0.1",
            1000,
            TransportProtocol.TCP,
        ),
        _pkt(
            "p2",
            BASE + timedelta(seconds=10),
            "10.0.0.1",
            1000,
            "10.0.0.2",
            80,
            TransportProtocol.TCP,
        ),
    ]
    _seed(root, "cap-1", packets)

    nodes = {str(node.ip_addresses[0]): node for node in discover_nodes(root, "cap-1")}

    assert nodes["10.0.0.1"].first_observed == BASE
    assert nodes["10.0.0.1"].last_observed == BASE + timedelta(seconds=10)
    assert nodes["10.0.0.2"].first_observed == BASE
    assert nodes["10.0.0.2"].last_observed == BASE + timedelta(seconds=10)


def test_discover_nodes_deterministic_ordering_and_ids(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    packets = [
        _pkt("p0", BASE, "10.0.0.9", 1000, "10.0.0.5", 80, TransportProtocol.TCP),
        _pkt("p1", BASE, "10.0.0.5", 80, "10.0.0.9", 1000, TransportProtocol.TCP),
    ]
    _seed(root, "cap-1", packets)

    first_run = discover_nodes(root, "cap-1")
    second_run = discover_nodes(root, "cap-1")

    assert first_run == second_run
    # Same first_observed timestamp for both IPs -> tie-break lexicographically.
    assert [str(n.ip_addresses[0]) for n in first_run] == ["10.0.0.5", "10.0.0.9"]
    assert [n.node_id for n in first_run] == ["cap-1:node:0", "cap-1:node:1"]


def test_discover_nodes_missing_capture_returns_empty_list(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    assert discover_nodes(root, "no-such-capture") == []


def test_discover_nodes_empty_capture_returns_empty_list(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _seed(root, "cap-1", [])
    assert discover_nodes(root, "cap-1") == []


def test_discover_nodes_finds_icmp_only_node_missed_by_flow_reconstruction(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    packets = [
        _pkt("p0", BASE, "10.0.0.1", None, "10.0.0.2", None, TransportProtocol.ICMP),
    ]
    _seed(root, "cap-1", packets)

    nodes = discover_nodes(root, "cap-1")
    ips = {str(node.ip_addresses[0]) for node in nodes}
    assert ips == {"10.0.0.1", "10.0.0.2"}

    flows = reconstruct_flows(root, "cap-1")
    flow_ips = {str(f.src_ip) for f in flows} | {str(f.dst_ip) for f in flows}
    assert flow_ips == set()


def test_discover_nodes_destination_only_ip_is_discovered(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    packets = [
        _pkt("p0", BASE, "10.0.0.1", 1000, "10.0.0.2", 80, TransportProtocol.TCP),
        _pkt(
            "p1",
            BASE + timedelta(seconds=1),
            "10.0.0.1",
            1001,
            "10.0.0.2",
            80,
            TransportProtocol.TCP,
        ),
    ]
    _seed(root, "cap-1", packets)

    ips = {str(node.ip_addresses[0]) for node in discover_nodes(root, "cap-1")}
    assert "10.0.0.2" in ips


def test_discover_nodes_source_only_ip_is_discovered(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    packets = [
        _pkt("p0", BASE, "10.0.0.1", 1000, "10.0.0.2", 80, TransportProtocol.TCP),
    ]
    _seed(root, "cap-1", packets)

    ips = {str(node.ip_addresses[0]) for node in discover_nodes(root, "cap-1")}
    assert "10.0.0.1" in ips
