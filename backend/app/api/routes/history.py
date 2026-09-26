"""GET /history. Backing implementation: spec Phase 49 (Historical Investigation Engine).

Supports queries like "what changed between t1 and t2?" (spec example) by filtering Phase 47's
persisted, chronological `GraphChangeEvent` stream (`build_topology_event_timeline`) to the
requested `[start, end]` window (inclusive both ends) and paginating with the same machinery
`GET /flows` already uses.

Unlike `GET /flows`/`GET /topology`, this route does not 404 on an unrecognized `capture_id`:
`build_topology_event_timeline` -> `list_snapshots` already follows the archaeology layer's
"missing means empty" convention (no snapshots yet, or no such capture at all, both just mean
`[]`), so an unknown `capture_id` here naturally returns an empty, still-200 paginated result --
a deliberate convention choice, not an oversight.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query

from backend.app.api.schemas import CAPTURE_ID_PATTERN, PageParams, PaginatedResponse, get_page_params
from backend.app.core.config import get_settings
from backend.app.tenancy.deps import TenantScope, get_tenant_scope
from backend.app.models import GraphChangeEvent
from backend.archaeology.timeline import build_topology_event_timeline

router = APIRouter(prefix="/history", tags=["history"])


@router.get("", response_model=PaginatedResponse[GraphChangeEvent])
def query_history(
    capture_id: str = Query(
        ..., description="Capture session to investigate.", pattern=CAPTURE_ID_PATTERN
    ),
    start: datetime = Query(..., description="Start of the investigation window."),
    end: datetime = Query(..., description="End of the investigation window."),
    page: PageParams = Depends(get_page_params),
    scope: TenantScope = Depends(get_tenant_scope),
) -> PaginatedResponse[GraphChangeEvent]:
    settings = get_settings()
    events = build_topology_event_timeline(scope.root, capture_id)
    window = [event for event in events if start <= event.occurred_at <= end]

    page_items = window[page.offset : page.offset + page.limit]
    return PaginatedResponse[GraphChangeEvent](
        items=page_items, limit=page.limit, offset=page.offset, total=len(window)
    )
