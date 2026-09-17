"""GET /metrics. Backing implementation: spec Phase 68 (Complete Research Validation) --
every returned MetricResult must trace to an experiment_id (spec §21, no fake metrics)."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from backend.app.api.errors import NotYetImplemented
from backend.app.api.schemas import PageParams, PaginatedResponse, get_page_params
from backend.app.models import MetricContext, MetricResult

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("", response_model=PaginatedResponse[MetricResult])
def list_metrics(
    context: Optional[MetricContext] = Query(default=None),
    page: PageParams = Depends(get_page_params),
) -> PaginatedResponse[MetricResult]:
    raise NotYetImplemented("evaluation metrics (spec Phase 68)")
