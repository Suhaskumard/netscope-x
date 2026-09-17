"""GET /flows. Backing implementation: spec Phase 23 (Five-Tuple Flow Reconstruction)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from backend.app.api.errors import NotYetImplemented
from backend.app.api.schemas import PageParams, PaginatedResponse, get_page_params
from backend.app.models import Flow

router = APIRouter(prefix="/flows", tags=["flows"])


@router.get("", response_model=PaginatedResponse[Flow])
def list_flows(
    capture_id: str = Query(..., description="Capture session to list flows for."),
    page: PageParams = Depends(get_page_params),
) -> PaginatedResponse[Flow]:
    raise NotYetImplemented("flow reconstruction (spec Phase 23)")
