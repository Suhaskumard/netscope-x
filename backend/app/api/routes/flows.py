"""GET /flows. Backing implementation: spec Phase 23 (Five-Tuple Flow Reconstruction).

Recomputes flows fresh on every request: normalizes `raw.pcap` (Phase 22)
then reconstructs five-tuple flows (Phase 23) and paginates the result.
This is a deliberate, documented simplification -- no job queue or cache
layer, consistent with spec §6's "minimum necessary infrastructure" -- not
a REST-purity claim; see docs/architecture/flow_reconstruction.md.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from backend.app.api.schemas import CAPTURE_ID_PATTERN, PageParams, PaginatedResponse, get_page_params
from backend.app.core.config import get_settings
from backend.app.models import Flow
from backend.nettrace.capture.errors import CaptureNotFoundError
from backend.nettrace.normalize import normalize_pcap
from backend.nettrace.reconstruct import reconstruct_flows
from experiments.artifacts.paths import pcap_path

router = APIRouter(prefix="/flows", tags=["flows"])


@router.get("", response_model=PaginatedResponse[Flow])
def list_flows(
    capture_id: str = Query(
        ..., description="Capture session to list flows for.", pattern=CAPTURE_ID_PATTERN
    ),
    page: PageParams = Depends(get_page_params),
) -> PaginatedResponse[Flow]:
    settings = get_settings()
    if not pcap_path(settings.artifact_root, capture_id).is_file():
        raise CaptureNotFoundError(f"no ingested capture found for capture_id={capture_id!r}")

    normalize_pcap(settings.artifact_root, capture_id)
    flows = reconstruct_flows(
        settings.artifact_root,
        capture_id,
        udp_session_idle_timeout_seconds=settings.udp_session_idle_timeout_seconds,
    )

    window = flows[page.offset : page.offset + page.limit]
    return PaginatedResponse[Flow](items=window, limit=page.limit, offset=page.offset, total=len(flows))
