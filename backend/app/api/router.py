"""Aggregates all 12 required endpoint groups (spec Phase 09) under a
versioned prefix (NFR-6, versioned APIs)."""

from __future__ import annotations

from fastapi import APIRouter

from backend.app.api.routes import (
    anomalies,
    behaviors,
    capture,
    causal,
    counterfactual,
    dependencies,
    experiments,
    flows,
    history,
    metrics,
    simulation,
    topology,
)

api_router = APIRouter(prefix="/api/v1")

for _module in (
    capture,
    flows,
    topology,
    behaviors,
    anomalies,
    history,
    dependencies,
    causal,
    simulation,
    counterfactual,
    experiments,
    metrics,
):
    api_router.include_router(_module.router)
