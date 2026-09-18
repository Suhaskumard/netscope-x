"""POST /capture. Backing implementation: spec Phase 21 (High-Fidelity Packet Capture).

`source=pcap_upload` is fully real this phase: the named file is read from
the configured upload staging directory, validated as a real pcap via
Scapy, and ingested into `experiments/artifacts`' canonical
`captures/<capture_id>/raw.pcap` layout (`backend.nettrace.capture.ingest`).

`source=live_interface` validates the requested interface against the
authorized allowlist (spec §5 Safety Boundary) and returns 202 describing
the real lab-side workflow: the backend's FastAPI process runs in a
separate Docker Compose project with no network path into the lab, so it
cannot itself open a socket on a lab interface. Actual sniffing is a real,
verified `simulator/capture/live.py` run inside the lab's `client`
container (see docs/architecture/packet_capture.md); its output pcap is
then ingested through this same endpoint as source=pcap_upload.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field, model_validator

from backend.app.core.config import get_settings
from backend.nettrace.capture.authorized_interfaces import is_authorized_interface
from backend.nettrace.capture.errors import InvalidPcapError, UnauthorizedInterfaceError
from backend.nettrace.capture.ingest import ingest_pcap

router = APIRouter(prefix="/capture", tags=["capture"])


class CaptureRequest(BaseModel):
    source: Literal["pcap_upload", "live_interface"]
    pcap_filename: Optional[str] = Field(
        default=None, description="Required when source == pcap_upload."
    )
    interface: Optional[str] = Field(
        default=None,
        description="Required when source == live_interface; must be an authorized lab interface (spec §5).",
    )

    @model_validator(mode="after")
    def _required_field_for_source(self) -> "CaptureRequest":
        if self.source == "pcap_upload":
            if not self.pcap_filename:
                raise ValueError("pcap_filename is required when source == pcap_upload")
            # Must be a bare filename -- no directory components -- so it can
            # never escape upload_staging_dir (e.g. "../../etc/passwd").
            if self.pcap_filename != Path(self.pcap_filename).name:
                raise ValueError("pcap_filename must not contain a path")
        if self.source == "live_interface" and not self.interface:
            raise ValueError("interface is required when source == live_interface")
        return self


class CaptureAccepted(BaseModel):
    capture_id: str
    status: Literal["accepted"]
    packet_count: Optional[int] = Field(
        default=None, description="Set when source == pcap_upload: packets ingested."
    )
    note: Optional[str] = Field(
        default=None, description="Set when source == live_interface: how to complete the capture."
    )


@router.post("", response_model=CaptureAccepted, status_code=202)
def start_capture(request: CaptureRequest) -> CaptureAccepted:
    settings = get_settings()
    capture_id = str(uuid.uuid4())

    if request.source == "pcap_upload":
        assert request.pcap_filename is not None  # enforced by _required_field_for_source
        source_path = settings.upload_staging_dir / request.pcap_filename
        if not source_path.is_file():
            raise InvalidPcapError(f"no staged upload found for pcap_filename={request.pcap_filename!r}")
        manifest = ingest_pcap(
            source_path,
            settings.artifact_root,
            capture_id,
            source="pcap_upload",
            original_filename=request.pcap_filename,
        )
        return CaptureAccepted(capture_id=capture_id, status="accepted", packet_count=manifest.packet_count)

    assert request.interface is not None  # enforced by _required_field_for_source
    if not is_authorized_interface(request.interface):
        raise UnauthorizedInterfaceError(
            f"{request.interface!r} is not an authorized capture interface (spec §5 Safety Boundary)"
        )
    return CaptureAccepted(
        capture_id=capture_id,
        status="accepted",
        note=(
            f"Interface {request.interface!r} authorized. Run "
            f"`python3 -m simulator.capture.live --interface {request.interface} --out <path>` "
            "inside the lab's client container, then submit the resulting pcap via "
            "POST /capture with source=pcap_upload."
        ),
    )
