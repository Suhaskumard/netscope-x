"""GET /anomalies. Backing implementation: spec Phase 40-41 (Multi-Dimensional Anomaly
Detection, Explainable Anomalies)."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from backend.app.api.errors import NotYetImplemented
from backend.app.api.schemas import PageParams, PaginatedResponse, get_page_params
from backend.app.models import Anomaly

router = APIRouter(prefix="/anomalies", tags=["anomalies"])


@router.get("", response_model=PaginatedResponse[Anomaly])
def list_anomalies(
    node_id: Optional[str] = Query(default=None, description="Filter to a single node."),
    page: PageParams = Depends(get_page_params),
) -> PaginatedResponse[Anomaly]:
    raise NotYetImplemented("anomaly detection (spec Phase 40)")
