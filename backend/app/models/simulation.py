"""Simulation-run and counterfactual-scenario data contracts.

Serves FR-1.31, FR-1.36-1.38 (spec Phases 57-58, 63-66).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator

from backend.app.models.failure import FailureScenario


class SimulationRun(BaseModel):
    """A single execution of the digital twin against a failure scenario (spec Phase 57-58, 61)."""

    run_id: str
    twin_snapshot_id: str = Field(..., description="Digital twin state the simulation ran against.")
    scenario: FailureScenario
    started_at: datetime
    completed_at: Optional[datetime] = None


class CounterfactualAction(str, Enum):
    """The structured counterfactual scenario language (spec Phase 64)."""

    REMOVE_NODE = "REMOVE_NODE"
    REMOVE_EDGE = "REMOVE_EDGE"
    INCREASE_LATENCY = "INCREASE_LATENCY"
    REDUCE_BANDWIDTH = "REDUCE_BANDWIDTH"
    INCREASE_TRAFFIC = "INCREASE_TRAFFIC"
    ADD_ROUTE = "ADD_ROUTE"


class CounterfactualScenario(BaseModel):
    """A hypothetical 'what if' scenario (spec Phase 64-65).

    `isolated_graph_id` is required and must differ from `baseline_graph_id`
    to make it structurally impossible to represent a counterfactual that
    claims to have mutated the real baseline (spec Phase 65: "Never mutate
    the original baseline").
    """

    scenario_id: str
    action: CounterfactualAction
    baseline_graph_id: str
    isolated_graph_id: str
    target_node_id: Optional[str] = None
    target_edge_id: Optional[str] = None
    magnitude: Optional[float] = Field(
        default=None, description="e.g. added latency in ms, or traffic multiplier, depending on action."
    )
    created_at: datetime

    @model_validator(mode="after")
    def _isolated_differs_from_baseline(self) -> "CounterfactualScenario":
        if self.baseline_graph_id == self.isolated_graph_id:
            raise ValueError("isolated_graph_id must differ from baseline_graph_id")
        return self
