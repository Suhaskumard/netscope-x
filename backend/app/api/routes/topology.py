"""GET /topology. Backing implementation: spec Phase 32 (Probabilistic Topology Reconstruction)."""

from __future__ import annotations

from fastapi import APIRouter, Query

from backend.app.api.errors import NotYetImplemented
from backend.app.models import TopologyGraph

router = APIRouter(prefix="/topology", tags=["topology"])


@router.get("", response_model=TopologyGraph)
def get_topology(
    capture_id: str = Query(..., description="Capture session to reconstruct topology for."),
) -> TopologyGraph:
    raise NotYetImplemented("probabilistic topology reconstruction (spec Phase 32)")
