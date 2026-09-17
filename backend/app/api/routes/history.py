"""GET /history. Backing implementation: spec Phase 49 (Historical Investigation Engine).

Supports queries like "what changed between t1 and t2?" (spec example)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query

from backend.app.api.errors import NotYetImplemented
from backend.app.api.schemas import PageParams, PaginatedResponse, get_page_params
from backend.app.models import GraphChangeEvent

router = APIRouter(prefix="/history", tags=["history"])


@router.get("", response_model=PaginatedResponse[GraphChangeEvent])
def query_history(
    start: datetime = Query(..., description="Start of the investigation window."),
    end: datetime = Query(..., description="End of the investigation window."),
    page: PageParams = Depends(get_page_params),
) -> PaginatedResponse[GraphChangeEvent]:
    raise NotYetImplemented("historical investigation engine (spec Phase 49)")
