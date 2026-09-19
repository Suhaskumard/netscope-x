"""Failure Propagation Graph (spec Phase 54, FR-1.28: "represent failure
propagation as a multi-order impact graph (primary -> secondary -> tertiary
impact)").

`backend/app/models/failure.py`'s `PropagationImpact` (Phase 04) -- with
`ImpactOrder.PRIMARY`/`SECONDARY`/`TERTIARY` the master spec's own bullet
list verbatim -- has never been constructed anywhere until this phase.
`FailureScenario` (the failure-injection request) and `POST /simulation`
are both explicitly scoped to "spec Phase 59-61" in their own docstrings --
this phase needs only the simplest possible representation of "what
failed" (a node id), not that later machinery.

A real design decision: this propagates over `List[CausalCandidate]`
(Phase 53), not raw `List[DependencyEdge]` (Phase 50-51). `Edge`/
`DependencyEdge.source_node_id`/`target_node_id` are undirected --
`discover_edges` assigns them by alphabetically sorting the node-id pair
(`backend/nettrace/topology/edges.py`), not by any real dependency
direction. Propagating along a raw `DependencyEdge`'s `source -> target`
would often mean following a direction with zero supporting evidence (a
`temporal_precedence_score` of exactly `0.0`) -- an artifact of
alphabetical sorting, not a causal claim. `CausalCandidate`s are exactly
the subset of `DependencyEdge`s where `source -> target` carries genuine,
positive temporal-precedence evidence for that specific direction -- the
only edge set in this codebase where "if source fails, target is
impacted" is actually justified by real evidence.

Never imports `simulator.ground_truth` (spec §4;
`scripts/check_ground_truth_boundary.py` would reject it if it did).
"""

from __future__ import annotations

from typing import Dict, List

from backend.app.models.failure import ImpactOrder, PropagationImpact
from backend.dependency.causal_candidates import CausalCandidate

_SECONDARY_AND_TERTIARY = (ImpactOrder.SECONDARY, ImpactOrder.TERTIARY)


def propagate_failure(
    candidates: List[CausalCandidate],
    scenario_id: str,
    failed_node_id: str,
) -> List[PropagationImpact]:
    """Represents `failed_node_id`'s failure as a multi-order impact graph:
    the failed node itself (`PRIMARY`), every node reached by one
    `CausalCandidate` hop from it (`SECONDARY`), and every node reached by
    one more hop from those (`TERTIARY`) -- exactly three orders, matching
    the spec's own bullet list; no further cascading is attempted (a
    plausible future enhancement, not built here).

    A breadth-first traversal over `source_node_id -> target_node_id`:
    each node is visited at most once (the first order/candidate that
    reaches it wins), so a cycle can never loop and a diamond-shaped
    candidate graph never double-counts a node. Processing order is fully
    deterministic (frontier nodes sorted by node id; each node's outgoing
    candidates sorted by `dependency_id`), so results are reproducible.

    Always returns at least the primary impact, even if `candidates` is
    empty or `failed_node_id` has no outgoing candidates -- never an
    error.
    """
    by_source: Dict[str, List[CausalCandidate]] = {}
    for candidate in candidates:
        by_source.setdefault(candidate.source_node_id, []).append(candidate)
    for edges in by_source.values():
        edges.sort(key=lambda c: c.dependency_id)

    visited = {failed_node_id}
    impacts: List[PropagationImpact] = [
        PropagationImpact(
            scenario_id=scenario_id,
            affected_node_id=failed_node_id,
            order=ImpactOrder.PRIMARY,
            caused_by_node_id=None,
            evidence=[f"{failed_node_id} is the primary failure"],
        )
    ]

    frontier = [failed_node_id]
    for order in _SECONDARY_AND_TERTIARY:
        next_frontier: List[str] = []
        for node in sorted(frontier):
            for candidate in by_source.get(node, []):
                if candidate.target_node_id in visited:
                    continue
                visited.add(candidate.target_node_id)
                impacts.append(
                    PropagationImpact(
                        scenario_id=scenario_id,
                        affected_node_id=candidate.target_node_id,
                        order=order,
                        caused_by_node_id=node,
                        evidence=[
                            f"impact propagates from {node} via a causal candidate "
                            f"(strength={candidate.strength:.3f}, "
                            f"temporal_precedence={candidate.temporal_precedence_score:.3f})"
                        ],
                    )
                )
                next_frontier.append(candidate.target_node_id)
        frontier = next_frontier

    return impacts
