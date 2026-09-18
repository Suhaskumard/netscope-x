"""Phase 22 packet normalization unit tests (pure, no Docker/live capture)."""

from __future__ import annotations

from pathlib import Path

from scapy.all import ICMP, IP, TCP, UDP, Ether, wrpcap

from backend.app.models.packet import Packet, PacketDirection, TransportProtocol
from backend.nettrace.normalize import normalize_pcap
from experiments.artifacts.io import read_jsonl
from experiments.artifacts.paths import packets_path, pcap_path


def _seed_pcap(root: Path, capture_id: str, packets) -> None:
    path = pcap_path(root, capture_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    wrpcap(str(path), packets)


def test_normalize_pcap_extracts_tcp_fields(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _seed_pcap(root, "cap-1", [IP(src="10.0.0.1", dst="10.0.0.2") / TCP(sport=1111, dport=80, flags="SA")])

    result = normalize_pcap(root, "cap-1")

    assert len(result) == 1
    pkt = result[0]
    assert pkt.packet_id == "cap-1:0"
    assert pkt.capture_id == "cap-1"
    assert str(pkt.src_ip) == "10.0.0.1"
    assert str(pkt.dst_ip) == "10.0.0.2"
    assert pkt.src_port == 1111
    assert pkt.dst_port == 80
    assert pkt.protocol == TransportProtocol.TCP
    assert pkt.tcp_flags == "SYN,ACK"
    assert pkt.direction == PacketDirection.UNKNOWN
    assert pkt.size_bytes == 40


def test_normalize_pcap_extracts_udp_fields(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _seed_pcap(root, "cap-2", [IP(src="10.0.0.1", dst="10.0.0.2") / UDP(sport=2222, dport=53)])

    result = normalize_pcap(root, "cap-2")

    assert len(result) == 1
    pkt = result[0]
    assert pkt.protocol == TransportProtocol.UDP
    assert pkt.src_port == 2222
    assert pkt.dst_port == 53
    assert pkt.tcp_flags is None


def test_normalize_pcap_extracts_icmp_fields(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _seed_pcap(root, "cap-3", [IP(src="10.0.0.1", dst="10.0.0.2") / ICMP()])

    result = normalize_pcap(root, "cap-3")

    assert len(result) == 1
    pkt = result[0]
    assert pkt.protocol == TransportProtocol.ICMP
    assert pkt.src_port is None
    assert pkt.dst_port is None
    assert pkt.tcp_flags is None


def test_normalize_pcap_skips_frames_without_ip_layer(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _seed_pcap(
        root,
        "cap-4",
        [Ether(), Ether() / IP(src="10.0.0.1", dst="10.0.0.2") / UDP(sport=1, dport=2)],
    )

    result = normalize_pcap(root, "cap-4")

    # The bare Ether() frame (no IP layer) cannot be normalized into this
    # schema and must be skipped, not fabricated -- only the real IP packet
    # survives. Its index still reflects its real position in the capture.
    assert len(result) == 1
    assert result[0].packet_id == "cap-4:1"


def test_normalize_pcap_packet_ids_reflect_real_capture_order(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _seed_pcap(
        root,
        "cap-5",
        [IP(src="10.0.0.1", dst="10.0.0.2") / TCP(sport=1000 + i, dport=80) for i in range(4)],
    )

    result = normalize_pcap(root, "cap-5")

    assert [p.packet_id for p in result] == ["cap-5:0", "cap-5:1", "cap-5:2", "cap-5:3"]


def test_normalize_pcap_writes_and_round_trips_through_jsonl(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _seed_pcap(root, "cap-6", [IP(src="10.0.0.1", dst="10.0.0.2") / TCP(sport=1, dport=2, flags="S")])

    result = normalize_pcap(root, "cap-6")

    stored = read_jsonl(packets_path(root, "cap-6"), Packet)
    assert stored == result
    assert stored[0].tcp_flags == "SYN"
