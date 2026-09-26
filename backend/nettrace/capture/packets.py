"""Resolve a capture's normalized packets regardless of its source (spec Phase 95)."""

from __future__ import annotations

from pathlib import Path

from backend.nettrace.capture.errors import CaptureNotFoundError
from backend.nettrace.normalize import normalize_pcap
from experiments.artifacts.paths import flowexport_path, packets_path, pcap_path


def ensure_packets(root: Path, capture_id: str) -> None:
    """A raw.pcap is normalized (Phase 22); a flow export already had its packets written at ingest."""
    if pcap_path(root, capture_id).is_file():
        normalize_pcap(root, capture_id)
    elif flowexport_path(root, capture_id).is_file() and packets_path(root, capture_id).is_file():
        return
    else:
        raise CaptureNotFoundError(f"no ingested capture found for capture_id={capture_id!r}")
