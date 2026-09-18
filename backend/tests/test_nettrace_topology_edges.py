"""Phase 30-31 edge discovery + probabilistic edge confidence unit tests (pure, no Docker)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from scapy.all import IP, TCP, Raw, wrpcap

from backend.app.models.flow import Flow, FlowFeatures, TCPState
from backend.app.models.packet import Packet, PacketDirection, TransportProtocol
from backend.nettrace.reconstruct import reconstruct_flows
from backend.nettrace.topology.discovery import discover_nodes
from backend.nettrace.topology.edges import _confidence, discover_edges
from experiments.artifacts.io import write_jsonl
from experiments.artifacts.paths import packets_path, pcap_path

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


def _server_hello_record(legacy_version=(3, 3), supported_version=None) -> bytes:
    """Minimal crafted TLS ServerHello record, mirroring
    test_nettrace_reconstruct.py's own helper of the same name."""
    random_bytes = bytes(32)
    cipher_suite = bytes([0x13, 0x01])
    compression_method = bytes([0x00])

    extensions = b""
    if supported_version is not None:
        ext_body = bytes(supported_version)
        extensions += bytes([0x00, 0x2B]) + len(ext_body).to_bytes(2, "big") + ext_body

    hello_body = (
        bytes(legacy_version)
        + random_bytes
        + bytes([0])
        + cipher_suite
        + compression_method
        + len(extensions).to_bytes(2, "big")
        + extensions
    )
    handshake = bytes([0x02]) + len(hello_body).to_bytes(3, "big") + hello_body
    return bytes([0x16, 0x03, 0x03]) + len(handshake).to_bytes(2, "big") + handshake


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


def _flow(
    flow_id="f0",
    packet_count=1,
    forward_byte_ratio=0.5,
    tcp_state=None,
    fingerprinted_protocol=None,
    tls_version=None,
    is_persistent=False,
    protocol=TransportProtocol.TCP,
) -> Flow:
    """Directly constructs a Flow for unit-testing _confidence's pure math in
    isolation, bypassing the packet->flow pipeline entirely."""
    return Flow(
        flow_id=flow_id,
        capture_id="cap-1",
        src_ip="10.0.0.1",
        dst_ip="10.0.0.2",
        src_port=1000,
        dst_port=9999,
        protocol=protocol,
        first_seen=BASE,
        last_seen=BASE + timedelta(seconds=1),
        tcp_state=tcp_state,
        fingerprinted_protocol=fingerprinted_protocol,
        tls_version=tls_version,
        features=FlowFeatures(
            packet_count=packet_count,
            byte_count=packet_count * 100,
            duration_seconds=1.0,
            burstiness=0.0,
            mean_inter_arrival_seconds=0.1,
            forward_byte_ratio=forward_byte_ratio,
            destination_diversity=1,
            port_diversity=1,
            is_persistent=is_persistent,
        ),
    )


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
    assert len(edge.evidence) == 3  # 2 per-flow lines + 1 bucket-level confidence-signal summary
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


def test_discover_edges_confidence_higher_with_established_handshake_than_partial(tmp_path: Path) -> None:
    # Equal packet_count (3) and equal forward_byte_ratio in both fixtures -- the only
    # difference is whether the third packet completes the handshake (ACK) or is a
    # retransmitted SYN (still PARTIAL), isolating the established-handshake signal.
    partial_root = tmp_path / "partial"
    partial_packets = [
        _pkt("p0", BASE, "10.0.0.1", 1000, "10.0.0.2", 9999, TransportProtocol.TCP, flags="SYN"),
        _pkt(
            "p1",
            BASE + timedelta(milliseconds=10),
            "10.0.0.2",
            9999,
            "10.0.0.1",
            1000,
            TransportProtocol.TCP,
            flags="SYN,ACK",
        ),
        _pkt(
            "p2",
            BASE + timedelta(milliseconds=20),
            "10.0.0.1",
            1000,
            "10.0.0.2",
            9999,
            TransportProtocol.TCP,
            flags="SYN",
        ),
    ]
    _, partial_edges = _prepare(partial_root, "cap-1", partial_packets)

    established_root = tmp_path / "established"
    established_packets = [
        _pkt("p0", BASE, "10.0.0.1", 1000, "10.0.0.2", 9999, TransportProtocol.TCP, flags="SYN"),
        _pkt(
            "p1",
            BASE + timedelta(milliseconds=10),
            "10.0.0.2",
            9999,
            "10.0.0.1",
            1000,
            TransportProtocol.TCP,
            flags="SYN,ACK",
        ),
        _pkt(
            "p2",
            BASE + timedelta(milliseconds=20),
            "10.0.0.1",
            1000,
            "10.0.0.2",
            9999,
            TransportProtocol.TCP,
            flags="ACK",
        ),
    ]
    _, established_edges = _prepare(established_root, "cap-1", established_packets)

    assert len(partial_edges) == 1
    assert len(established_edges) == 1
    assert partial_edges[0].observation_count == established_edges[0].observation_count == 1
    assert established_edges[0].confidence > partial_edges[0].confidence


def test_discover_edges_confidence_higher_with_tls_negotiated(tmp_path: Path) -> None:
    # Identical, already-established TCP handshake in both fixtures; only difference
    # is whether a real ServerHello is present in raw.pcap for the capture.
    packets = [
        _pkt("p0", BASE, "10.0.0.1", 51000, "10.0.0.2", 9999, TransportProtocol.TCP, flags="SYN"),
        _pkt(
            "p1",
            BASE + timedelta(milliseconds=10),
            "10.0.0.2",
            9999,
            "10.0.0.1",
            51000,
            TransportProtocol.TCP,
            flags="SYN,ACK",
        ),
        _pkt(
            "p2",
            BASE + timedelta(milliseconds=20),
            "10.0.0.1",
            51000,
            "10.0.0.2",
            9999,
            TransportProtocol.TCP,
            flags="ACK",
        ),
    ]

    no_tls_root = tmp_path / "no_tls"
    _, no_tls_edges = _prepare(no_tls_root, "cap-1", packets)

    tls_root = tmp_path / "tls"
    _seed(tls_root, "cap-1", packets)
    record = _server_hello_record(legacy_version=(3, 3), supported_version=(3, 4))
    scapy_pkt = IP(src="10.0.0.2", dst="10.0.0.1") / TCP(sport=9999, dport=51000) / Raw(load=record)
    path = pcap_path(tls_root, "cap-1")
    path.parent.mkdir(parents=True, exist_ok=True)
    wrpcap(str(path), [scapy_pkt])
    reconstruct_flows(tls_root, "cap-1")
    tls_nodes = discover_nodes(tls_root, "cap-1")
    tls_edges = discover_edges(tls_root, "cap-1", tls_nodes)

    assert len(no_tls_edges) == 1
    assert len(tls_edges) == 1
    assert tls_edges[0].confidence > no_tls_edges[0].confidence
    assert any("tls_version=TLS 1.3" in line for line in tls_edges[0].evidence)


def test_discover_edges_confidence_higher_with_fingerprinted_protocol(tmp_path: Path) -> None:
    # Equal packet_count (2), equal forward_byte_ratio (0.5), equal (PARTIAL) tcp_state;
    # only the destination port differs -- one is in the fingerprint table (80 -> http),
    # the other is not (9999).
    unfingerprinted_root = tmp_path / "unfingerprinted"
    unfingerprinted_packets = [
        _pkt("p0", BASE, "10.0.0.1", 1000, "10.0.0.2", 9999, TransportProtocol.TCP),
        _pkt("p1", BASE + timedelta(milliseconds=10), "10.0.0.2", 9999, "10.0.0.1", 1000, TransportProtocol.TCP),
    ]
    _, unfingerprinted_edges = _prepare(unfingerprinted_root, "cap-1", unfingerprinted_packets)

    fingerprinted_root = tmp_path / "fingerprinted"
    fingerprinted_packets = [
        _pkt("p0", BASE, "10.0.0.1", 1000, "10.0.0.2", 80, TransportProtocol.TCP),
        _pkt("p1", BASE + timedelta(milliseconds=10), "10.0.0.2", 80, "10.0.0.1", 1000, TransportProtocol.TCP),
    ]
    _, fingerprinted_edges = _prepare(fingerprinted_root, "cap-1", fingerprinted_packets)

    assert len(unfingerprinted_edges) == 1
    assert len(fingerprinted_edges) == 1
    assert fingerprinted_edges[0].confidence > unfingerprinted_edges[0].confidence


def test_discover_edges_confidence_higher_with_bidirectional_traffic(tmp_path: Path) -> None:
    # Equal packet_count (2) UDP flows, avoiding port 53 to keep fingerprinting out of
    # the comparison; only whether both packets travel the same direction differs.
    one_way_root = tmp_path / "one_way"
    one_way_packets = [
        _pkt("p0", BASE, "10.0.0.1", 2000, "10.0.0.2", 9999, TransportProtocol.UDP),
        _pkt("p1", BASE + timedelta(milliseconds=10), "10.0.0.1", 2000, "10.0.0.2", 9999, TransportProtocol.UDP),
    ]
    _, one_way_edges = _prepare(one_way_root, "cap-1", one_way_packets)

    bidirectional_root = tmp_path / "bidirectional"
    bidirectional_packets = [
        _pkt("p0", BASE, "10.0.0.1", 2000, "10.0.0.2", 9999, TransportProtocol.UDP),
        _pkt("p1", BASE + timedelta(milliseconds=10), "10.0.0.2", 9999, "10.0.0.1", 2000, TransportProtocol.UDP),
    ]
    _, bidirectional_edges = _prepare(bidirectional_root, "cap-1", bidirectional_packets)

    assert len(one_way_edges) == 1
    assert len(bidirectional_edges) == 1
    assert bidirectional_edges[0].confidence > one_way_edges[0].confidence


def test_discover_edges_confidence_monotonic_with_combined_signals() -> None:
    """Pure math test of _confidence: adding one signal at a time never decreases
    confidence, generalizing Phase 30's packet-only monotonicity property."""
    scale, strength = 20.0, 0.3

    c0 = _confidence([_flow(packet_count=2, forward_byte_ratio=1.0)], scale, strength)
    c1 = _confidence([_flow(packet_count=10, forward_byte_ratio=1.0)], scale, strength)
    assert c1 >= c0

    c2 = _confidence(
        [_flow(packet_count=10, forward_byte_ratio=1.0, tcp_state=TCPState.ESTABLISHED)], scale, strength
    )
    assert c2 >= c1

    c3 = _confidence(
        [
            _flow(
                packet_count=10,
                forward_byte_ratio=1.0,
                tcp_state=TCPState.ESTABLISHED,
                fingerprinted_protocol="http",
            )
        ],
        scale,
        strength,
    )
    assert c3 >= c2

    c4 = _confidence(
        [
            _flow(
                packet_count=10,
                forward_byte_ratio=1.0,
                tcp_state=TCPState.ESTABLISHED,
                fingerprinted_protocol="http",
                tls_version="TLS 1.3",
            )
        ],
        scale,
        strength,
    )
    assert c4 >= c3

    c5 = _confidence(
        [
            _flow(
                packet_count=10,
                forward_byte_ratio=1.0,
                tcp_state=TCPState.ESTABLISHED,
                fingerprinted_protocol="http",
                tls_version="TLS 1.3",
                is_persistent=True,
            )
        ],
        scale,
        strength,
    )
    assert c5 >= c4

    c6 = _confidence(
        [
            _flow(
                packet_count=10,
                forward_byte_ratio=0.5,
                tcp_state=TCPState.ESTABLISHED,
                fingerprinted_protocol="http",
                tls_version="TLS 1.3",
                is_persistent=True,
            )
        ],
        scale,
        strength,
    )
    assert c6 >= c5
    assert c6 > c0


def test_discover_edges_all_positive_signals_exceeds_packet_volume_alone() -> None:
    scale, strength = 20.0, 0.3
    packet_only = _confidence([_flow(packet_count=10, forward_byte_ratio=1.0)], scale, strength)
    all_signals = _confidence(
        [
            _flow(
                packet_count=10,
                forward_byte_ratio=0.5,
                tcp_state=TCPState.ESTABLISHED,
                fingerprinted_protocol="http",
                tls_version="TLS 1.3",
                is_persistent=True,
            )
        ],
        scale,
        strength,
    )
    assert all_signals > packet_only
    assert all_signals - packet_only > 0.1


def test_discover_edges_udp_only_edge_has_no_tcp_signals_but_confidence_still_sensible() -> None:
    """A UDP-only bucket structurally can never have tcp_state/tls_version signals
    (both None by construction for UDP flows). Confirms this contributes no penalty
    (identity factor, not a zeroed-out one) and confidence can still climb via the
    signals that ARE applicable (fingerprint, persistence, bidirectionality)."""
    scale, strength = 20.0, 0.3
    plain_udp = _confidence(
        [_flow(packet_count=20, forward_byte_ratio=1.0, protocol=TransportProtocol.UDP)], scale, strength
    )
    rich_udp = _confidence(
        [
            _flow(
                packet_count=20,
                forward_byte_ratio=0.5,
                protocol=TransportProtocol.UDP,
                fingerprinted_protocol="dns",
                is_persistent=True,
            )
        ],
        scale,
        strength,
    )
    assert rich_udp > plain_udp
    assert rich_udp > 0.8


def test_discover_edges_evidence_summary_line_present_and_reflects_signals(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    packets = [
        _pkt("p0", BASE, "10.0.0.1", 1000, "10.0.0.2", 80, TransportProtocol.TCP),
        _pkt("p1", BASE + timedelta(milliseconds=10), "10.0.0.2", 80, "10.0.0.1", 1000, TransportProtocol.TCP),
    ]
    _, edges = _prepare(root, "cap-1", packets)

    assert len(edges) == 1
    summary = edges[0].evidence[-1]
    assert summary.startswith("confidence signals:")
    assert "fingerprinted_protocol=yes" in summary
    assert f"confidence={edges[0].confidence:.3f}" in summary
