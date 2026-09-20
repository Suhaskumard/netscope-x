"""Failure Propagation Simulator (spec Phase 61, FR-1.34: "simulate failure ->
dependency propagation -> routing impact -> service impact as a connected
pipeline, not isolated stages").

Pure composition, not new logic: this module reimplements none of the three
already-real, already-tested pieces it chains together --
`apply_failure_scenario` (Phase 59, `backend/simulation/failure_injection.py`),
`propagate_failure` (Phase 54, `backend/dependency/failure_propagation.py`),
and `compute_connectivity`/`compute_route_change` (Phase 60,
`backend/simulation/path_engine.py`) are all called exactly as already
built. Both Phase 59 and Phase 60's own docstrings explicitly defer this
composition to "Phase 61" -- this module is that composition.

Three open design questions, each resolved as a firm, documented decision
rather than left implicit:

1. What "failed node" feeds propagation when the injected failure has no
   `target_node_id` (a pure `EDGE_FAILURE`, or an edge-targeted
   `PACKET_LOSS`/`BANDWIDTH_REDUCTION`)? `propagate_failure` requires exactly
   one causal-origin node id. Neither endpoint of a failed edge is uniquely
   "the" failure -- picking one, or merging both, would fabricate causal
   evidence `CausalCandidate` (Phase 53) was specifically built to avoid
   claiming. So propagation runs only when `scenario.target_node_id is not
   None`; an edge-only failure still gets a real, honest routing-impact
   answer from stage 3, just no causal-propagation stage -- a scope
   limitation of Phase 54's own node-oriented design, documented here rather
   than papered over.

2. What counts as "routing impact"? `compute_connectivity` already gives the
   correct O(n) global "did the graph fragment" signal with no pair
   selection needed, used before vs. after injection to derive
   `newly_unreachable_node_ids`. `compute_route_change` needs explicit
   pairs; the only pairs with real evidentiary justification are the
   failure site's own former direct neighbors (or, for an edge failure, the
   edge's own two endpoints) -- paths guaranteed to have actually used the
   failed element. An all-pairs comparison would be undocumented O(n^2)
   scope creep with no basis for most of what it would report.

3. What does "service impact" mean, given this codebase has no service
   registry independent of nodes? A "service" is a node, optionally
   role-classified via the already-existing but currently orphaned Phase
   36-37 `RoleClassification`/`ServiceRole` (its only planned consumer, `GET
   /behaviors/{node_id}`, stays a 501 stub). This module accepts an optional
   caller-supplied `node_id -> RoleClassification` map rather than
   resurrecting that stub or inventing a new classification call here;
   reporting `None` for an unsupplied node is an honest "role unknown," not
   a fabricated guess. Service impact stays strictly itemized/per-node --
   no aggregate ratio/count/score is computed here, since that is
   `ResilienceIndicators` (`backend/app/models/failure.py`), explicitly
   reserved for spec Phase 62. This module supplies the itemized raw
   material that aggregation will need, nothing more.

`POST /simulation` (`backend/app/api/routes/simulation.py`) stays a 501
stub: `SimulationRun` (Phase 04/57-58) has no results field, and no
`experiments/artifacts` path convention reserves one for simulation output
-- wiring the route would mean an unscoped schema or persistence decision,
which FR-1.34 does not ask for (it asks only that the simulation logic be a
connected pipeline).

Never mutates any input `TopologyGraph` -- every composed function already
guarantees this. Never imports `simulator.ground_truth` (spec §4;
`scripts/check_ground_truth_boundary.py` would reject it if it did).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from backend.app.models.behavior import RoleClassification
from backend.app.models.failure import FailureScenario, PropagationImpact
from backend.app.models.topology import TopologyGraph
from backend.dependency.causal_candidates import CausalCandidate
from backend.dependency.failure_propagation import propagate_failure
from backend.simulation.failure_injection import FailureInjectionResult, apply_failure_scenario
from backend.simulation.path_engine import (
    ConnectivityResult,
    RouteChange,
    compute_connectivity,
    compute_route_change,
)


@dataclass(frozen=True)
class ServiceImpact:
    node_id: str
    reason: str  # "propagation" | "routing" | "propagation+routing"
    propagation_order: Optional[str]
    newly_unreachable: bool
    role_classification: Optional[RoleClassification]


@dataclass(frozen=True)
class FailurePipelineResult:
    scenario: FailureScenario
    injection: FailureInjectionResult
    propagation_impacts: List[PropagationImpact]
    connectivity_before: ConnectivityResult
    connectivity_after: ConnectivityResult
    newly_unreachable_node_ids: List[str]
    route_changes: List[RouteChange]
    service_impacts: List[ServiceImpact]


def _former_neighbor_ids(graph: TopologyGraph, node_id: str) -> List[str]:
    neighbors = set()
    for edge in graph.edges:
        if edge.source_node_id == node_id:
            neighbors.add(edge.target_node_id)
        elif edge.target_node_id == node_id:
            neighbors.add(edge.source_node_id)
    return sorted(neighbors)


def _edge_endpoints(graph: TopologyGraph, edge_id: str) -> Optional[tuple]:
    for edge in graph.edges:
        if edge.edge_id == edge_id:
            return (edge.source_node_id, edge.target_node_id)
    return None


def _compute_route_changes(
    graph: TopologyGraph,
    injection: FailureInjectionResult,
) -> List[RouteChange]:
    scenario = injection.scenario
    present_node_ids = {n.node_id for n in injection.graph.nodes}

    if scenario.target_node_id is not None:
        pairs = [
            (neighbor, scenario.target_node_id)
            for neighbor in _former_neighbor_ids(graph, scenario.target_node_id)
            if neighbor in present_node_ids
        ]
    elif scenario.target_edge_id is not None:
        endpoints = _edge_endpoints(graph, scenario.target_edge_id)
        if endpoints is None:
            pairs = []
        else:
            source_id, target_id = endpoints
            pairs = [(source_id, target_id)]
    else:
        pairs = []

    return [
        compute_route_change(graph, injection.graph, source_id, target_id, failure=injection)
        for source_id, target_id in pairs
    ]


def _newly_unreachable_node_ids(
    injection: FailureInjectionResult,
    connectivity_before: ConnectivityResult,
    connectivity_after: ConnectivityResult,
) -> List[str]:
    before_main = set(connectivity_before.largest_component_node_ids)
    after_main = set(connectivity_after.largest_component_node_ids)
    still_present = before_main - set(injection.removed_node_ids)
    return sorted(still_present - after_main)


def run_failure_propagation_pipeline(
    graph: TopologyGraph,
    scenario: FailureScenario,
    candidates: List[CausalCandidate],
    role_classifications: Optional[Dict[str, RoleClassification]] = None,
) -> FailurePipelineResult:
    """Runs the full failure -> dependency propagation -> routing impact ->
    service impact pipeline for `scenario` against `graph`.

    `role_classifications`, if given, maps `node_id` to a Phase 36-37
    `RoleClassification` used to annotate `service_impacts`; nodes with no
    entry get `role_classification=None` rather than a guessed role. Never
    mutates `graph`.
    """
    injection = apply_failure_scenario(graph, scenario)

    if scenario.target_node_id is not None:
        propagation_impacts = propagate_failure(candidates, scenario.scenario_id, scenario.target_node_id)
    else:
        propagation_impacts = []

    connectivity_before = compute_connectivity(graph)
    connectivity_after = compute_connectivity(injection.graph)
    newly_unreachable_node_ids = _newly_unreachable_node_ids(
        injection, connectivity_before, connectivity_after
    )
    route_changes = _compute_route_changes(graph, injection)

    propagation_order_by_node: Dict[str, str] = {
        impact.affected_node_id: impact.order.value for impact in propagation_impacts
    }
    unreachable_set = set(newly_unreachable_node_ids)
    impacted_node_ids = sorted(set(propagation_order_by_node) | unreachable_set)

    role_classifications = role_classifications or {}
    service_impacts = []
    for node_id in impacted_node_ids:
        in_propagation = node_id in propagation_order_by_node
        in_routing = node_id in unreachable_set
        if in_propagation and in_routing:
            reason = "propagation+routing"
        elif in_propagation:
            reason = "propagation"
        else:
            reason = "routing"
        service_impacts.append(
            ServiceImpact(
                node_id=node_id,
                reason=reason,
                propagation_order=propagation_order_by_node.get(node_id),
                newly_unreachable=in_routing,
                role_classification=role_classifications.get(node_id),
            )
        )

    return FailurePipelineResult(
        scenario=scenario,
        injection=injection,
        propagation_impacts=propagation_impacts,
        connectivity_before=connectivity_before,
        connectivity_after=connectivity_after,
        newly_unreachable_node_ids=newly_unreachable_node_ids,
        route_changes=route_changes,
        service_impacts=service_impacts,
    )
