# NETSCOPE-X — Counterfactual Graph Engine

Phase 65 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 65 — COUNTERFACTUAL GRAPH
ENGINE"): execute counterfactuals on an isolated alternate graph state that never mutates the real
baseline.

FR-1.36 (second half): *"...execute counterfactuals on an isolated alternate graph state that
never mutates the real baseline (spec Phase 65)."*

Code: new `backend/simulation/counterfactual_engine.py` (`CounterfactualExecutionResult`,
`execute_counterfactual_scenario`).

## Mirrors `apply_failure_scenario` wherever directly analogous

`backend/simulation/failure_injection.py`'s `apply_failure_scenario` (Phase 59) is the direct
structural precedent: an isolated-copy `TopologyGraph` construction, hard actions remove
nodes/edges, soft actions only mark `degraded_edge_ids` (no path-cost computation — that stays
Phase 66's job here, exactly as it was Phase 60's job for failure injection).

| `CounterfactualAction` | `FailureType` analog | Behavior |
|---|---|---|
| `REMOVE_NODE` | `NODE_FAILURE` | Removes the node and its incident edges. |
| `REMOVE_EDGE` | `EDGE_FAILURE` | Removes only the targeted edge. |
| `INCREASE_LATENCY` | `LATENCY_INJECTION` | Marks the target node's incident edges degraded; no structural change. |
| `REDUCE_BANDWIDTH` | `BANDWIDTH_REDUCTION` | Marks the targeted edge, or a targeted node's incident edges, degraded. |
| `INCREASE_TRAFFIC` | *(none — new in Phase 64)* | Marks the target node's incident edges degraded, same node-only reasoning as Phase 64 established. |
| `ADD_ROUTE` | *(none — new in Phase 64)* | Synthesizes and adds a new hypothetical `Edge`. See below. |

`REDUCE_BANDWIDTH`'s "target_node_id or target_edge_id" ambiguity needs no extra guard in this
module, unlike Phase 59's own supplementary patch for `FailureScenario` — Phase 64 already closed
that gap at the schema level (`_action_requires_correct_fields`), so by the time a
`CounterfactualScenario` reaches this module, exactly one of the two is guaranteed present.

## `baseline_graph_id`/`isolated_graph_id` usage

Unlike `FailureScenario` (which carries no graph-identity fields at all — `apply_failure_scenario`
synthesizes `f"{graph.graph_id}:failure:{scenario.scenario_id}"`), `CounterfactualScenario` already
reserved `baseline_graph_id`/`isolated_graph_id` since Phase 04, specifically for this phase. This
module therefore:

1. Validates `scenario.baseline_graph_id == graph.graph_id` up front, raising `ValueError` on
   mismatch — a genuinely inconsistent call, the same fail-fast stance Phase 59 already takes for
   its own target-existence guards.
2. Uses `scenario.isolated_graph_id` directly as the resulting graph's `graph_id` — not
   synthesized, since the schema already reserved this field for exactly this purpose.

## `ADD_ROUTE`: synthesizing a hypothetical edge

No precedent exists anywhere in this codebase for constructing a non-empirically-observed `Edge`
except `simulator/ground_truth/generate.py`'s *declared* edges (`confidence=1.0`,
`evidence=["ground truth: declared lab architecture..."]`). That precedent's **mechanism** — fill
every required field, name the real justification directly in `evidence` — is reused here. Its
**confidence value is not**: ground truth is declared-and-certain (the real deployed architecture,
known by construction); a counterfactual `ADD_ROUTE` is explicitly hypothetical and unvalidated.
RQ7 (`docs/research/research_questions.md`) is direct on this exact point: *"report the prediction
as unvalidated rather than implying it was tested."* Reusing `confidence=1.0` would misrepresent a
hypothetical route as a certain one.

This module therefore uses a documented, fixed, neutral constant:

```python
_HYPOTHETICAL_ROUTE_CONFIDENCE = 0.5
```

— deliberately distinct from ground truth's `1.0`, neither claiming nor denying real evidence for
the route. Every other required `Edge` field is filled with an equally deliberate, documented
choice, never a silent default:

- `evidence = [f"hypothetical route added by counterfactual scenario {scenario_id}; not empirically observed"]`
  — states plainly that this is a counterfactual construct, not an observation.
- `observation_count = 1` — the schema's structural minimum (`Edge.observation_count` has
  `ge=1`); documented as **not** meaning "observed once" the way real inference means it, purely
  satisfying the Pydantic constraint for a declared/hypothetical construct — mirroring ground
  truth's own use of the same minimum for the same structural reason.
- `first_observed = last_observed = scenario.created_at` — the honest anchor timestamp: when this
  hypothetical was declared, not a fabricated observation time.
- `protocols = ["unknown"]` — `Edge.protocols` requires `min_length=1`; no protocol is claimed or
  knowable for a hypothetical route, so an explicit placeholder is used rather than a guess.

`CounterfactualScenario.magnitude` is deliberately **not** repurposed as this confidence value: it
has no documented meaning for `ADD_ROUTE`
(`docs/architecture/counterfactual_scenario_language.md`'s own decision table says so explicitly),
and silently overloading a field whose documented meaning is "degradation magnitude" into "route
certainty" would violate this codebase's "explicit over implicit/overloaded fields" convention —
the same reasoning already applied throughout Phase 64's own validator design.

### The no-existing-route guard

`ADD_ROUTE` additionally requires that no edge already connects `source_node_id`/`target_node_id`
in either direction (undirected, per Phase 30's own edge convention) — `ValueError` if one does.
RQ7's own framing of `ADD_ROUTE` is specifically *"a purely hypothetical route that doesn't
exist"*; adding a route that already exists would be incoherent, not merely redundant, so this is
enforced as a real precondition rather than silently accepted as a no-op.

## What this phase deliberately does NOT do

- **No path-cost weighting or connectivity analysis.** Comparing the isolated graph's paths,
  connectivity, or resilience indicators against the baseline is Phase 66's job (FR-1.37: "compare
  baseline vs. counterfactual outcomes across paths, connectivity, latency, affected services,
  bottlenecks, and propagation"). `path_engine.py` is never invoked here, exactly as
  `apply_failure_scenario` never invokes it either.
- **No impact validation against reality.** RQ7's "predicted vs. actual" comparison for
  counterfactuals is also Phase 66's job.
- **No API wiring.** `POST /counterfactual` stays `NotYetImplemented`, unchanged — same reasoning
  as Phase 59-61's own `POST /simulation` decision (no results field, no artifact-path convention).
- **No new Pydantic schema.** `CounterfactualScenario`/`CounterfactualAction` are reused exactly as
  Phase 64 left them; `CounterfactualExecutionResult` is a plain frozen dataclass, matching
  `FailureInjectionResult`'s own precedent.

## Worked examples

```python
# REMOVE_NODE -- direct mirror of NODE_FAILURE
execute_counterfactual_scenario(graph, CounterfactualScenario(
    scenario_id="cf1", action=REMOVE_NODE, baseline_graph_id="g1", isolated_graph_id="g1-cf1",
    target_node_id="H", created_at=NOW))
# removed_node_ids=["H"], removed_edge_ids=[...H's incident edges...]

# ADD_ROUTE -- the novel action, given the most detail
execute_counterfactual_scenario(graph, CounterfactualScenario(
    scenario_id="cf2", action=ADD_ROUTE, baseline_graph_id="g1", isolated_graph_id="g1-cf2",
    source_node_id="A", target_node_id="D", created_at=NOW))
# added_edge_id="g1-cf2:added-route:cf2"
# new edge: confidence=0.5, evidence=["hypothetical route added by counterfactual scenario cf2; not empirically observed"],
#           observation_count=1, protocols=["unknown"], first_observed=last_observed=NOW

# ADD_ROUTE raises when A and D are already connected, or when either node doesn't exist in graph.
```

## Verification actually performed this phase

- `pytest backend/tests/test_counterfactual_engine.py -v` — **13/13 passed**: `REMOVE_NODE`
  removes the node and its incident edges (and raises for an unknown target); `REMOVE_EDGE` removes
  only the targeted edge; `INCREASE_LATENCY`/`REDUCE_BANDWIDTH` (both target forms)/
  `INCREASE_TRAFFIC` all correctly mark incident/targeted edges degraded with zero structural
  change; `ADD_ROUTE` adds exactly one new edge with every documented hypothetical field value,
  raises when the two endpoints are already connected, and raises for an unknown endpoint; a
  `baseline_graph_id` mismatch raises; the function never mutates its input graph; a real
  end-to-end run over a topology discovered from synthetic packets confirms a `REMOVE_NODE`
  counterfactual behaves identically to the hand-built fixtures.
- Full repo suite (`pytest backend/tests experiments/tests simulator/tests`, run from repo root) —
  **555/555 passed** (up from 542/542), no regressions.
- `python -m scripts.validate_data_contracts` — 55/55 passed, unchanged (no schema changes this
  phase — `CounterfactualScenario` is consumed exactly as Phase 64 left it).
- `python -m scripts.check_ground_truth_boundary` — clean.

## Status

The counterfactual graph engine (spec Phase 65, FR-1.36's second half) is implemented and
unit-verified: all six `CounterfactualAction` verbs now execute against a real `TopologyGraph`,
producing a genuinely isolated alternate graph that never mutates the baseline, with `ADD_ROUTE`'s
hypothetical-edge synthesis resolved as a firm, documented decision distinct from ground truth's
declared-and-certain edges. No API route exists yet. Phase 66 (comparing baseline vs.
counterfactual outcomes across paths, connectivity, latency, affected services, bottlenecks, and
propagation) remains ahead.
