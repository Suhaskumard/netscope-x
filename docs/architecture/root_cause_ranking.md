# Root-Cause Ranking with Counterfactual Explanations (Phase 101)

`POST /api/v1/investigation/root-cause {capture_id, failed_node_id, max_candidates?}` (`backend/nlq/rootcause.py`).

1. Y = `newly_unreachable_node_ids` from the real Phase 61 pipeline failing `failed_node_id`.
2. For each candidate X (every other node via REMOVE_NODE, every edge via REMOVE_EDGE, capped by `max_candidates`) a real
   `CounterfactualScenario` is run through `execute_counterfactual_scenario` and `compare_counterfactual_outcome`.
3. The same failure is re-run on the counterfactual graph. `prevented_node_ids` = nodes of Y still present there and no longer
   newly unreachable. X is never counted as prevented. `collateral_unreachable_node_ids` is what removing X alone cuts off.
4. Rank by prevented fraction, then least collateral, then id. The explanation is a deterministic template; no LLM.

Each item exposes `scenario_id`, `isolated_graph_id`, removed ids and the prevented set so it can be re-executed.

## Verified
Tests spy the engine (every ranked scenario was executed) and re-execute each one independently, recomputing the prevented set and
score. Determinism, ordering, no mutation of the input graph, 404/422 are covered.

## Limits
Structural, on the reconstructed graph; not proof of real-world causation (the response carries a caveat). Y is routing
reachability only, not causal-propagation impacts (those come from dependency candidates, which graph edits do not change). Only
single removals; no combinations.
