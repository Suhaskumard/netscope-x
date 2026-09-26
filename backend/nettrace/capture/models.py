"""Capture data contracts (spec Phase 21).

Deliberately separate from `backend.app.models` (Phase 04): a `CaptureManifest`
is ingestion metadata about a `raw.pcap` artifact, not a cross-pipeline domain
object every module needs -- only `backend.nettrace.capture` and its callers
touch it. It also isn't ground truth, so it is written with the plain
`write_json`/`read_json` helpers (`experiments/artifacts/io.py`), not the
hashed `write_ground_truth` pair reserved for actual ground-truth artifacts.

Error types (`InvalidPcapError`, `UnauthorizedInterfaceError`) live in the
dependency-free sibling module `backend.nettrace.capture.errors`, not here,
so that `simulator/capture/live.py` can raise/catch them inside a lab
container without needing Pydantic installed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class CaptureManifest(BaseModel):
    """Ingestion record for one `captures/<capture_id>/raw.pcap` artifact."""

    capture_id: str
    source: Literal["pcap_upload", "live_interface", "flow_export"]
    original_filename: Optional[str] = Field(
        default=None, description="Set when source == pcap_upload."
    )
    interface: Optional[str] = Field(
        default=None, description="Set when source == live_interface."
    )
    packet_count: int = Field(..., ge=0)
    size_bytes: int = Field(..., ge=0)
    ingested_at: datetime

    model_config = {"frozen": True}
