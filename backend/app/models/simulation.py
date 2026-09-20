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

    `_action_requires_correct_fields` (spec Phase 64) enforces each of the
    six `CounterfactualAction` values' own required fields -- `source_node_id`
    (new this phase, mirroring `Edge.source_node_id`/`target_node_id`) is
    ADD_ROUTE's second endpoint and must stay `None` for every other action.
    See `docs/architecture/counterfactual_scenario_language.md` for the full
    per-action decision table and rationale.
    """

    scenario_id: str
    action: CounterfactualAction
    baseline_graph_id: str
    isolated_graph_id: str
    source_node_id: Optional[str] = Field(
        default=None,
        description="ADD_ROUTE only: the new route's origin node. Must stay None for every other action.",
    )
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

    @model_validator(mode="after")
    def _action_requires_correct_fields(self) -> "CounterfactualScenario":
        """Per-action field requirements (spec Phase 64). Unlike `FailureScenario`'s own
        precedent, where Phase 04's schema validator covered 4/6 types and Phase 59 patched
        the remaining ambiguous two at execution time, this phase owns `CounterfactualScenario`'s
        validation completely -- nothing else touches this schema before Phase 65 consumes it --
        so every action's requirements are enforced here in one pass."""
        if self.action != CounterfactualAction.ADD_ROUTE and self.source_node_id is not None:
            raise ValueError("source_node_id may only be set for ADD_ROUTE")

        if self.action == CounterfactualAction.REMOVE_NODE:
            if self.target_node_id is None:
                raise ValueError("REMOVE_NODE requires target_node_id")

        elif self.action == CounterfactualAction.REMOVE_EDGE:
            if self.target_edge_id is None:
                raise ValueError("REMOVE_EDGE requires target_edge_id")

        elif self.action == CounterfactualAction.INCREASE_LATENCY:
            if self.target_node_id is None:
                raise ValueError("INCREASE_LATENCY requires target_node_id")
            if self.magnitude is None:
                raise ValueError("INCREASE_LATENCY requires magnitude")

        elif self.action == CounterfactualAction.REDUCE_BANDWIDTH:
            if self.target_node_id is None and self.target_edge_id is None:
                raise ValueError("REDUCE_BANDWIDTH requires target_node_id or target_edge_id")
            if self.magnitude is None:
                raise ValueError("REDUCE_BANDWIDTH requires magnitude")

        elif self.action == CounterfactualAction.INCREASE_TRAFFIC:
            if self.target_node_id is None:
                raise ValueError("INCREASE_TRAFFIC requires target_node_id")
            if self.magnitude is None:
                raise ValueError("INCREASE_TRAFFIC requires magnitude")

        elif self.action == CounterfactualAction.ADD_ROUTE:
            if self.source_node_id is None or self.target_node_id is None:
                raise ValueError("ADD_ROUTE requires both source_node_id and target_node_id")
            if self.target_edge_id is not None:
                raise ValueError("ADD_ROUTE cannot reference an existing target_edge_id")
            if self.source_node_id == self.target_node_id:
                raise ValueError("ADD_ROUTE cannot connect a node to itself")

        return self
