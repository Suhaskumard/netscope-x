"""Phase 21 PCAP ingestion unit tests (pure, no Docker/live capture)."""

from __future__ import annotations

from pathlib import Path

import pytest
from scapy.all import IP, TCP, wrpcap

from backend.nettrace.capture.authorized_interfaces import is_authorized_interface
from backend.nettrace.capture.errors import InvalidPcapError
from backend.nettrace.capture.ingest import ingest_pcap, validate_pcap_bytes, validate_pcap_file
from experiments.artifacts.io import read_json
from experiments.artifacts.paths import capture_manifest_path, pcap_path


def _real_pcap_bytes(tmp_path: Path, count: int = 5) -> bytes:
    path = tmp_path / "seed.pcap"
    packets = [IP(src="10.0.0.1", dst="10.0.0.2") / TCP(sport=1000 + i, dport=80) for i in range(count)]
    wrpcap(str(path), packets)
    return path.read_bytes()


def test_validate_pcap_bytes_accepts_real_capture(tmp_path: Path) -> None:
    assert validate_pcap_bytes(_real_pcap_bytes(tmp_path, count=4)) == 4


def test_validate_pcap_bytes_rejects_empty() -> None:
    with pytest.raises(InvalidPcapError, match="empty"):
        validate_pcap_bytes(b"")


def test_validate_pcap_bytes_rejects_garbage() -> None:
    with pytest.raises(InvalidPcapError, match="not a valid pcap"):
        validate_pcap_bytes(b"this is definitely not a pcap file")


def test_validate_pcap_bytes_rejects_zero_packets(tmp_path: Path) -> None:
    path = tmp_path / "zero.pcap"
    wrpcap(str(path), [])
    with pytest.raises(InvalidPcapError, match="zero packets"):
        validate_pcap_bytes(path.read_bytes())


def test_validate_pcap_file_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(InvalidPcapError, match="does not exist"):
        validate_pcap_file(tmp_path / "missing.pcap")


def test_ingest_pcap_writes_canonical_layout_and_manifest(tmp_path: Path) -> None:
    upload_dir = tmp_path / "inbox"
    upload_dir.mkdir()
    source_path = upload_dir / "capture.pcap"
    source_path.write_bytes(_real_pcap_bytes(tmp_path, count=7))

    root = tmp_path / "artifacts"
    manifest = ingest_pcap(
        source_path, root, "cap-1", source="pcap_upload", original_filename="capture.pcap"
    )

    assert manifest.capture_id == "cap-1"
    assert manifest.packet_count == 7
    assert manifest.original_filename == "capture.pcap"
    assert manifest.interface is None

    raw = pcap_path(root, "cap-1")
    assert raw.is_file()
    assert raw.read_bytes() == source_path.read_bytes()

    stored_manifest = read_json(capture_manifest_path(root, "cap-1"), type(manifest))
    assert stored_manifest == manifest


def test_ingest_pcap_rejects_invalid_source(tmp_path: Path) -> None:
    bad_path = tmp_path / "bad.pcap"
    bad_path.write_bytes(b"nope")
    with pytest.raises(InvalidPcapError):
        ingest_pcap(bad_path, tmp_path / "artifacts", "cap-2")


def test_authorized_interfaces_default_allows_eth0() -> None:
    assert is_authorized_interface("eth0") is True


def test_authorized_interfaces_rejects_unlisted_interface() -> None:
    assert is_authorized_interface("eth99") is False
    assert is_authorized_interface("wlan0") is False
