"""POST /simulation. Backing implementation: spec Phase 59-61 (Failure Injection Framework,
Dynamic Path Engine, Failure Propagation Simulator) are now real as library code --
`backend.simulation.failure_propagation_pipeline.run_failure_propagation_pipeline`. This route
stays unwired: `SimulationRun` (Phase 04/57-58) carries only run metadata (run_id,
twin_snapshot_id, scenario, timestamps), no results field, and no `experiments/artifacts` path
convention reserves one for simulation output. Wiring this route would require an unscoped
schema or persistence decision that FR-1.34 does not ask for -- it asks only that the simulation
logic itself be a connected pipeline. See `docs/architecture/failure_propagation_simulator.md`."""

from __future__ import annotations

from fastapi import APIRouter

from backend.app.api.errors import NotYetImplemented
from backend.app.models import FailureScenario, SimulationRun

router = APIRouter(prefix="/simulation", tags=["simulation"])


@router.post("", response_model=SimulationRun, status_code=202)
def run_simulation(scenario: FailureScenario) -> SimulationRun:
    raise NotYetImplemented(
        "POST /simulation API wiring and result persistence (library complete: spec Phase 59-61)"
    )
