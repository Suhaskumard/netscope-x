"""Phase 26 protocol fingerprinting unit tests (pure, no Docker)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.app.models.packet import Packet, PacketDirection, TransportProtocol
from backend.nettrace.fingerprint import fingerprint_protocol
from backend.nettrace.reconstruct import reconstruct_flows
from experiments.artifacts.io import write_jsonl
from experiments.artifacts.paths import packets_path

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


def test_fingerprint_protocol_recognizes_http() -> None:
    assert fingerprint_protocol(TransportProtocol.TCP, 51000, 80) == "http"


def test_fingerprint_protocol_recognizes_tls() -> None:
    assert fingerprint_protocol(TransportProtocol.TCP, 51000, 443) == "tls"


def test_fingerprint_protocol_recognizes_postgresql() -> None:
    assert fingerprint_protocol(TransportProtocol.TCP, 51000, 5432) == "postgresql"


def test_fingerprint_protocol_recognizes_redis() -> None:
    assert fingerprint_protocol(TransportProtocol.TCP, 51000, 6379) == "redis"


def test_fingerprint_protocol_recognizes_dns() -> None:
    assert fingerprint_protocol(TransportProtocol.UDP, 51000, 53) == "dns"


def test_fingerprint_protocol_unrecognized_port_returns_none() -> None:
    assert fingerprint_protocol(TransportProtocol.TCP, 51000, 9999) is None


def test_fingerprint_protocol_falls_back_to_src_port() -> None:
    # Reversed canonical orientation: the well-known port is on src_port,
    # not dst_port (e.g. the server was the first-observed packet's sender).
    assert fingerprint_protocol(TransportProtocol.TCP, 80, 51000) == "http"


def test_fingerprint_protocol_dst_port_takes_priority_over_src_port() -> None:
    assert fingerprint_protocol(TransportProtocol.TCP, 443, 80) == "http"


def test_fingerprint_protocol_both_ports_none_returns_none() -> None:
    assert fingerprint_protocol(TransportProtocol.ICMP, None, None) is None


def test_fingerprint_protocol_wrong_transport_for_port_returns_none() -> None:
    # Port 53 is only recognized as DNS over UDP, not TCP.
    assert fingerprint_protocol(TransportProtocol.TCP, 51000, 53) is None


def test_reconstruct_flows_real_http_flow_is_fingerprinted(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    packets = [
        _pkt("p0", BASE, "10.0.0.1", 51000, "10.0.0.2", 80, TransportProtocol.TCP, flags="SYN"),
        _pkt("p1", BASE + timedelta(milliseconds=10), "10.0.0.2", 80, "10.0.0.1", 51000, TransportProtocol.TCP, flags="SYN,ACK"),
    ]
    _seed_packets(root, "cap-1", packets)

    flows = reconstruct_flows(root, "cap-1")

    assert flows[0].fingerprinted_protocol == "http"


def test_reconstruct_flows_real_dns_session_is_fingerprinted(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    packets = [
        _pkt("p0", BASE, "10.0.0.1", 51000, "10.0.0.2", 53, TransportProtocol.UDP),
        _pkt("p1", BASE + timedelta(milliseconds=10), "10.0.0.2", 53, "10.0.0.1", 51000, TransportProtocol.UDP),
    ]
    _seed_packets(root, "cap-1", packets)

    flows = reconstruct_flows(root, "cap-1")

    assert flows[0].fingerprinted_protocol == "dns"


def test_reconstruct_flows_unrecognized_port_stays_none(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    packets = [
        _pkt("p0", BASE, "10.0.0.1", 51000, "10.0.0.2", 9999, TransportProtocol.TCP, flags="SYN"),
        _pkt("p1", BASE + timedelta(milliseconds=10), "10.0.0.2", 9999, "10.0.0.1", 51000, TransportProtocol.TCP, flags="SYN,ACK"),
    ]
    _seed_packets(root, "cap-1", packets)

    flows = reconstruct_flows(root, "cap-1")

    assert flows[0].fingerprinted_protocol is None
