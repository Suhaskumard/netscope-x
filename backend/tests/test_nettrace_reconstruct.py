"""Phase 23 five-tuple flow reconstruction unit tests (pure, no Docker)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.app.models.flow import Flow
from backend.app.models.packet import Packet, PacketDirection, TransportProtocol
from backend.nettrace.reconstruct import reconstruct_flows
from experiments.artifacts.io import read_jsonl, write_jsonl
from experiments.artifacts.paths import flows_path, packets_path

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _pkt(pid, t, src_ip, src_port, dst_ip, dst_port, protocol, size=100, flags=None) -> Packet:
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
        tcp_flags=flags,
    )


def _seed_packets(root: Path, capture_id: str, packets) -> None:
    write_jsonl(packets_path(root, capture_id), packets)


def test_reconstruct_flows_merges_both_directions_into_one_flow(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    packets = [
        _pkt("p0", BASE, "10.0.0.1", 1000, "10.0.0.2", 80, TransportProtocol.TCP, size=60, flags="SYN"),
        _pkt(
            "p1",
            BASE + timedelta(milliseconds=10),
            "10.0.0.2",
            80,
            "10.0.0.1",
            1000,
            TransportProtocol.TCP,
            size=60,
            flags="SYN,ACK",
        ),
        _pkt(
            "p2",
            BASE + timedelta(milliseconds=20),
            "10.0.0.1",
            1000,
            "10.0.0.2",
            80,
            TransportProtocol.TCP,
            size=40,
            flags="ACK",
        ),
    ]
    _seed_packets(root, "cap-1", packets)

    flows = reconstruct_flows(root, "cap-1")

    assert len(flows) == 1
    flow = flows[0]
    assert str(flow.src_ip) == "10.0.0.1"
    assert flow.src_port == 1000
    assert str(flow.dst_ip) == "10.0.0.2"
    assert flow.dst_port == 80
    assert flow.protocol == TransportProtocol.TCP
    assert flow.tcp_state is None
    assert flow.fingerprinted_protocol is None
    assert flow.features.packet_count == 3
    assert flow.features.byte_count == 160
    assert flow.features.is_persistent is False


def test_reconstruct_flows_assigns_forward_and_reverse_direction(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    packets = [
        _pkt("p0", BASE, "10.0.0.1", 1000, "10.0.0.2", 80, TransportProtocol.TCP, size=60),
        _pkt("p1", BASE + timedelta(milliseconds=10), "10.0.0.2", 80, "10.0.0.1", 1000, TransportProtocol.TCP, size=60),
    ]
    _seed_packets(root, "cap-1", packets)

    reconstruct_flows(root, "cap-1")

    resolved = read_jsonl(packets_path(root, "cap-1"), Packet)
    assert resolved[0].packet_id == "p0"
    assert resolved[0].direction == PacketDirection.FORWARD
    assert resolved[1].packet_id == "p1"
    assert resolved[1].direction == PacketDirection.REVERSE


def test_reconstruct_flows_computes_real_feature_arithmetic(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    packets = [
        _pkt("p0", BASE, "10.0.0.1", 1000, "10.0.0.2", 80, TransportProtocol.TCP, size=100),
        _pkt("p1", BASE + timedelta(seconds=2), "10.0.0.1", 1000, "10.0.0.2", 80, TransportProtocol.TCP, size=100),
        _pkt("p2", BASE + timedelta(seconds=4), "10.0.0.2", 80, "10.0.0.1", 1000, TransportProtocol.TCP, size=50),
    ]
    _seed_packets(root, "cap-1", packets)

    flows = reconstruct_flows(root, "cap-1")
    features = flows[0].features

    assert features.packet_count == 3
    assert features.byte_count == 250
    assert features.duration_seconds == 4.0
    assert features.mean_inter_arrival_seconds == 2.0
    # Forward = the two packets matching the first packet's orientation (10.0.0.1:1000 -> 10.0.0.2:80).
    assert features.forward_byte_ratio == 200 / 250
    assert features.destination_diversity == 1
    assert features.port_diversity == 1


def test_reconstruct_flows_separates_distinct_five_tuples(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    packets = [
        _pkt("p0", BASE, "10.0.0.1", 1000, "10.0.0.2", 80, TransportProtocol.TCP),
        _pkt("p1", BASE + timedelta(seconds=1), "10.0.0.1", 2000, "10.0.0.3", 53, TransportProtocol.UDP),
    ]
    _seed_packets(root, "cap-1", packets)

    flows = reconstruct_flows(root, "cap-1")

    assert len(flows) == 2
    protocols = {f.protocol for f in flows}
    assert protocols == {TransportProtocol.TCP, TransportProtocol.UDP}


def test_reconstruct_flows_excludes_icmp_and_other_from_flows(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    packets = [
        _pkt("p0", BASE, "10.0.0.1", 1000, "10.0.0.2", 80, TransportProtocol.TCP),
        _pkt("p1", BASE + timedelta(seconds=1), "10.0.0.1", None, "10.0.0.2", None, TransportProtocol.ICMP),
    ]
    _seed_packets(root, "cap-1", packets)

    flows = reconstruct_flows(root, "cap-1")

    assert len(flows) == 1
    resolved = read_jsonl(packets_path(root, "cap-1"), Packet)
    icmp_pkt = next(p for p in resolved if p.packet_id == "p1")
    assert icmp_pkt.direction == PacketDirection.UNKNOWN


def test_reconstruct_flows_writes_and_round_trips_through_jsonl(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    packets = [
        _pkt("p0", BASE, "10.0.0.1", 1000, "10.0.0.2", 80, TransportProtocol.TCP),
        _pkt("p1", BASE + timedelta(seconds=1), "10.0.0.2", 80, "10.0.0.1", 1000, TransportProtocol.TCP),
    ]
    _seed_packets(root, "cap-1", packets)

    flows = reconstruct_flows(root, "cap-1")

    stored = read_jsonl(flows_path(root, "cap-1"), Flow)
    assert stored == flows


def test_reconstruct_flows_preserves_original_packet_order(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    packets = [
        _pkt("p0", BASE, "10.0.0.1", 1000, "10.0.0.2", 80, TransportProtocol.TCP),
        _pkt("p1", BASE + timedelta(seconds=1), "10.0.0.3", 2000, "10.0.0.4", 53, TransportProtocol.UDP),
        _pkt("p2", BASE + timedelta(seconds=2), "10.0.0.2", 80, "10.0.0.1", 1000, TransportProtocol.TCP),
    ]
    _seed_packets(root, "cap-1", packets)

    reconstruct_flows(root, "cap-1")

    resolved = read_jsonl(packets_path(root, "cap-1"), Packet)
    assert [p.packet_id for p in resolved] == ["p0", "p1", "p2"]
