"""Resilience & Vulnerability Indicators (spec Phase 62, FR-1.35: "compute
resilience indicators: connectivity, reachable-node ratio, affected services,
path degradation, bottleneck emergence, alternative-path availability").

Pure aggregation, not new logic: `ResilienceIndicators`
(`backend/app/models/failure.py`) has existed since Phase 04 and was explicitly
reserved for this phase by both `docs/architecture/failure_propagation_simulator.md`
and `docs/architecture/dynamic_path_engine.md`, which each deferred these six
metrics here rather than computing them early. This module reimplements none of
Phase 55's `compute_graph_criticality`, Phase 60's `compute_alternate_paths`, or
Phase 61's `run_failure_propagation_pipeline` -- it only aggregates their already-
real outputs.

`compute_resilience_indicators(graph, result)` takes both the pre-failure
`TopologyGraph` and a Phase 61 `FailurePipelineResult`. `result` alone almost
suffices (its `connectivity_before`/`connectivity_after`, `route_changes`,
`service_impacts`, and `injection.graph` cover five of six metrics), but it
carries no pre-failure graph object -- only `ConnectivityResult` component
membership, no edge list. `graph` is needed once, for `bottleneck_node_ids`'s
pre/post articulation-point diff. No stage of Phase 61's pipeline (injection,
propagation, routing) is re-run here. `graph` must be the exact pre-failure
graph originally passed to `run_failure_propagation_pipeline`; this is
caller-trusted, not runtime-verified, matching `compute_route_change`'s own
existing trust convention in `path_engine.py`.

Six decisions, each resolved firmly rather than left implicit:

- `connectivity_ratio` = post-failure largest-component size / pre-failure
  largest-component size. Self-relative to the pre-failure main body, so it
  measures what *this* failure did, not pre-existing fragmentation. Always in
  [0,1] since a failure only ever removes nodes/edges, never adds them; `1.0`
  for a zero-node graph, mirroring `compute_connectivity`'s own convention.

- `reachable_node_ratio` is a deliberately different axis, not a duplicate:
  the fraction of *every originally-present* node that ends up in *any*
  post-failure component of size >= 2 (every healthy island, not just the
  largest). A stranded singleton is honestly `0` -- it has no peer to
  communicate with. The two ratios coincide whenever the post-failure graph
  stays one component and diverge whenever a failure splits it into several
  still-functional islands (see the bowtie-graph test).

- `affected_service_count` = `len(result.service_impacts)` directly -- Phase
  61 already deduplicates that list per node.

- `path_degradation_score` sums (not averages, matching `affected_service_
  count`'s own raw-count convention) over `result.route_changes`: a pair with
  no `baseline_path` contributes `0.0` (nothing existed to degrade); a pair
  whose `current_path` fully collapsed contributes a fixed
  `_UNREACHABLE_PATH_PENALTY` rather than silently `0` or an unserializable
  `float('inf')`; every other pair contributes `max(cost_delta, 0.0)` (only
  worsening counts).

- `bottleneck_node_ids` is the *diff* of Phase 55 articulation points
  (pre-failure graph vs. post-failure graph), not the raw post-failure set --
  read literally against the spec's own word "emergence." A node that was
  already a structural single point of failure before any simulated failure
  is a pre-existing weakness `docs/architecture/criticality_analysis.md`
  already deliberately left unscored, not something this failure caused.

- `alternative_path_available` checks, over the same bounded pair set Phase
  61 already derived (`route_changes`), whether any still-reachable pair has
  a genuine second route via Yen's algorithm (`compute_alternate_paths(...,
  k=2, ...) ` returning >= 2 paths) -- a distinct signal from mere
  reachability (`reachable_node_ratio`). Empty `route_changes` yields `False`,
  an honest "no evidence gathered," never a fabricated `True`.

Never imports `simulator.ground_truth` (spec §4;
`scripts/check_ground_truth_boundary.py` would reject it if it did).
"""

from __future__ import annotations

import math
from typing import Set

from backend.app.models.failure import ResilienceIndicators
from backend.app.models.topology import TopologyGraph
from backend.dependency.criticality import compute_graph_criticality
from backend.simulation.failure_propagation_pipeline import FailurePipelineResult
from backend.simulation.path_engine import RouteChange, compute_alternate_paths

_UNREACHABLE_PATH_PENALTY = -math.log(1e-9)  # ~20.72; same -log(confidence) unit as path_engine.py


def _connectivity_ratio(result: FailurePipelineResult) -> float:
    before_size = len(result.connectivity_before.largest_component_node_ids)
    after_size = len(result.connectivity_after.largest_component_node_ids)
    if before_size == 0:
        return 1.0
    return after_size / before_size


def _reachable_node_ratio(result: FailurePipelineResult) -> float:
    original_node_ids: Set[str] = {
        node_id for component in result.connectivity_before.components for node_id in component
    }
    if not original_node_ids:
        return 1.0
    reachable_node_ids = {
        node_id
        for component in result.connectivity_after.components
        if len(component) >= 2
        for node_id in component
    }
    return len(reachable_node_ids) / len(original_node_ids)


def _route_degradation(route_change: RouteChange) -> float:
    if route_change.baseline_path is None:
        return 0.0
    if route_change.current_path is None:
        return _UNREACHABLE_PATH_PENALTY
    return max(route_change.cost_delta, 0.0)


def _path_degradation_score(result: FailurePipelineResult) -> float:
    return sum(_route_degradation(rc) for rc in result.route_changes)


def _bottleneck_node_ids(graph: TopologyGraph, result: FailurePipelineResult) -> list:
    pre_report = compute_graph_criticality(graph)
    post_report = compute_graph_criticality(result.injection.graph)
    pre_articulation_ids = {ns.node_id for ns in pre_report.node_scores if ns.is_articulation_point}
    post_articulation_ids = {ns.node_id for ns in post_report.node_scores if ns.is_articulation_point}
    return sorted(post_articulation_ids - pre_articulation_ids)


def _alternative_path_available(result: FailurePipelineResult) -> bool:
    for route_change in result.route_changes:
        if route_change.current_path is None:
            continue
        alternate_paths = compute_alternate_paths(
            result.injection.graph,
            route_change.source_node_id,
            route_change.target_node_id,
            k=2,
            failure=result.injection,
        )
        if len(alternate_paths) >= 2:
            return True
    return False


def compute_resilience_indicators(
    graph: TopologyGraph,
    result: FailurePipelineResult,
) -> ResilienceIndicators:
    """Aggregates a Phase 61 `FailurePipelineResult` (plus the pre-failure
    `graph` it was computed from) into `ResilienceIndicators`. Never mutates
    either argument; re-runs no injection/propagation/routing stage.
    """
    return ResilienceIndicators(
        scenario_id=result.scenario.scenario_id,
        connectivity_ratio=_connectivity_ratio(result),
        reachable_node_ratio=_reachable_node_ratio(result),
        affected_service_count=len(result.service_impacts),
        path_degradation_score=_path_degradation_score(result),
        bottleneck_node_ids=_bottleneck_node_ids(graph, result),
        alternative_path_available=_alternative_path_available(result),
    )
