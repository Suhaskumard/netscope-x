# NETSCOPE-X — Dynamic Path Engine

Phase 60 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 60 — DYNAMIC PATH ENGINE"):
"compute shortest paths, alternate paths, path costs, route changes, and disconnected components on
the (possibly failure-modified) graph."

FR-1.33: *"The system shall compute shortest paths, alternate paths, path costs, route changes, and
disconnected components on the (possibly failure-modified) graph (spec Phase 60)."*

Code: new `backend/simulation/path_engine.py` (`PathResult`, `ConnectivityResult`, `RouteChange`,
`compute_shortest_path`, `compute_alternate_paths`, `compute_connectivity`,
`compute_route_change`).

## Algorithms: already selected at Phase 05, not reinvented here

`algorithm_selection.md` section 5 already committed to Dijkstra (weighted shortest path), Yen's
algorithm bounded K (alternate paths), and BFS/union-find (connectivity). NetworkX — already a
project dependency since Phase 55's `criticality.py` — supplies all three directly:
`nx.shortest_path` (Dijkstra under a weighted graph), `nx.shortest_simple_paths` (Yen's algorithm,
a generator yielding paths in strictly increasing cost order — nothing here reimplements it),
`nx.connected_components`. The `TopologyGraph -> nx.Graph` conversion follows `criticality.py`'s own
`_build_graph` pattern (node ids map directly, no remapping).

## Edge weight: a genuinely probabilistic cost, not an arbitrary scale

Base cost is `-log(confidence)`, clamped away from 0/1 to stay finite. This is the standard,
principled dual of "probability along a path multiplies, cost along a path adds": a path's total
weight is `-log` of its overall confidence product, so Dijkstra/Yen's minimizing summed cost is
exactly maximizing route confidence — not an unrelated number bolted onto the graph.

For an edge marked in a Phase 59 `FailureInjectionResult.degraded_edge_ids`:
- `PACKET_LOSS` / `BANDWIDTH_REDUCTION` add `-log(1 - ratio)` — the *same unit* as the base cost,
  treating the ratio as an additional independent failure probability for that edge.
- `LATENCY_INJECTION` adds `latency_ms / _DEFAULT_LATENCY_COST_SCALE` (`100.0`, a documented
  provisional constant — same "provisional, uncalibrated pending Phase 68" status as
  `_DEFAULT_PACKET_SCALE` and its siblings elsewhere in this project).
- `SERVICE_DEGRADATION` carries no quantitative field on `FailureScenario` at all — the edge stays
  recorded in `degraded_edge_ids` but contributes no extra cost here. A documented limitation, not
  an invented number.

A `failure` argument's `.graph` must equal the `graph` argument passed alongside it — an internally
inconsistent call raises `ValueError`, the same fail-fast stance Phase 59 already takes for its own
guards.

## A missing source/target is deliberately not an error

Unlike Phase 59's "unknown scenario target" guard (a malformed *request*), the single most important
real case this module must handle is a route-change query where a `NODE_FAILURE` removed the very
node being asked about — the honest answer is "no path" (`None`), not a crash. This mirrors the
archaeology layer's own "missing means empty" convention (Phase 44/47/49) rather than Phase 59's
stricter one: the two situations are genuinely different — Phase 59 validates a scenario's own
internal consistency before acting; this module answers a reachability question where "the node
isn't there" is itself a valid, common answer.

## "Route changes": an interpretation, not literal spec text

FR-1.33 names "route changes" without elaborating what baseline it's compared against anywhere in
the spec or its own docs. The reading adopted here — the only self-consistent one — is: the
shortest path for a given `(source, target)` pair on a baseline graph vs. on a current (possibly
failure-modified) graph. `compute_route_change` reports whether the path itself changed (including
reachability flipping either direction) and the real cost delta when both sides are reachable.

## What this phase deliberately does NOT do

- **No pipeline composition.** Feeding a real `FailureScenario` through injection, then through this
  path engine, then into Phase 54's `propagate_failure`, as one connected operation, is explicitly
  FR-1.34's job (Phase 61).
- **No resilience indicators.** `ResilienceIndicators` (connectivity ratio, reachable-node ratio,
  bottleneck detection) is Phase 62's job — this phase only supplies the raw path/connectivity
  primitives those metrics would be computed from.
- **No API wiring.** `POST /simulation` stays `NotYetImplemented`, scoped "Phase 59-61" in its own
  docstring.

## Worked example

The diamond topology A→B→D (confidence 0.9/0.9, cheap) and A→C→D (confidence 0.5/0.5, expensive):

```
compute_shortest_path(graph, "A", "D")
# node_ids: [A, B, D], cost = -log(0.9) - log(0.9) ≈ 0.211

compute_alternate_paths(graph, "A", "D", k=5)
# [A, B, D] (cost ≈ 0.211), then [A, C, D] (cost ≈ 1.386) -- in increasing cost order

# NODE_FAILURE on B:
failure = apply_failure_scenario(graph, FailureScenario(..., failure_type=NODE_FAILURE, target_node_id="B"))
compute_route_change(graph, failure.graph, "A", "D", failure=failure)
# changed: True
# baseline_path: [A, B, D]
# current_path: [A, C, D]  (rerouted through the surviving path)
# cost_delta: current.cost - baseline.cost > 0
```

## Verification actually performed this phase

- `pytest backend/tests/test_path_engine.py -v` — **15/15 passed**: shortest-path cost matches the
  `-log(confidence)` sum exactly (`pytest.approx`); `None` for a disconnected pair and for a missing
  source/target node; alternate paths on a diamond topology returned in strictly increasing cost
  order and bounded by `k`; empty alternate-path list when disconnected; connectivity correctly
  reports two components vs. one fully-connected component; a route-change test composing a real
  `apply_failure_scenario` `NODE_FAILURE` shows the reroute from the cheap to the expensive diamond
  path with a positive real cost delta; a second route-change test shows total disconnection
  (`current_path=None`, `cost_delta=None`); an unmodified route reports `changed=False`; latency
  injection increases cost by exactly `latency_ms / 100.0`; packet loss increases cost by exactly
  `-log(1 - packet_loss_ratio)`; a mismatched `failure.graph` raises `ValueError`; a real end-to-end
  run over a topology discovered from synthetic packets confirms an `EDGE_FAILURE` on the only
  connecting edge makes `compute_shortest_path` correctly return `None`.
- Full repo suite (`pytest backend/tests experiments/tests simulator/tests`, run from repo root) —
  **508/508 passed** (up from 493/493), no regressions.
- `python -m scripts.validate_data_contracts` — 38/38 passed, no regression (no schema changes this
  phase).
- `python -m scripts.check_ground_truth_boundary` — clean.

## Status

The dynamic path engine (spec Phase 60, FR-1.33) is implemented and unit-verified: shortest paths,
bounded alternate paths, connectivity/disconnected-component analysis, and route-change comparison
all operate over any `TopologyGraph`, with edge weight honestly derived from confidence and Phase
59's failure-injection outputs where applicable. No API route exists yet. Composing this into the
full failure→propagation→routing→service-impact pipeline (Phase 61) and computing resilience
indicators from it (Phase 62) remain ahead.
