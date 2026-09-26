"""GET /dependencies. Backing implementation: spec Phase 51 (Dependency Strength), extended
Phase 52 (Temporal Precedence Analysis).

Deliberately distinct from mere communication (spec Phase 50; RQ5) -- this endpoint returns
inferred `DependencyEdge` records, never plain communication-observation records. Estimates
`strength`/`directionality_score` from frequency, persistence, directionality, and traffic
characteristics over Phase 50's `CommunicationRelationship`s (`estimate_dependency_strength`,
`backend/dependency/strength.py`); `temporal_precedence_score` is now genuinely computed too
(Phase 52's `estimate_temporal_precedence`), completing all five of FR-1.26's named signals.

Same "missing means empty" convention `GET /history`/Phase 50 already use for this layer: an
unrecognized `capture_id` returns an empty, still-200 paginated result, not a 404 -- there is no
per-request pcap processing here to make a missing capture a distinct error condition.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from backend.app.api.schemas import CAPTURE_ID_PATTERN, PageParams, PaginatedResponse, get_page_params
from backend.app.core.config import get_settings
from backend.app.tenancy.deps import TenantScope, get_tenant_scope
from backend.app.models import DependencyEdge
from backend.dependency.strength import estimate_dependency_strength

router = APIRouter(prefix="/dependencies", tags=["dependencies"])


@router.get("", response_model=PaginatedResponse[DependencyEdge])
def list_dependencies(
    capture_id: str = Query(
        ..., description="Capture session to list dependencies for.", pattern=CAPTURE_ID_PATTERN
    ),
    page: PageParams = Depends(get_page_params),
    scope: TenantScope = Depends(get_tenant_scope),
) -> PaginatedResponse[DependencyEdge]:
    settings = get_settings()
    dependencies = estimate_dependency_strength(
        scope.root,
        capture_id,
        edge_confidence_packet_scale=settings.edge_confidence_packet_scale,
        edge_confidence_signal_strength=settings.edge_confidence_signal_strength,
        dependency_frequency_scale=settings.dependency_frequency_scale,
        dependency_persistence_scale=settings.dependency_persistence_scale,
        dependency_signal_strength=settings.dependency_signal_strength,
        dependency_temporal_bucket_seconds=settings.dependency_temporal_bucket_seconds,
        dependency_temporal_max_lag_buckets=settings.dependency_temporal_max_lag_buckets,
    )

    page_items = dependencies[page.offset : page.offset + page.limit]
    return PaginatedResponse[DependencyEdge](
        items=page_items, limit=page.limit, offset=page.offset, total=len(dependencies)
    )
