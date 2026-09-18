"""Phase 27 encrypted traffic metadata (TLS version extraction) unit tests
(pure, no Docker)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

from scapy.all import IP, TCP, Raw, wrpcap

from backend.nettrace.tls_metadata import _parse_server_hello_version, extract_tls_versions
from experiments.artifacts.paths import pcap_path


def _server_hello_record(
    legacy_version: Tuple[int, int], supported_version: Optional[Tuple[int, int]] = None
) -> bytes:
    random_bytes = bytes(32)
    session_id = b""
    cipher_suite = bytes([0x13, 0x01])
    compression_method = bytes([0x00])

    extensions = b""
    if supported_version is not None:
        ext_body = bytes(supported_version)
        extensions += bytes([0x00, 0x2B]) + len(ext_body).to_bytes(2, "big") + ext_body

    hello_body = (
        bytes(legacy_version)
        + random_bytes
        + bytes([len(session_id)])
        + session_id
        + cipher_suite
        + compression_method
        + len(extensions).to_bytes(2, "big")
        + extensions
    )
    handshake = bytes([0x02]) + len(hello_body).to_bytes(3, "big") + hello_body
    record = bytes([0x16, 0x03, 0x03]) + len(handshake).to_bytes(2, "big") + handshake
    return record


def _client_hello_record() -> bytes:
    random_bytes = bytes(32)
    hello_body = bytes([0x03, 0x03]) + random_bytes + bytes([0x00]) + bytes([0x00, 0x02, 0x13, 0x01])
    handshake = bytes([0x01]) + len(hello_body).to_bytes(3, "big") + hello_body
    record = bytes([0x16, 0x03, 0x01]) + len(handshake).to_bytes(2, "big") + handshake
    return record


def test_parse_server_hello_version_tls_1_0() -> None:
    record = _server_hello_record(legacy_version=(3, 1))
    assert _parse_server_hello_version(record) == "TLS 1.0"


def test_parse_server_hello_version_tls_1_1() -> None:
    record = _server_hello_record(legacy_version=(3, 2))
    assert _parse_server_hello_version(record) == "TLS 1.1"


def test_parse_server_hello_version_tls_1_2() -> None:
    record = _server_hello_record(legacy_version=(3, 3))
    assert _parse_server_hello_version(record) == "TLS 1.2"


def test_parse_server_hello_version_tls_1_3_via_supported_versions_extension() -> None:
    # Legacy version stays pinned at 0x0303 ("TLS 1.2") for compatibility --
    # the real negotiated version only shows up in the extension.
    record = _server_hello_record(legacy_version=(3, 3), supported_version=(3, 4))
    assert _parse_server_hello_version(record) == "TLS 1.3"


def test_parse_server_hello_version_non_handshake_record_returns_none() -> None:
    # Content type 0x17 = Application Data, not Handshake.
    record = bytes([0x17, 0x03, 0x03, 0x00, 0x05]) + b"\x00" * 5
    assert _parse_server_hello_version(record) is None


def test_parse_server_hello_version_client_hello_returns_none() -> None:
    assert _parse_server_hello_version(_client_hello_record()) is None


def test_parse_server_hello_version_truncated_record_returns_none() -> None:
    record = _server_hello_record(legacy_version=(3, 3))
    assert _parse_server_hello_version(record[:10]) is None


def test_parse_server_hello_version_too_short_payload_returns_none() -> None:
    assert _parse_server_hello_version(b"\x16\x03") is None


def test_extract_tls_versions_real_pcap(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    record = _server_hello_record(legacy_version=(3, 3), supported_version=(3, 4))
    pkt = IP(src="10.0.0.2", dst="10.0.0.1") / TCP(sport=443, dport=51000) / Raw(load=record)

    path = pcap_path(root, "cap-1")
    path.parent.mkdir(parents=True, exist_ok=True)
    wrpcap(str(path), [pkt])

    versions = extract_tls_versions(root, "cap-1")

    assert versions == {("10.0.0.2", 443): "TLS 1.3"}
