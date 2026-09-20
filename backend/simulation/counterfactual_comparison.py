"""Counterfactual Outcome Comparison (spec Phase 66, FR-1.37: "compare
baseline vs. counterfactual outcomes across paths, connectivity, latency,
affected services, bottlenecks, and propagation").

Pure composition, not new logic: this module reimplements none of Phase
54's `propagate_failure`, Phase 55's `compute_graph_criticality`, or Phase
60's `compute_connectivity`/`compute_route_change` -- it only calls them
against a baseline `TopologyGraph` and a Phase 65 `CounterfactualExecutionResult`.
`path_engine.py`, `counterfactual_engine.py`, `failure_propagation_pipeline.py`,
`resilience_indicators.py`, `criticality.py`, and `failure_propagation.py`
are all consumed read-only; none of them are modified by this phase.

Two genuinely hard design questions, both resolved firmly:

1. **The "propagation" axis.** `CounterfactualScenario` carries no
   `CausalCandidate` feed at all -- nothing ties a counterfactual to causal
   evidence the way `FailureScenario` does via Phase 61's separately-supplied
   `candidates` argument. A propagation axis that only works when causal
   evidence happens to be supplied would produce nothing for the common
   case. So this module computes BOTH, as two separate, clearly labeled
   fields, never merged: `structural_propagation_impacts` (always computed,
   a BFS hop-distance cascade from the change site over the baseline graph's
   plain adjacency, restricted to nodes that actually became unreachable --
   honestly derivable from data this module already has, and explicitly
   labeled *structural*, never claiming causal evidence it doesn't possess)
   and `causal_propagation_impacts` (computed only when the caller supplies
   `candidates` AND the scenario has a `target_node_id`, calling Phase 54's
   real `propagate_failure` unmodified -- exactly Phase 61's own gating
   condition, reused rather than reinvented). Fusing the two into one list
   would misrepresent structural inference as causal evidence, exactly the
   fabrication spec Sec21 ("No Fake Metrics") forbids.

2. **The "latency" axis.** For the three hard actions (REMOVE_NODE/
   REMOVE_EDGE/ADD_ROUTE) the isolated graph is already structurally
   different from baseline, so `compute_route_change(baseline_graph,
   execution.graph, source, target)` -- called with no `failure=` argument
   -- already captures the real path-cost difference correctly. For the
   three soft actions (INCREASE_LATENCY/REDUCE_BANDWIDTH/INCREASE_TRAFFIC)
   the isolated graph is structurally IDENTICAL to baseline (only
   `degraded_edge_ids` marked), so the same call with no `failure=` would
   show zero difference -- defeating the point. `_maybe_adapter_injection`
   resolves this with a translation adapter, not a parallel reimplementation
   of `_edge_weight`'s formula: it maps `INCREASE_LATENCY` ->
   `FailureType.LATENCY_INJECTION` + `latency_ms=magnitude`,
   `REDUCE_BANDWIDTH` -> `FailureType.BANDWIDTH_REDUCTION` +
   `bandwidth_reduction_ratio=magnitude` (an out-of-range `magnitude`
   raises Pydantic `ValidationError` here -- a decidable, honest failure,
   never silently clamped), and constructs a synthetic `FailureScenario`/
   `FailureInjectionResult` pair to pass as `failure=`, reusing Phase 60's
   exact tested weighting formula with zero logic duplication -- just
   field-name translation. `INCREASE_TRAFFIC` has no `FailureType` analog
   (the same documented gap Phase 64/65 already recorded) -- returns
   `None`, correctly producing zero extra path cost, an honest limitation,
   not an invented number.

Never imports `simulator.ground_truth` (spec Sec4;
`scripts/check_ground_truth_boundary.py` would reject it if it did).
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from backend.app.models.behavior import RoleClassification
from backend.app.models.failure import FailureScenario, FailureType, PropagationImpact
from backend.app.models.simulation import CounterfactualAction, CounterfactualScenario
from backend.app.models.topology import TopologyGraph
from backend.dependency.causal_candidates import CausalCandidate
from backend.dependency.criticality import compute_graph_criticality
from backend.dependency.failure_propagation import propagate_failure
from backend.simulation.counterfactual_engine import CounterfactualExecutionResult
from backend.simulation.failure_injection import FailureInjectionResult
from backend.simulation.path_engine import (
    ConnectivityResult,
    RouteChange,
    compute_connectivity,
    compute_route_change,
)

_UNREACHABLE_PATH_PENALTY = -math.log(1e-9)  # same -log(confidence) unit as path_engine.py/resilience_indicators.py


@dataclass(frozen=True)
class CounterfactualServiceImpact:
    node_id: str
    reason: str  # "removed" | "newly_unreachable" | "route_changed" | "propagation", "+"-joined if multiple
    causal_propagation_order: Optional[str]
    role_classification: Optional[RoleClassification]


@dataclass(frozen=True)
class StructuralPropagationImpact:
    node_id: str
    hop_distance: int
    order: str  # "SECONDARY" (hop 1) | "TERTIARY" (hop 2) | "FURTHER" (hop >= 3)


@dataclass(frozen=True)
class CounterfactualComparisonResult:
    scenario: CounterfactualScenario
    execution: CounterfactualExecutionResult
    connectivity_before: ConnectivityResult
    connectivity_after: ConnectivityResult
    newly_unreachable_node_ids: List[str]
    route_changes: List[RouteChange]
    total_latency_delta: float
    service_impacts: List[CounterfactualServiceImpact]
    bottleneck_node_ids: List[str]
    structural_propagation_impacts: List[StructuralPropagationImpact]
    causal_propagation_impacts: List[PropagationImpact]
    causal_propagation_evaluated: bool


def _former_neighbor_ids(graph: TopologyGraph, node_id: str) -> List[str]:
    neighbors: Set[str] = set()
    for edge in graph.edges:
        if edge.source_node_id == node_id:
            neighbors.add(edge.target_node_id)
        elif edge.target_node_id == node_id:
            neighbors.add(edge.source_node_id)
    return sorted(neighbors)


def _edge_endpoints(graph: TopologyGraph, edge_id: str) -> Optional[Tuple[str, str]]:
    for edge in graph.edges:
        if edge.edge_id == edge_id:
            return (edge.source_node_id, edge.target_node_id)
    return None


def _comparison_pairs(baseline_graph: TopologyGraph, scenario: CounterfactualScenario) -> List[Tuple[str, str]]:
    if scenario.action == CounterfactualAction.ADD_ROUTE:
        return [(scenario.source_node_id, scenario.target_node_id)]
    if scenario.target_node_id is not None:
        return [(neighbor, scenario.target_node_id) for neighbor in _former_neighbor_ids(baseline_graph, scenario.target_node_id)]
    if scenario.target_edge_id is not None:
        endpoints = _edge_endpoints(baseline_graph, scenario.target_edge_id)
        return [] if endpoints is None else [endpoints]
    return []


def _maybe_adapter_injection(execution: CounterfactualExecutionResult) -> Optional[FailureInjectionResult]:
    scenario = execution.scenario
    if scenario.action == CounterfactualAction.INCREASE_LATENCY:
        failure_type = FailureType.LATENCY_INJECTION
        extra = {"latency_ms": scenario.magnitude}
    elif scenario.action == CounterfactualAction.REDUCE_BANDWIDTH:
        failure_type = FailureType.BANDWIDTH_REDUCTION
        extra = {"bandwidth_reduction_ratio": scenario.magnitude}
    else:
        # Hard actions: the isolated graph's own structural diff already produces the
        # correct path-cost delta with no adapter. INCREASE_TRAFFIC: no FailureType
        # analog exists (same documented gap as Phase 64/65's own decision tables).
        return None

    synthetic_scenario = FailureScenario(
        scenario_id=f"{scenario.scenario_id}:latency-adapter",
        failure_type=failure_type,
        target_node_id=scenario.target_node_id,
        target_edge_id=scenario.target_edge_id,
        **extra,
    )
    return FailureInjectionResult(
        scenario=synthetic_scenario,
        graph=execution.graph,
        removed_node_ids=[],
        removed_edge_ids=[],
        degraded_edge_ids=execution.degraded_edge_ids,
    )


def _route_degradation(route_change: RouteChange) -> float:
    if route_change.baseline_path is None:
        return 0.0
    if route_change.current_path is None:
        return _UNREACHABLE_PATH_PENALTY
    return max(route_change.cost_delta, 0.0)


def _newly_unreachable_node_ids(
    execution: CounterfactualExecutionResult,
    connectivity_before: ConnectivityResult,
    connectivity_after: ConnectivityResult,
) -> List[str]:
    before_main = set(connectivity_before.largest_component_node_ids)
    after_main = set(connectivity_after.largest_component_node_ids)
    still_present = before_main - set(execution.removed_node_ids)
    return sorted(still_present - after_main)


def _bottleneck_node_ids(baseline_graph: TopologyGraph, execution: CounterfactualExecutionResult) -> List[str]:
    pre_report = compute_graph_criticality(baseline_graph)
    post_report = compute_graph_criticality(execution.graph)
    pre_articulation_ids = {ns.node_id for ns in pre_report.node_scores if ns.is_articulation_point}
    post_articulation_ids = {ns.node_id for ns in post_report.node_scores if ns.is_articulation_point}
    return sorted(post_articulation_ids - pre_articulation_ids)


def _change_site_node_ids(scenario: CounterfactualScenario, baseline_graph: TopologyGraph) -> List[str]:
    if scenario.action == CounterfactualAction.ADD_ROUTE:
        return sorted({scenario.source_node_id, scenario.target_node_id})
    if scenario.target_node_id is not None:
        return [scenario.target_node_id]
    if scenario.target_edge_id is not None:
        endpoints = _edge_endpoints(baseline_graph, scenario.target_edge_id)
        return [] if endpoints is None else sorted(endpoints)
    return []


def _structural_propagation_impacts(
    baseline_graph: TopologyGraph,
    scenario: CounterfactualScenario,
    newly_unreachable_node_ids: List[str],
) -> List[StructuralPropagationImpact]:
    """BFS hop-distance from the change site over `baseline_graph`'s plain
    adjacency, restricted to nodes that actually became unreachable --
    a structural cascade, never claiming causal evidence."""
    unreachable = set(newly_unreachable_node_ids)
    if not unreachable:
        return []

    adjacency: Dict[str, Set[str]] = {}
    for edge in baseline_graph.edges:
        adjacency.setdefault(edge.source_node_id, set()).add(edge.target_node_id)
        adjacency.setdefault(edge.target_node_id, set()).add(edge.source_node_id)

    origins = _change_site_node_ids(scenario, baseline_graph)
    visited: Dict[str, int] = {origin: 0 for origin in origins}
    queue: deque = deque(origins)
    while queue:
        node = queue.popleft()
        for neighbor in sorted(adjacency.get(node, ())):
            if neighbor in visited:
                continue
            visited[neighbor] = visited[node] + 1
            queue.append(neighbor)

    impacts = []
    for node_id in sorted(unreachable):
        hop = visited.get(node_id)
        if hop is None or hop == 0:
            continue
        order = "SECONDARY" if hop == 1 else "TERTIARY" if hop == 2 else "FURTHER"
        impacts.append(StructuralPropagationImpact(node_id=node_id, hop_distance=hop, order=order))
    return impacts


def compare_counterfactual_outcome(
    baseline_graph: TopologyGraph,
    execution: CounterfactualExecutionResult,
    candidates: Optional[List[CausalCandidate]] = None,
    role_classifications: Optional[Dict[str, RoleClassification]] = None,
) -> CounterfactualComparisonResult:
    """Compares `execution` (a Phase 65 `execute_counterfactual_scenario`
    result) against `baseline_graph` across FR-1.37's six named axes: paths,
    connectivity, latency, affected services, bottlenecks, and propagation.
    Never mutates either argument.
    """
    scenario = execution.scenario
    if scenario.baseline_graph_id != baseline_graph.graph_id:
        raise ValueError(
            f"scenario.baseline_graph_id {scenario.baseline_graph_id!r} does not match "
            f"baseline_graph.graph_id {baseline_graph.graph_id!r}"
        )

    connectivity_before = compute_connectivity(baseline_graph)
    connectivity_after = compute_connectivity(execution.graph)
    newly_unreachable_node_ids = _newly_unreachable_node_ids(execution, connectivity_before, connectivity_after)

    adapter = _maybe_adapter_injection(execution)
    pairs = _comparison_pairs(baseline_graph, scenario)
    route_changes = [
        compute_route_change(baseline_graph, execution.graph, source_id, target_id, failure=adapter)
        for source_id, target_id in pairs
    ]
    total_latency_delta = sum(_route_degradation(rc) for rc in route_changes)

    bottleneck_node_ids = _bottleneck_node_ids(baseline_graph, execution)

    structural_propagation_impacts = _structural_propagation_impacts(baseline_graph, scenario, newly_unreachable_node_ids)

    causal_propagation_evaluated = candidates is not None and scenario.target_node_id is not None
    causal_propagation_impacts: List[PropagationImpact] = (
        propagate_failure(candidates, scenario.scenario_id, scenario.target_node_id)
        if causal_propagation_evaluated
        else []
    )

    role_classifications = role_classifications or {}
    reasons_by_node: Dict[str, List[str]] = {}
    for node_id in execution.removed_node_ids:
        reasons_by_node.setdefault(node_id, []).append("removed")
    for node_id in newly_unreachable_node_ids:
        reasons_by_node.setdefault(node_id, []).append("newly_unreachable")
    for route_change in route_changes:
        if route_change.changed:
            reasons_by_node.setdefault(route_change.source_node_id, []).append("route_changed")
            reasons_by_node.setdefault(route_change.target_node_id, []).append("route_changed")
    causal_order_by_node: Dict[str, str] = {}
    for impact in causal_propagation_impacts:
        reasons_by_node.setdefault(impact.affected_node_id, []).append("propagation")
        causal_order_by_node[impact.affected_node_id] = impact.order.value

    service_impacts = [
        CounterfactualServiceImpact(
            node_id=node_id,
            reason="+".join(dict.fromkeys(reasons)),
            causal_propagation_order=causal_order_by_node.get(node_id),
            role_classification=role_classifications.get(node_id),
        )
        for node_id, reasons in sorted(reasons_by_node.items())
    ]

    return CounterfactualComparisonResult(
        scenario=scenario,
        execution=execution,
        connectivity_before=connectivity_before,
        connectivity_after=connectivity_after,
        newly_unreachable_node_ids=newly_unreachable_node_ids,
        route_changes=route_changes,
        total_latency_delta=total_latency_delta,
        service_impacts=service_impacts,
        bottleneck_node_ids=bottleneck_node_ids,
        structural_propagation_impacts=structural_propagation_impacts,
        causal_propagation_impacts=causal_propagation_impacts,
        causal_propagation_evaluated=causal_propagation_evaluated,
    )
