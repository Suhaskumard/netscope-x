"""POST /counterfactual. Backing implementation: spec Phase 64-66 (Counterfactual Scenario
Language, Counterfactual Graph Engine, Counterfactual Impact Analysis).

Known simplification: the request body currently mirrors the full
CounterfactualScenario domain object (including server-assignable fields
like scenario_id/isolated_graph_id) rather than a dedicated "create"
request DTO. This is acceptable for a not-yet-implemented contract; a
slimmer request schema should be introduced alongside the real
implementation in Phase 64-66 if server-side ID assignment is adopted."""

from __future__ import annotations

from fastapi import APIRouter

from backend.app.api.errors import NotYetImplemented
from backend.app.models import CounterfactualScenario

router = APIRouter(prefix="/counterfactual", tags=["counterfactual"])


@router.post("", response_model=CounterfactualScenario, status_code=202)
def run_counterfactual(scenario: CounterfactualScenario) -> CounterfactualScenario:
    raise NotYetImplemented("counterfactual engine (spec Phase 64-66)")
