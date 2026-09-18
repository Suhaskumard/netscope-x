"""PCAP ingestion (spec Phase 21, FR-1.1).

Pure, host/lab-agnostic logic: given bytes (or a path) that are supposed to
be a PCAP/PCAPNG file, validate them with Scapy and persist them at the
canonical `experiments/artifacts` location (`captures/<capture_id>/raw.pcap`,
Phase 10), alongside a `CaptureManifest` (`manifest.json`, plain
`write_json` -- not ground truth). This module never opens a live socket;
"controlled live capture" (spec Phase 21's other requirement) is real,
lab-side Scapy `sniff()` mechanics in `simulator/capture/live.py`, whose
output pcap is ingested through this same code path.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from scapy.utils import PcapReader

from backend.nettrace.capture.errors import InvalidPcapError
from backend.nettrace.capture.models import CaptureManifest
from experiments.artifacts.io import write_json
from experiments.artifacts.paths import capture_manifest_path, pcap_path


def validate_pcap_bytes(data: bytes) -> int:
    """Validates `data` as a non-empty PCAP/PCAPNG capture and returns its
    packet count. Raises InvalidPcapError otherwise."""
    if len(data) == 0:
        raise InvalidPcapError("pcap file is empty")

    packet_count = 0
    try:
        with PcapReader(io.BytesIO(data)) as reader:  # type: ignore[arg-type]
            for _ in reader:
                packet_count += 1
    except Exception as exc:  # Scapy raises plain Exception/Scapy_Exception on bad magic/truncation
        raise InvalidPcapError(f"not a valid pcap file: {exc}") from exc

    if packet_count == 0:
        raise InvalidPcapError("pcap file contains zero packets")
    return packet_count


def validate_pcap_file(path: Path) -> int:
    """Validates a PCAP file on disk. See validate_pcap_bytes."""
    if not path.is_file():
        raise InvalidPcapError(f"pcap file does not exist: {path}")
    return validate_pcap_bytes(path.read_bytes())


def ingest_pcap(
    source_path: Path,
    root: Path,
    capture_id: str,
    *,
    source: Literal["pcap_upload", "live_interface"] = "pcap_upload",
    original_filename: Optional[str] = None,
    interface: Optional[str] = None,
) -> CaptureManifest:
    """Validates `source_path` as a real pcap, copies it to the canonical
    `captures/<capture_id>/raw.pcap` location, and writes a CaptureManifest.

    Used both for `POST /capture` with source=pcap_upload, and for ingesting
    a real pcap produced by `simulator/capture/live.py`'s controlled live
    capture (source=live_interface).
    """
    data = source_path.read_bytes()
    packet_count = validate_pcap_bytes(data)

    destination = pcap_path(root, capture_id)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)

    manifest = CaptureManifest(
        capture_id=capture_id,
        source=source,
        original_filename=original_filename,
        interface=interface,
        packet_count=packet_count,
        size_bytes=len(data),
        ingested_at=datetime.now(timezone.utc),
    )
    write_json(capture_manifest_path(root, capture_id), manifest)
    return manifest
