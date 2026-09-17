"""Phase 15 protocol wire-format tests.

Pure -- no Docker, no network -- covers the parts of simulator/traffic/protocols.py
that don't require a live target: DNS query construction/response parsing, and
the Postgres SSLRequest message format.
"""

from __future__ import annotations

import struct

from simulator.traffic.protocols import (
    _POSTGRES_SSL_REQUEST_CODE,
    build_dns_query,
    build_postgres_ssl_request,
    parse_dns_response,
)


def test_build_dns_query_has_correct_header_counts() -> None:
    packet, txid = build_dns_query("example.lab")
    assert len(packet) >= 12
    got_txid, flags, qdcount, ancount, nscount, arcount = struct.unpack("!HHHHHH", packet[:12])
    assert got_txid == txid
    assert qdcount == 1
    assert ancount == 0 and nscount == 0 and arcount == 0
    assert flags & 0x8000 == 0, "query must not have the QR (response) bit set"
    assert flags & 0x0100 != 0, "recursion-desired bit should be set"


def test_build_dns_query_encodes_qname_as_length_prefixed_labels() -> None:
    packet, _ = build_dns_query("example.lab")
    question = packet[12:]
    # "example" (7 bytes) then "lab" (3 bytes) then a zero terminator, then QTYPE/QCLASS.
    assert question[0] == 7
    assert question[1:8] == b"example"
    assert question[8] == 3
    assert question[9:12] == b"lab"
    assert question[12] == 0  # terminator
    qtype, qclass = struct.unpack("!HH", question[13:17])
    assert qtype == 1  # A record
    assert qclass == 1  # IN


def test_build_dns_query_txid_varies_across_calls() -> None:
    # Not a hard guarantee (random collisions are possible), but with 65536
    # possible values, 20 consecutive identical txids would indicate the
    # "random" transaction ID generation is actually broken/constant.
    txids = {build_dns_query("example.lab")[1] for _ in range(20)}
    assert len(txids) > 1


def test_parse_dns_response_success_case() -> None:
    txid = 0x1234
    flags = 0x8180  # QR=1, RD=1, RA=1, RCODE=0
    header = struct.pack("!HHHHHH", txid, flags, 1, 1, 0, 0)
    assert parse_dns_response(header, expected_txid=txid) == {
        "ok": True,
        "txid_matched": True,
        "rcode": 0,
        "answer_count": 1,
    }


def test_parse_dns_response_txid_mismatch_is_not_ok() -> None:
    header = struct.pack("!HHHHHH", 0xAAAA, 0x8180, 1, 1, 0, 0)
    result = parse_dns_response(header, expected_txid=0xBBBB)
    assert result["ok"] is False
    assert result["txid_matched"] is False


def test_parse_dns_response_nonzero_rcode_is_not_ok() -> None:
    txid = 0x5555
    flags = 0x8183  # RCODE=3 (NXDOMAIN)
    header = struct.pack("!HHHHHH", txid, flags, 1, 0, 0, 0)
    result = parse_dns_response(header, expected_txid=txid)
    assert result["ok"] is False
    assert result["rcode"] == 3


def test_parse_dns_response_too_short_is_rejected() -> None:
    result = parse_dns_response(b"\x00\x01", expected_txid=1)
    assert result["ok"] is False
    assert "error" in result


def test_postgres_ssl_request_matches_the_protocol_spec() -> None:
    # Independent check of the well-known Postgres SSLRequest magic number:
    # high 16 bits = 1234, low 16 bits = 5679 (documented in the Postgres
    # frontend/backend protocol spec), not merely re-deriving it from the
    # same constant the implementation uses.
    assert _POSTGRES_SSL_REQUEST_CODE == (1234 << 16) | 5679

    message = build_postgres_ssl_request()
    assert len(message) == 8
    length, code = struct.unpack("!II", message)
    assert length == 8
    assert code == _POSTGRES_SSL_REQUEST_CODE
