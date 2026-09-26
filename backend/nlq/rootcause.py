"""Root-cause ranking with counterfactual explanations (spec addendum Phase 101).

"Removing X would have prevented Y" is reported only when a real counterfactual was executed and compared:

* Y is the real Phase 61 result of failing `failed_node_id` on the baseline graph (`newly_unreachable_node_ids`).
* For each candidate X (a node or edge other than the failed node) a real Phase 64 `CounterfactualScenario` is executed
  (`execute_counterfactual_scenario`, Phase 65) and compared with the baseline (`compare_counterfactual_outcome`, Phase 66).
* The same failure is then re-run through the real Phase 61 pipeline on the counterfactual graph. Y_prevented is the set of
  nodes in Y that are still present in the counterfactual graph and are no longer newly unreachable there. Nothing is estimated.

X itself is never counted as "prevented" (removing it trivially removes it). The result is structural, on the reconstructed
graph: it says the failure would not have cut those nodes off, not that X caused anything in the real network.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.app.models.failure import FailureScenario, FailureType
from backend.app.models.simulation import CounterfactualAction, CounterfactualScenario
from backend.app.models.topology import TopologyGraph
from backend.dependency.causal_candidates import CausalCandidate
from backend.simulation.counterfactual_comparison import compare_counterfactual_outcome
from backend.simulation.counterfactual_engine import execute_counterfactual_scenario
from backend.simulation.failure_propagation_pipeline import run_failure_propagation_pipeline

CAVEAT = (
    "Structural counterfactual on the reconstructed graph: it shows which nodes the failure would not have cut off, "
    "not that the removed element caused anything in the real network."
)


def _scenario(graph: TopologyGraph, sid: str, action: CounterfactualAction, node: Optional[str], edge: Optional[str]) -> CounterfactualScenario:
    return CounterfactualScenario(
        scenario_id=sid, action=action, baseline_graph_id=graph.graph_id, isolated_graph_id=f"{graph.graph_id}::{sid}",
        target_node_id=node, target_edge_id=edge, created_at=datetime.now(timezone.utc),
    )


def rank_root_causes(
    graph: TopologyGraph, failed_node_id: str, candidates: Optional[List[CausalCandidate]] = None, max_candidates: int = 50,
) -> Dict[str, Any]:
    """Executes one real counterfactual per candidate X and ranks them by the fraction of Y they prevent."""
    if failed_node_id not in {n.node_id for n in graph.nodes}:
        raise ValueError(f"unknown failed_node_id {failed_node_id!r}")
    candidates = candidates or []
    failure = FailureScenario(scenario_id="rc-failure", failure_type=FailureType.NODE_FAILURE, target_node_id=failed_node_id)
    baseline = run_failure_propagation_pipeline(graph, failure, candidates)
    y = sorted(baseline.newly_unreachable_node_ids)

    options: List[tuple] = [(CounterfactualAction.REMOVE_NODE, n.node_id, None) for n in sorted(graph.nodes, key=lambda n: n.node_id) if n.node_id != failed_node_id]
    options += [(CounterfactualAction.REMOVE_EDGE, None, e.edge_id) for e in sorted(graph.edges, key=lambda e: e.edge_id)]
    options = options[:max_candidates]

    ranked: List[Dict[str, Any]] = []
    for i, (action, node, edge) in enumerate(options):
        cf = _scenario(graph, f"rc-{i}", action, node, edge)
        execution = execute_counterfactual_scenario(graph, cf)
        comparison = compare_counterfactual_outcome(graph, execution, candidates)
        rerun = run_failure_propagation_pipeline(execution.graph, failure, candidates)
        present = {n.node_id for n in execution.graph.nodes}
        still = set(rerun.newly_unreachable_node_ids)
        prevented = sorted(n for n in y if n in present and n not in still)
        target = node or edge
        ranked.append({
            "candidate": target, "action": action.value, "scenario_id": cf.scenario_id,
            "isolated_graph_id": execution.graph.graph_id, "removed_node_ids": execution.removed_node_ids,
            "removed_edge_ids": execution.removed_edge_ids, "prevented_node_ids": prevented,
            "score": len(prevented) / len(y) if y else 0.0,
            "collateral_unreachable_node_ids": sorted(comparison.newly_unreachable_node_ids),
            "explanation": (f"Removing {action.value.split('_')[1].lower()} {target} would have prevented {', '.join(prevented)} "
                            f"from being cut off when {failed_node_id} fails." if prevented else
                            f"Removing {action.value.split('_')[1].lower()} {target} would not have prevented any node from being cut off."),
        })
    ranked.sort(key=lambda r: (-r["score"], len(r["collateral_unreachable_node_ids"]), r["candidate"]))
    for rank, item in enumerate(ranked, 1):
        item["rank"] = rank
    return {"failed_node_id": failed_node_id, "impacted_node_ids": y, "ranking": ranked, "caveat": CAVEAT}
