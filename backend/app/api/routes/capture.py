"""POST /capture. Backing implementation: spec Phase 21 (High-Fidelity Packet Capture)."""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.app.api.errors import NotYetImplemented

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


class CaptureAccepted(BaseModel):
    capture_id: str
    status: Literal["accepted"]


@router.post("", response_model=CaptureAccepted, status_code=202)
def start_capture(request: CaptureRequest) -> CaptureAccepted:
    raise NotYetImplemented("packet capture (spec Phase 21)")
