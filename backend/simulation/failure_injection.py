"""Controlled Failure Injection (spec Phase 59, FR-1.32: "support
controlled failure injection: node failure, edge failure, latency,
packet loss, bandwidth reduction, service degradation").

`backend/app/models/failure.py`'s `FailureScenario`/`FailureType` (Phase
04) -- the master spec's own six-item list verbatim -- have never been
applied to a real `TopologyGraph` anywhere until this phase. No new
schema is added; both are reused exactly as already constrained.

`TopologyGraph`/`Edge` (Phase 04/29-32) carry no latency/packet-loss/
bandwidth/degradation fields -- entirely new territory, and deliberately
left that way here. `algorithm_selection.md` section 5 already scopes
"edge weights derived from confidence/latency estimates" and path-cost
computation to Phase 60 (Dynamic Path Engine); this phase only decides
WHICH edges a soft failure affects (`degraded_edge_ids`), never how much
they should cost afterward. Likewise, composing injection with Phase
54's `propagate_failure` into one pipeline is explicitly FR-1.34's job
(Phase 61) -- `propagate_failure` is not called here.

A simulated failure is applied to an isolated graph copy
(`algorithm_selection.md` section 5) -- `apply_failure_scenario` never
mutates its input `TopologyGraph`, mirroring every other phase's
"recompute fresh, never mutate in place" convention (Phase 45's
`diff_snapshots`, Phase 57's `build_digital_twin`).

`FailureScenario`'s own validator already requires a target for four of
six failure types (`NODE_FAILURE`/`LATENCY_INJECTION`/
`SERVICE_DEGRADATION` -> `target_node_id`; `EDGE_FAILURE` ->
`target_edge_id`), but deliberately leaves `PACKET_LOSS`/
`BANDWIDTH_REDUCTION` untargeted at the schema level -- either field, or
neither, satisfies it. This phase adds its own guard for "neither": a
ratio with nothing to apply it to is a genuinely inconsistent request,
not something to silently accept, the same fail-fast stance Phase 46/56
already take for their own mismatched-input cases.

Never imports `simulator.ground_truth` (spec §4;
`scripts/check_ground_truth_boundary.py` would reject it if it did).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from backend.app.models.failure import FailureScenario, FailureType
from backend.app.models.topology import Edge, Node, TopologyGraph

_NODE_TARGETED_TYPES = (
    FailureType.NODE_FAILURE,
    FailureType.LATENCY_INJECTION,
    FailureType.SERVICE_DEGRADATION,
)
_UNTARGETED_RATIO_TYPES = (FailureType.PACKET_LOSS, FailureType.BANDWIDTH_REDUCTION)


@dataclass(frozen=True)
class FailureInjectionResult:
    scenario: FailureScenario
    graph: TopologyGraph
    removed_node_ids: List[str]
    removed_edge_ids: List[str]
    degraded_edge_ids: List[str]


def _incident_edge_ids(edges: List[Edge], node_id: str) -> List[str]:
    return sorted(e.edge_id for e in edges if node_id in (e.source_node_id, e.target_node_id))


def apply_failure_scenario(graph: TopologyGraph, scenario: FailureScenario) -> FailureInjectionResult:
    """Applies `scenario` to `graph`, returning an isolated copy plus the
    real, evidenced record of what was removed or marked degraded.

    Raises `ValueError` for a `target_node_id`/`target_edge_id` that
    doesn't exist in `graph`, and for a `PACKET_LOSS`/
    `BANDWIDTH_REDUCTION` scenario with neither target set -- both
    genuinely inconsistent requests, not silently accepted.
    """
    node_ids = {n.node_id for n in graph.nodes}
    edge_ids = {e.edge_id for e in graph.edges}

    if scenario.target_node_id is not None and scenario.target_node_id not in node_ids:
        raise ValueError(f"target_node_id {scenario.target_node_id!r} not present in this graph")
    if scenario.target_edge_id is not None and scenario.target_edge_id not in edge_ids:
        raise ValueError(f"target_edge_id {scenario.target_edge_id!r} not present in this graph")

    removed_node_ids: List[str] = []
    removed_edge_ids: List[str] = []
    degraded_edge_ids: List[str] = []

    if scenario.failure_type == FailureType.NODE_FAILURE:
        removed_node_ids = [scenario.target_node_id]
        removed_edge_ids = _incident_edge_ids(graph.edges, scenario.target_node_id)
    elif scenario.failure_type == FailureType.EDGE_FAILURE:
        removed_edge_ids = [scenario.target_edge_id]
    elif scenario.failure_type in _NODE_TARGETED_TYPES:
        # LATENCY_INJECTION / SERVICE_DEGRADATION: the schema already
        # guarantees target_node_id is set for these.
        degraded_edge_ids = _incident_edge_ids(graph.edges, scenario.target_node_id)
    elif scenario.failure_type in _UNTARGETED_RATIO_TYPES:
        if scenario.target_edge_id is not None:
            degraded_edge_ids = [scenario.target_edge_id]
        elif scenario.target_node_id is not None:
            degraded_edge_ids = _incident_edge_ids(graph.edges, scenario.target_node_id)
        else:
            raise ValueError(
                f"{scenario.failure_type} requires target_node_id or target_edge_id to apply to"
            )

    remaining_nodes: List[Node] = [n for n in graph.nodes if n.node_id not in removed_node_ids]
    remaining_edges: List[Edge] = [e for e in graph.edges if e.edge_id not in removed_edge_ids]

    injected_graph = TopologyGraph(
        graph_id=f"{graph.graph_id}:failure:{scenario.scenario_id}",
        generated_at=graph.generated_at,
        nodes=remaining_nodes,
        edges=remaining_edges,
    )

    return FailureInjectionResult(
        scenario=scenario,
        graph=injected_graph,
        removed_node_ids=removed_node_ids,
        removed_edge_ids=removed_edge_ids,
        degraded_edge_ids=degraded_edge_ids,
    )
