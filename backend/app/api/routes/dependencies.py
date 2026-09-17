"""GET /dependencies. Backing implementation: spec Phase 51 (Dependency Strength).

Deliberately distinct from mere communication (spec Phase 50; RQ5) -- this
endpoint returns inferred DependencyEdge records, never plain
communication-observation records."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from backend.app.api.errors import NotYetImplemented
from backend.app.api.schemas import PageParams, PaginatedResponse, get_page_params
from backend.app.models import DependencyEdge

router = APIRouter(prefix="/dependencies", tags=["dependencies"])


@router.get("", response_model=PaginatedResponse[DependencyEdge])
def list_dependencies(
    capture_id: str = Query(..., description="Capture session to list dependencies for."),
    page: PageParams = Depends(get_page_params),
) -> PaginatedResponse[DependencyEdge]:
    raise NotYetImplemented("dependency inference (spec Phase 51)")
