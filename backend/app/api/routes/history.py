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
from backend.app.models import GraphChangeEvent, NetworkSnapshot, TopologyGraph
from backend.archaeology.snapshots import SnapshotNotFoundError, list_snapshots, read_snapshot_graph
from backend.archaeology.timeline import build_topology_event_timeline

router = APIRouter(prefix="/history", tags=["history"])


@router.get("/snapshots", response_model=PaginatedResponse[NetworkSnapshot])
def list_history_snapshots(
    capture_id: str = Query(..., description="Capture session to list snapshots for.", pattern=CAPTURE_ID_PATTERN),
    page: PageParams = Depends(get_page_params),
    scope: TenantScope = Depends(get_tenant_scope),
) -> PaginatedResponse[NetworkSnapshot]:
    """Phase 97: the recorded snapshots (version order) the time-travel explorer scrubs through. Same "unknown capture
    means empty" convention as GET /history."""
    snapshots = list_snapshots(scope.root, capture_id)
    return PaginatedResponse[NetworkSnapshot](
        items=snapshots[page.offset : page.offset + page.limit], limit=page.limit, offset=page.offset, total=len(snapshots)
    )


@router.get("/snapshots/{version}/topology", response_model=TopologyGraph)
def get_snapshot_topology(
    version: int,
    capture_id: str = Query(..., description="Capture session the snapshot belongs to.", pattern=CAPTURE_ID_PATTERN),
    scope: TenantScope = Depends(get_tenant_scope),
) -> TopologyGraph:
    """Phase 97: the topology graph exactly as recorded at snapshot `version` (read back, never recomputed)."""
    snapshot = next((s for s in list_snapshots(scope.root, capture_id) if s.version == version), None)
    if snapshot is None:
        raise SnapshotNotFoundError(f"capture {capture_id!r} has no snapshot version {version}")
    return read_snapshot_graph(scope.root, capture_id, snapshot)


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
