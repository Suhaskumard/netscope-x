"""Protocol-diverse traffic senders (spec Phase 15): TCP, UDP, DNS, HTTP,
TLS metadata, database, cache. Stdlib-only, no new dependency -- each
sender does a real wire-level exchange and returns real observed
metadata, never a synthetic/fabricated result.

Split into pure wire-format helpers (unit-testable without a network --
see simulator/tests/test_protocols.py) and the I/O-performing senders
that use them.
"""

from __future__ import annotations

import random
import socket
import ssl
import struct
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

# ---------------------------------------------------------------- DNS (UDP) --

# RFC 1035 header: ID, FLAGS, QDCOUNT, ANCOUNT, NSCOUNT, ARCOUNT (6 x uint16).
_DNS_HEADER_FORMAT = "!HHHHHH"
_DNS_STANDARD_QUERY_RD_FLAG = 0x0100  # opcode=QUERY, recursion desired
_DNS_QTYPE_A = 1
_DNS_QCLASS_IN = 1


def _encode_dns_qname(name: str) -> bytes:
    """Encodes a domain name as length-prefixed labels terminated by a zero byte."""
    labels = [label for label in name.strip(".").split(".") if label]
    return b"".join(struct.pack("B", len(label)) + label.encode("ascii") for label in labels) + b"\x00"


def build_dns_query(name: str, qtype: int = _DNS_QTYPE_A) -> tuple[bytes, int]:
    """Builds a real DNS query packet (RFC 1035 wire format). Returns (packet, transaction_id)."""
    txid = random.randint(0, 0xFFFF)
    header = struct.pack(_DNS_HEADER_FORMAT, txid, _DNS_STANDARD_QUERY_RD_FLAG, 1, 0, 0, 0)
    question = _encode_dns_qname(name) + struct.pack("!HH", qtype, _DNS_QCLASS_IN)
    return header + question, txid


def parse_dns_response(data: bytes, expected_txid: int) -> Dict[str, Any]:
    """Parses just the DNS header of a response (sufficient to confirm a real, matching answer)."""
    if len(data) < 12:
        return {"ok": False, "error": "response shorter than a DNS header"}
    txid, flags, qdcount, ancount, nscount, arcount = struct.unpack(_DNS_HEADER_FORMAT, data[:12])
    rcode = flags & 0x000F
    txid_matched = txid == expected_txid
    return {
        "ok": txid_matched and rcode == 0,
        "txid_matched": txid_matched,
        "rcode": rcode,
        "answer_count": ancount,
    }


def dns_query(name: str, server: str, port: int = 53, timeout: float = 3.0) -> Dict[str, Any]:
    query, txid = build_dns_query(name)
    start = time.perf_counter()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(timeout)
            sock.sendto(query, (server, port))
            data, _ = sock.recvfrom(512)
        result = parse_dns_response(data, txid)
    except OSError as exc:
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    result["latency_ms"] = (time.perf_counter() - start) * 1000.0
    return result


# ------------------------------------------------------------- generic TCP --


def tcp_raw_connect(host: str, port: int, timeout: float = 3.0) -> Dict[str, Any]:
    """A bare TCP connect/close with no higher-layer protocol on top -- represents
    generic/unclassified TCP traffic, distinct from any of the named application
    protocols below."""
    start = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
        result: Dict[str, Any] = {"ok": True}
    except OSError as exc:
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    result["latency_ms"] = (time.perf_counter() - start) * 1000.0
    return result


# ------------------------------------------------------------------- HTTP --


def http_get(url: str, timeout: float = 5.0) -> Dict[str, Any]:
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 (lab-internal target only)
            result: Dict[str, Any] = {"ok": True, "status_code": resp.status}
    except urllib.error.HTTPError as exc:
        result = {"ok": False, "status_code": exc.code}
    except Exception as exc:  # noqa: BLE001 -- record any failure, never crash the run
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    result["latency_ms"] = (time.perf_counter() - start) * 1000.0
    return result


# --------------------------------------------------------------- cache (Redis) --


def redis_ping(host: str, port: int = 6379, timeout: float = 3.0) -> Dict[str, Any]:
    """Raw RESP-protocol PING, no redis client library needed."""
    start = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.sendall(b"PING\r\n")
            response = sock.recv(64)
        result: Dict[str, Any] = {
            "ok": response.startswith(b"+PONG"),
            "raw_response": response.decode("ascii", errors="replace").strip(),
        }
    except OSError as exc:
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    result["latency_ms"] = (time.perf_counter() - start) * 1000.0
    return result


# ---------------------------------------------------------- database (Postgres) --

# Postgres wire protocol SSLRequest: 8-byte message, length=8 then the fixed
# "magic" request code 80877103 (= 1234 << 16 | 5679, a well-known constant
# from the Postgres frontend/backend protocol spec, verified independently
# in simulator/tests/test_protocols.py).
_POSTGRES_SSL_REQUEST_CODE = 80877103


def build_postgres_ssl_request() -> bytes:
    return struct.pack("!II", 8, _POSTGRES_SSL_REQUEST_CODE)


def postgres_ssl_request(host: str, port: int = 5432, timeout: float = 3.0) -> Dict[str, Any]:
    """Sends a real Postgres SSLRequest and reads the server's real single-byte
    'S' (SSL supported) / 'N' (not supported) response -- no database driver or
    authentication needed to observe genuine protocol-level behavior."""
    message = build_postgres_ssl_request()
    start = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.sendall(message)
            response = sock.recv(1)
        response_byte: Optional[str] = response.decode("ascii", errors="replace") if response else None
        result: Dict[str, Any] = {"ok": response_byte in ("S", "N"), "response_byte": response_byte}
    except OSError as exc:
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    result["latency_ms"] = (time.perf_counter() - start) * 1000.0
    return result


# ------------------------------------------------------------- TLS metadata --


def tls_handshake(host: str, port: int = 443, timeout: float = 3.0) -> Dict[str, Any]:
    """Performs a real TLS handshake and reports the actually negotiated version
    and cipher -- metadata only, never payload decryption, consistent with
    docs/research/problem_definition.md's observability model.

    verify_mode=CERT_NONE is used because the lab target's certificate is a
    self-signed, lab-only certificate generated at container startup (see
    simulator/docker/external/). This is explicitly a lab-only relaxation,
    never a pattern to use against a real target.
    """
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    start = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout) as raw_sock:
            with ctx.wrap_socket(raw_sock, server_hostname=host) as tls_sock:
                version = tls_sock.version()
                cipher = tls_sock.cipher()
        result: Dict[str, Any] = {
            "ok": True,
            "tls_version": version,
            "cipher": cipher[0] if cipher else None,
        }
    except (OSError, ssl.SSLError) as exc:
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    result["latency_ms"] = (time.perf_counter() - start) * 1000.0
    return result
