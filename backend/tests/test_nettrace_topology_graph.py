"""Phase 32 topology assembly + Phase 43 temporal (as_of) unit tests (pure, no Docker).

No dedicated unit-test file existed for `build_topology_graph` before Phase 43 --
its Phase 32 coverage lives in `test_api.py`'s `GET /topology` section. This file
adds direct unit coverage for the function itself, focused on Phase 43's new
`as_of` parameter (spec Phase 43, FR-1.20: "represent the network as a
time-indexed graph G(t)").
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.app.models.packet import Packet, PacketDirection, TransportProtocol
from backend.nettrace.reconstruct import reconstruct_flows
from backend.nettrace.topology.graph import build_topology_graph
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


def _seed_two_episodes(root: Path) -> None:
    """Episode 1 (A<->B) at t=0; episode 2 (C<->D) at t=100s -- two distinct,
    time-separated communication episodes in one capture."""
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


def test_build_topology_graph_as_of_before_either_episode_is_empty(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _seed_two_episodes(root)

    graph = build_topology_graph(root, "cap-1", "g1", as_of=BASE - timedelta(seconds=1))

    assert graph.nodes == []
    assert graph.edges == []


def test_build_topology_graph_as_of_between_episodes_shows_only_first(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _seed_two_episodes(root)

    graph = build_topology_graph(root, "cap-1", "g1", as_of=BASE + timedelta(seconds=50))

    ips = {str(ip) for node in graph.nodes for ip in node.ip_addresses}
    assert ips == {"10.0.0.1", "10.0.0.2"}
    assert len(graph.edges) == 1


def test_build_topology_graph_as_of_after_both_episodes_shows_everything(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _seed_two_episodes(root)

    graph = build_topology_graph(root, "cap-1", "g1", as_of=BASE + timedelta(seconds=200))

    ips = {str(ip) for node in graph.nodes for ip in node.ip_addresses}
    assert ips == {"10.0.0.1", "10.0.0.2", "10.0.0.3", "10.0.0.4"}
    assert len(graph.edges) == 2


def test_build_topology_graph_node_and_edge_counts_grow_monotonically_over_time(
    tmp_path: Path,
) -> None:
    root = tmp_path / "artifacts"
    _seed_two_episodes(root)

    before = build_topology_graph(root, "cap-1", "g1", as_of=BASE - timedelta(seconds=1))
    between = build_topology_graph(root, "cap-1", "g1", as_of=BASE + timedelta(seconds=50))
    after = build_topology_graph(root, "cap-1", "g1", as_of=BASE + timedelta(seconds=200))

    assert len(before.nodes) <= len(between.nodes) <= len(after.nodes)
    assert len(before.edges) <= len(between.edges) <= len(after.edges)


def test_build_topology_graph_without_as_of_matches_unbounded_behavior(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _seed_two_episodes(root)

    unbounded = build_topology_graph(root, "cap-1", "g1")
    explicit_none = build_topology_graph(root, "cap-1", "g1", as_of=None)
    far_future = build_topology_graph(root, "cap-1", "g1", as_of=BASE + timedelta(days=365))

    unbounded_ips = {str(ip) for node in unbounded.nodes for ip in node.ip_addresses}
    explicit_none_ips = {str(ip) for node in explicit_none.nodes for ip in node.ip_addresses}
    far_future_ips = {str(ip) for node in far_future.nodes for ip in node.ip_addresses}

    assert unbounded_ips == explicit_none_ips == far_future_ips
    assert len(unbounded.edges) == len(explicit_none.edges) == len(far_future.edges)


def test_build_topology_graph_missing_capture_returns_empty_graph_regardless_of_as_of(
    tmp_path: Path,
) -> None:
    root = tmp_path / "artifacts"

    graph = build_topology_graph(root, "no-such-capture", "g1", as_of=BASE)

    assert graph.nodes == []
    assert graph.edges == []
