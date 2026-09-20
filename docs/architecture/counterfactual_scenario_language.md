# NETSCOPE-X — Structured Counterfactual Scenario Language

Phase 64 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 64 — STRUCTURED
COUNTERFACTUAL SCENARIO LANGUAGE"): support REMOVE node, REMOVE edge, INCREASE latency, REDUCE
bandwidth, INCREASE traffic, ADD route as a structured scenario language.

FR-1.36: *"The system shall support a structured counterfactual scenario language (REMOVE node,
REMOVE edge, INCREASE latency, REDUCE bandwidth, INCREASE traffic, ADD route) (spec Phase 64) and
execute counterfactuals on an isolated alternate graph state that never mutates the real baseline
(spec Phase 65)."* This phase covers the Phase 64 half only — the language itself. Executing a
counterfactual against an isolated alternate graph (Phase 65) and comparing predicted vs. actual
outcomes (Phase 66) are untouched; no `backend/simulation/counterfactual_*.py` module exists yet,
and `POST /counterfactual` stays `NotYetImplemented`.

## No new module — a schema-only phase

`backend/app/models/simulation.py`'s `CounterfactualAction` (the six-verb enum) and
`CounterfactualScenario` have existed since Phase 04. Until this phase, `CounterfactualScenario`'s
only validator checked `isolated_graph_id != baseline_graph_id` — zero action-specific field
requirements were enforced, and `ADD_ROUTE` could not even be expressed (no field existed for a
second node endpoint; confirmed by a full-repo grep — `ADD_ROUTE` appeared nowhere but the enum
definition and one doc line). This phase adds exactly one new field and one new validator method
to that existing schema — no new file, no new Pydantic model.

## Field design: `source_node_id`

```python
source_node_id: Optional[str] = Field(
    default=None,
    description="ADD_ROUTE only: the new route's origin node. Must stay None for every other action.",
)
```

Mirrors `Edge.source_node_id`/`target_node_id` (`backend/app/models/topology.py`) exactly, rather
than inventing route-specific field names — `target_node_id` does double duty as "the route's
destination node" for `ADD_ROUTE` and "the single targeted node" for every other node-targeted
action, keeping the schema minimal.

`source_node_id` is hard-forbidden for every action except `ADD_ROUTE` — not merely left
unenforced. This schema's existing convention (`_isolated_differs_from_baseline`) is "explicit
over invalid state," not "permissive by default": silently allowing `source_node_id` to be set on
a `REMOVE_NODE` scenario would let a request smuggle in a field that looks meaningful but is
silently ignored, exactly the kind of structural ambiguity this codebase's schemas are built to
make impossible.

## Per-action requirement table

| Action | Required | Forbidden | Why |
|---|---|---|---|
| `REMOVE_NODE` | `target_node_id` | — | Mirrors `FailureType.NODE_FAILURE` (`backend/app/models/failure.py`): removing a node is meaningless without naming which one. |
| `REMOVE_EDGE` | `target_edge_id` | — | Mirrors `FailureType.EDGE_FAILURE`, same reasoning, edge-scoped. |
| `INCREASE_LATENCY` | `target_node_id`, `magnitude` | — | Deliberately node-only, matching `FailureType.LATENCY_INJECTION`'s own established node-only precedent. Edge-targeted latency ("raise latency on this one link") is conceptually sensible, but this phase's job is to model the *existing* precedent faithfully, not silently diverge from it in a sibling schema Phase 65 will eventually read alongside `FailureScenario`. |
| `REDUCE_BANDWIDTH` | (`target_node_id` OR `target_edge_id`), `magnitude` | — | Mirrors `FailureType.BANDWIDTH_REDUCTION`'s ambiguous-ratio pattern (may target either). Unlike `FailureScenario`'s own Phase 04→59 split — where the schema left this "at least one" rule unenforced and Phase 59's `apply_failure_scenario` patched it at execution time, because Phase 59 wasn't the schema-owning phase — this phase *is* `CounterfactualScenario`'s schema-owning phase (nothing else touches it before Phase 65 consumes it), so the rule is enforced here, in the schema, in this same pass. |
| `INCREASE_TRAFFIC` | `target_node_id`, `magnitude` | — | No `FailureScenario` analog — a new concept. Node-only: traffic is naturally sourced or destined at a node (a service generating or receiving load), unlike latency/bandwidth reduction, which are physical link properties that can localize to a single edge. `magnitude` is the traffic multiplier, per the field's own pre-existing docstring. |
| `ADD_ROUTE` | `source_node_id`, `target_node_id` (must differ) | `target_edge_id` | The only two-endpoint action — a route being added has no existing edge to reference, so `target_edge_id` must stay `None`. No `magnitude` requirement: a structural addition, not a continuous degradation, mirroring `REMOVE_NODE`/`REMOVE_EDGE`'s own no-magnitude convention. Self-loop (`source_node_id == target_node_id`) is forbidden, directly mirroring `Edge._no_self_loop` — a route from a node to itself isn't a route, exactly as an edge connecting a node to itself isn't an edge; reusing an established, directly-analogous rule already in this codebase is the consistent choice. |

## Why Phase 64 owns this schema's validation completely

`FailureScenario` (Phase 04) already enforced per-type target requirements for 4 of its 6 failure
types at the schema level; Phase 59's `apply_failure_scenario` only added one narrow supplementary
guard for the remaining two ambiguous "ratio" types (`PACKET_LOSS`/`BANDWIDTH_REDUCTION`), and that
guard lives in the *execution* function, not the schema — because Phase 59 wasn't the schema's
owning phase, and Phase 04's own validator simply hadn't covered every case.

`CounterfactualScenario` is in a different position: nothing else is scheduled to touch this
schema before Phase 65's execution engine consumes it. Phase 64 *is* effectively the schema-owning
phase here, so rather than repeating `FailureScenario`'s gap-and-patch history — leaving the
`REDUCE_BANDWIDTH` ambiguous-target case for Phase 65 to discover and patch inside execution logic
— this phase does the complete validation job in one pass, including that ambiguous case. This is
a deliberate, better-informed deviation from the Phase 04→59 precedent, not an oversight or a
missed opportunity to mirror it exactly.

## What this phase deliberately does NOT do

- **No execution engine.** Applying a `CounterfactualScenario` to a real `TopologyGraph`, producing
  an isolated alternate graph state, is Phase 65's job (FR-1.36's second half). No
  `backend/simulation/counterfactual_*.py` module exists yet.
- **No impact comparison.** Comparing a counterfactual's predicted outcome against a real
  controlled experiment (RQ7, FR-1.37/1.38) is Phase 66's job.
- **No API wiring.** `POST /counterfactual` stays `NotYetImplemented`; its docstring's "known
  simplification" note about the request DTO shape is unaffected by this phase's one new optional
  field.
- **No new Pydantic model.** One field and one validator method added to the existing
  `CounterfactualScenario`, nothing more.

## Worked examples

```python
# REMOVE_NODE
CounterfactualScenario(scenario_id="cf1", action=REMOVE_NODE, baseline_graph_id="g1",
                        isolated_graph_id="g1-cf1", target_node_id="n2", created_at=NOW)

# REMOVE_EDGE
CounterfactualScenario(scenario_id="cf2", action=REMOVE_EDGE, baseline_graph_id="g1",
                        isolated_graph_id="g1-cf2", target_edge_id="e1", created_at=NOW)

# INCREASE_LATENCY
CounterfactualScenario(scenario_id="cf3", action=INCREASE_LATENCY, baseline_graph_id="g1",
                        isolated_graph_id="g1-cf3", target_node_id="n2", magnitude=50.0, created_at=NOW)

# REDUCE_BANDWIDTH (either target works)
CounterfactualScenario(scenario_id="cf4", action=REDUCE_BANDWIDTH, baseline_graph_id="g1",
                        isolated_graph_id="g1-cf4", target_edge_id="e1", magnitude=0.5, created_at=NOW)

# INCREASE_TRAFFIC
CounterfactualScenario(scenario_id="cf5", action=INCREASE_TRAFFIC, baseline_graph_id="g1",
                        isolated_graph_id="g1-cf5", target_node_id="n2", magnitude=2.0, created_at=NOW)

# ADD_ROUTE -- the novel action, given the most detail:
# valid: two distinct endpoints, no target_edge_id
CounterfactualScenario(scenario_id="cf6", action=ADD_ROUTE, baseline_graph_id="g1",
                        isolated_graph_id="g1-cf6", source_node_id="n1", target_node_id="n2", created_at=NOW)

# invalid: missing source_node_id -> "ADD_ROUTE requires both source_node_id and target_node_id"
# invalid: target_edge_id set -> "ADD_ROUTE cannot reference an existing target_edge_id"
# invalid: source_node_id == target_node_id -> "ADD_ROUTE cannot connect a node to itself"
```

## Verification actually performed this phase

- `python -m scripts.validate_data_contracts` — **55/55 passed** (up from 38/38): 17 new
  `CounterfactualScenario` cases added (8 valid, 9 invalid) covering every action's required-field
  combination, `REDUCE_BANDWIDTH`'s either-target case, `ADD_ROUTE`'s two-endpoint/self-loop/
  edge-id-forbidden cases, and `source_node_id` being rejected on a non-`ADD_ROUTE` action; the two
  pre-existing cases (valid `REMOVE_NODE`, the isolation-check rejection) re-verified unchanged.
- Full repo suite (`pytest backend/tests experiments/tests simulator/tests`, run from repo root) —
  **542/542 passed**, unchanged from before this phase: no runtime/execution code path touches this
  schema yet, and `backend/tests/test_api.py`'s existing `/api/v1/counterfactual` fixture already
  supplied `target_node_id` for its `REMOVE_NODE` request, so it already satisfied the new
  validator without modification.
- `python -m scripts.check_ground_truth_boundary` — clean (no code changed that could affect this
  check; re-run to confirm no regression).

## Status

The structured counterfactual scenario language (spec Phase 64, FR-1.36's first half) is complete:
all six actions now have real, enforced field requirements, and `ADD_ROUTE` can be genuinely
expressed for the first time via the new `source_node_id` field. Phase 65 (execution on an
isolated alternate graph) and Phase 66 (impact comparison) remain ahead; `POST /counterfactual`
remains a documented stub.
