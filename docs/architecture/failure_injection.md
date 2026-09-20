# NETSCOPE-X — Controlled Failure Injection

Phase 59 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 59 — CONTROLLED FAILURE
INJECTION"): "support controlled failure injection: node failure, edge failure, latency, packet
loss, bandwidth reduction, service degradation."

FR-1.32: *"The system shall support controlled failure injection: node failure, edge failure,
latency, packet loss, bandwidth reduction, service degradation (spec Phase 59)."*

Code: new package `backend/simulation/`, `backend/simulation/failure_injection.py`
(`FailureInjectionResult`, `apply_failure_scenario`) — the first real construction of
`backend/app/models/failure.py`'s `FailureScenario`/`FailureType` (Phase 04) against a real
`TopologyGraph`.

## No new schema — `FailureScenario`/`FailureType` already model FR-1.32 exactly

`FailureType` already enumerates the spec's six items verbatim. `FailureScenario`'s own
`model_validator` already requires a target per type: `NODE_FAILURE`/`LATENCY_INJECTION`/
`SERVICE_DEGRADATION` require `target_node_id`; `EDGE_FAILURE` requires `target_edge_id`;
`PACKET_LOSS` requires `packet_loss_ratio`; `BANDWIDTH_REDUCTION` requires
`bandwidth_reduction_ratio`. Notably, the validator does **not** force a target for
`PACKET_LOSS`/`BANDWIDTH_REDUCTION` — either `target_edge_id`, `target_node_id`, or neither
satisfies the schema alone. This phase adds its own guard for "neither": a ratio with nothing to
apply it to is a genuinely inconsistent request, not silently accepted — the same fail-fast stance
Phase 46/56 already take for their own mismatched-input cases.

## `apply_failure_scenario(graph, scenario) -> FailureInjectionResult`

One case per `FailureType`, each doing the minimum honest thing the schema actually supports:

- **`NODE_FAILURE`**: removes the target node and every edge incident to it — both to satisfy
  `TopologyGraph`'s own `_edges_reference_known_nodes` validator, and because a failed node cannot
  carry traffic on any incident link.
- **`EDGE_FAILURE`**: removes only the target edge; both endpoint nodes remain.
- **`LATENCY_INJECTION` / `SERVICE_DEGRADATION`**: no structural removal —
  `degraded_edge_ids` = every edge incident to the target node, still present in the returned
  graph.
- **`PACKET_LOSS` / `BANDWIDTH_REDUCTION`**: degrades the target edge if one is given; otherwise
  every edge incident to the target node; raises `ValueError` if neither is given.

An unknown `target_node_id`/`target_edge_id` (not present in the given graph) raises `ValueError`
for every applicable type — validated once, up front, before any mutation logic runs.

Returns `FailureInjectionResult(scenario, graph, removed_node_ids, removed_edge_ids,
degraded_edge_ids)`: `graph` is a genuinely new `TopologyGraph` (`graph_id` suffixed with
`:failure:<scenario_id>`), built from filtered node/edge lists — the input graph is never mutated,
mirroring `algorithm_selection.md` section 5's "applied to an isolated graph copy" design and every
other phase's "recompute fresh, never mutate in place" convention (Phase 45's `diff_snapshots`,
Phase 57's `build_digital_twin`).

## What this phase deliberately does NOT do

- **No path-cost weighting.** `TopologyGraph`/`Edge` carry no latency/packet-loss/bandwidth field
  to weight paths by — `algorithm_selection.md` section 5 explicitly scopes "edge weights derived
  from confidence/latency estimates" to Phase 60 (Dynamic Path Engine). `degraded_edge_ids` tells
  Phase 60 *which* edges a soft failure affects; the magnitude is already on `scenario` itself
  (`latency_ms`/`packet_loss_ratio`/`bandwidth_reduction_ratio`) for Phase 60 to read directly —
  nothing new is computed or stored for it here.
- **No composition with `propagate_failure`.** Phase 54's `propagate_failure` already handles "what
  happens downstream of a failed node" over `CausalCandidate`s. Wiring injection into that pipeline
  is explicitly FR-1.34's job (Phase 61, "a connected pipeline"), not attempted here.
- **No API wiring.** `POST /simulation` stays `NotYetImplemented`, explicitly scoped "Phase 59-61"
  in its own docstring — consistent with Phase 57/58's own "no route yet" precedent, since Phase
  60/61 aren't built.

## Worked example

A star topology (H connects to A, B, C):

```
apply_failure_scenario(graph, FailureScenario(scenario_id="s1", failure_type=NODE_FAILURE, target_node_id="H"))
# removed_node_ids: ["H"]
# removed_edge_ids: ["e0", "e1", "e2"]   (every edge incident to H)
# degraded_edge_ids: []
# result.graph: A, B, C only, no edges

apply_failure_scenario(graph, FailureScenario(scenario_id="s2", failure_type=LATENCY_INJECTION, target_node_id="H", latency_ms=50))
# removed_node_ids: []
# removed_edge_ids: []
# degraded_edge_ids: ["e0", "e1", "e2"]  (structure unchanged; Phase 60 will weight these by latency_ms)
```

## Verification actually performed this phase

- `pytest backend/tests/test_failure_injection.py -v` — **11/11 passed**: node failure removes the
  node and exactly its incident edges; edge failure removes only that edge; latency
  injection/service degradation leave the graph structurally identical but mark every incident edge
  as degraded; packet loss/bandwidth reduction degrade the targeted edge, or every edge incident to
  a targeted node, or raise `ValueError` when neither target is given; an unknown
  `target_node_id`/`target_edge_id` raises `ValueError`; the returned graph is a genuinely new
  object and the input graph is unchanged after the call; a real end-to-end run over a topology
  discovered from synthetic packets confirms a node failure removes exactly one node and its real
  incident edges from a genuinely-constructed `TopologyGraph`.
- Full repo suite (`pytest backend/tests experiments/tests simulator/tests`, run from repo root) —
  **493/493 passed** (up from 482/482), no regressions.
- `python -m scripts.validate_data_contracts` — 38/38 passed, no regression (no schema changes this
  phase).
- `python -m scripts.check_ground_truth_boundary` — clean.

## Status

Controlled failure injection (spec Phase 59, FR-1.32) is implemented and unit-verified:
`apply_failure_scenario` applies any of the six `FailureType`s to a real `TopologyGraph`, producing
an isolated, honestly-scoped result — structural removal for hard failures, an affected-edge set
for soft ones — without inventing path-cost weighting or propagation logic that belong to later
phases. No API route exists yet — `POST /simulation` remains scoped through Phase 61. The dynamic
path engine (Phase 60) and the connected failure→propagation→routing→service-impact pipeline
(Phase 61) remain ahead.
