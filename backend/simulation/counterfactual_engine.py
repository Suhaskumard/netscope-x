"""Counterfactual Graph Engine (spec Phase 65, FR-1.36 second half: "execute
counterfactuals on an isolated alternate graph state that never mutates the
real baseline").

Mirrors `apply_failure_scenario` (Phase 59, `backend/simulation/
failure_injection.py`) wherever the six `CounterfactualAction` verbs
(Phase 64, `backend/app/models/simulation.py`) are directly analogous to a
`FailureType`: `REMOVE_NODE`/`REMOVE_EDGE` structurally remove; `INCREASE_
LATENCY`/`REDUCE_BANDWIDTH`/`INCREASE_TRAFFIC` leave the graph structurally
unchanged and only mark `degraded_edge_ids` (no path-cost computation here --
explicitly Phase 66's job, exactly as it was Phase 60's job for failure
injection). `REDUCE_BANDWIDTH`'s "target_node_id or target_edge_id" ambiguity
needs no extra guard here, unlike Phase 59's own patch for `FailureScenario`
-- Phase 64 already closed that gap at the schema level.

Two things are genuinely new relative to the `FailureScenario` precedent:

1. `CounterfactualScenario` already carries `baseline_graph_id`/
   `isolated_graph_id` (Phase 04, validated distinct since Phase 04). This
   module validates `scenario.baseline_graph_id == graph.graph_id` up front
   (`ValueError` on mismatch, the same fail-fast stance Phase 59 already
   takes) and uses `scenario.isolated_graph_id` directly as the resulting
   graph's `graph_id` -- not synthesized, since the schema already reserved
   this field for exactly this purpose.

2. `ADD_ROUTE` synthesizes a genuinely new `Edge` -- no precedent exists for
   a non-empirically-observed `Edge` anywhere except `simulator/ground_truth/
   generate.py`'s *declared* edges (`confidence=1.0`, `evidence=["ground
   truth: declared lab architecture..."]`). That precedent's *mechanism*
   (fill every required field, name the real justification in `evidence`) is
   reused; its *confidence value* is not -- ground truth is declared-and-
   certain, while a counterfactual `ADD_ROUTE` is explicitly hypothetical.
   RQ7 (`docs/research/research_questions.md`) is direct on this point:
   "report the prediction as unvalidated rather than implying it was
   tested." So this module uses a documented, fixed, neutral confidence
   (`_HYPOTHETICAL_ROUTE_CONFIDENCE`), deliberately distinct from ground
   truth's `1.0`, with `evidence` stating plainly that the edge is a
   counterfactual construct, not an observation. `magnitude` is deliberately
   NOT repurposed as a confidence value -- it has no documented meaning for
   `ADD_ROUTE` (`docs/architecture/counterfactual_scenario_language.md`
   says so explicitly), and overloading it would violate this codebase's
   "explicit over implicit/overloaded fields" convention. `observation_count`
   is set to the schema's structural minimum (`ge=1`), documented as *not*
   meaning "observed once" the way real inference means it -- purely
   satisfying the constraint for a declared/hypothetical construct, mirroring
   ground truth's own use of the same minimum for the same structural
   reason. `protocols` gets an explicit `["unknown"]` placeholder rather
   than a guess, since no protocol is claimed or knowable for a hypothetical
   route. `ADD_ROUTE` also requires that no edge already connects the two
   nodes in either direction (undirected, per Phase 30's convention) --
   RQ7's own framing of `ADD_ROUTE` is specifically "a purely hypothetical
   route that doesn't exist"; adding one that already exists would be
   incoherent, not merely redundant.

Never mutates its input `TopologyGraph` -- mirrors every prior phase's
"recompute fresh, never mutate in place" convention. Never imports
`simulator.ground_truth` (spec §4; `scripts/check_ground_truth_boundary.py`
would reject it if it did) -- the declared-edge *pattern* is reused, not the
code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from backend.app.models.simulation import CounterfactualAction, CounterfactualScenario
from backend.app.models.topology import Edge, Node, TopologyGraph

_HYPOTHETICAL_ROUTE_CONFIDENCE = 0.5  # neutral: neither claims nor denies real evidence, unlike
                                       # ground truth's declared confidence=1.0 (documented, not arbitrary)


@dataclass(frozen=True)
class CounterfactualExecutionResult:
    scenario: CounterfactualScenario
    graph: TopologyGraph
    removed_node_ids: List[str]
    removed_edge_ids: List[str]
    degraded_edge_ids: List[str]
    added_edge_id: Optional[str]


def _incident_edge_ids(edges: List[Edge], node_id: str) -> List[str]:
    return sorted(e.edge_id for e in edges if node_id in (e.source_node_id, e.target_node_id))


def _connected(edges: List[Edge], node_a: str, node_b: str) -> bool:
    return any({e.source_node_id, e.target_node_id} == {node_a, node_b} for e in edges)


def execute_counterfactual_scenario(
    graph: TopologyGraph, scenario: CounterfactualScenario
) -> CounterfactualExecutionResult:
    """Applies `scenario` to `graph`, returning an isolated copy (`graph_id
    = scenario.isolated_graph_id`) plus the real record of what was
    removed, marked degraded, or added.

    Raises `ValueError` for a `baseline_graph_id` that doesn't match
    `graph.graph_id`, a `target_node_id`/`target_edge_id`/`source_node_id`
    that doesn't exist in `graph`, or an `ADD_ROUTE` whose two endpoints
    are already connected by an existing edge -- all genuinely inconsistent
    requests, not silently accepted.
    """
    if scenario.baseline_graph_id != graph.graph_id:
        raise ValueError(
            f"scenario.baseline_graph_id {scenario.baseline_graph_id!r} does not match graph.graph_id {graph.graph_id!r}"
        )

    node_ids = {n.node_id for n in graph.nodes}
    edge_ids = {e.edge_id for e in graph.edges}

    if scenario.target_node_id is not None and scenario.target_node_id not in node_ids:
        raise ValueError(f"target_node_id {scenario.target_node_id!r} not present in this graph")
    if scenario.target_edge_id is not None and scenario.target_edge_id not in edge_ids:
        raise ValueError(f"target_edge_id {scenario.target_edge_id!r} not present in this graph")
    if scenario.source_node_id is not None and scenario.source_node_id not in node_ids:
        raise ValueError(f"source_node_id {scenario.source_node_id!r} not present in this graph")

    removed_node_ids: List[str] = []
    removed_edge_ids: List[str] = []
    degraded_edge_ids: List[str] = []
    added_edge_id: Optional[str] = None
    extra_edge: Optional[Edge] = None

    if scenario.action == CounterfactualAction.REMOVE_NODE:
        removed_node_ids = [scenario.target_node_id]
        removed_edge_ids = _incident_edge_ids(graph.edges, scenario.target_node_id)
    elif scenario.action == CounterfactualAction.REMOVE_EDGE:
        removed_edge_ids = [scenario.target_edge_id]
    elif scenario.action in (CounterfactualAction.INCREASE_LATENCY, CounterfactualAction.INCREASE_TRAFFIC):
        degraded_edge_ids = _incident_edge_ids(graph.edges, scenario.target_node_id)
    elif scenario.action == CounterfactualAction.REDUCE_BANDWIDTH:
        if scenario.target_edge_id is not None:
            degraded_edge_ids = [scenario.target_edge_id]
        else:
            degraded_edge_ids = _incident_edge_ids(graph.edges, scenario.target_node_id)
    elif scenario.action == CounterfactualAction.ADD_ROUTE:
        if _connected(graph.edges, scenario.source_node_id, scenario.target_node_id):
            raise ValueError(
                f"ADD_ROUTE endpoints {scenario.source_node_id!r} and {scenario.target_node_id!r} "
                "are already connected by an existing edge"
            )
        added_edge_id = f"{scenario.isolated_graph_id}:added-route:{scenario.scenario_id}"
        extra_edge = Edge(
            edge_id=added_edge_id,
            source_node_id=scenario.source_node_id,
            target_node_id=scenario.target_node_id,
            confidence=_HYPOTHETICAL_ROUTE_CONFIDENCE,
            evidence=[
                f"hypothetical route added by counterfactual scenario {scenario.scenario_id}; "
                "not empirically observed"
            ],
            observation_count=1,
            first_observed=scenario.created_at,
            last_observed=scenario.created_at,
            protocols=["unknown"],
        )

    remaining_nodes: List[Node] = [n for n in graph.nodes if n.node_id not in removed_node_ids]
    remaining_edges: List[Edge] = [e for e in graph.edges if e.edge_id not in removed_edge_ids]
    if extra_edge is not None:
        remaining_edges = remaining_edges + [extra_edge]

    isolated_graph = TopologyGraph(
        graph_id=scenario.isolated_graph_id,
        generated_at=graph.generated_at,
        nodes=remaining_nodes,
        edges=remaining_edges,
    )

    return CounterfactualExecutionResult(
        scenario=scenario,
        graph=isolated_graph,
        removed_node_ids=removed_node_ids,
        removed_edge_ids=removed_edge_ids,
        degraded_edge_ids=degraded_edge_ids,
        added_edge_id=added_edge_id,
    )
