"""POST /simulation. Backing implementation: spec Phase 59-61 (Failure Injection Framework,
Dynamic Path Engine, Failure Propagation Simulator)."""

from __future__ import annotations

from fastapi import APIRouter

from backend.app.api.errors import NotYetImplemented
from backend.app.models import FailureScenario, SimulationRun

router = APIRouter(prefix="/simulation", tags=["simulation"])


@router.post("", response_model=SimulationRun, status_code=202)
def run_simulation(scenario: FailureScenario) -> SimulationRun:
    raise NotYetImplemented("failure injection / simulation engine (spec Phase 59-61)")
