# NETSCOPE-X — Failure Propagation Simulator

Phase 61 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 61 — FAILURE PROPAGATION
SIMULATOR"): "simulate failure → dependency propagation → routing impact → service impact as a
connected pipeline, not isolated stages."

FR-1.34: *"The system shall simulate failure → dependency propagation → routing impact → service
impact as a connected pipeline, not isolated stages (spec Phase 61)."*

Code: new `backend/simulation/failure_propagation_pipeline.py` (`FailurePipelineResult`,
`ServiceImpact`, `run_failure_propagation_pipeline`).

## Pure composition, not new logic

This phase reimplements none of the three already-real, already-tested pieces it chains together:

- Phase 59 `apply_failure_scenario` (`backend/simulation/failure_injection.py`) — applies a
  `FailureScenario` to an isolated copy of the graph.
- Phase 54 `propagate_failure` (`backend/dependency/failure_propagation.py`) — BFS over Phase 53's
  `CausalCandidate` edges from a single failed-node origin, producing PRIMARY/SECONDARY/TERTIARY
  `PropagationImpact`s.
- Phase 60 `compute_connectivity`/`compute_route_change` (`backend/simulation/path_engine.py`) —
  connectivity analysis and shortest-path comparison, weighted by confidence and Phase 59's
  failure-degradation marks.

Both Phase 59's and Phase 60's own docstrings explicitly deferred "composing into one pipeline" to
Phase 61 — that composition is the entirety of this phase's work.

## `run_failure_propagation_pipeline(graph, scenario, candidates, role_classifications=None)`

Four stages, run in order, each feeding the next:

1. **Injection.** `injection = apply_failure_scenario(graph, scenario)` — unchanged call. Supplies
   the isolated post-failure graph and `degraded_edge_ids` every later stage needs.
2. **Dependency propagation.** `propagate_failure(candidates, scenario.scenario_id,
   scenario.target_node_id)` — unchanged call, run only when `scenario.target_node_id is not
   None`. See "Decision 1" below for when it is skipped.
3. **Routing impact.** Whole-graph connectivity before (`compute_connectivity(graph)`) vs. after
   (`compute_connectivity(injection.graph)`) yields `newly_unreachable_node_ids`; bounded
   `compute_route_change` calls over the failure site's own former direct neighbors yield
   `route_changes`. See "Decision 2" below.
4. **Service impact.** The union of propagation-affected and newly-unreachable node ids, each
   reported as one itemized `ServiceImpact`, optionally annotated with a caller-supplied
   `RoleClassification`. See "Decision 3" below.

Returns one frozen `FailurePipelineResult` carrying every stage's output — the scenario, the
injection result, the propagation impacts, both connectivity snapshots, the newly-unreachable node
ids, the route changes, and the service impacts — so a caller sees the whole connected pipeline,
not isolated per-stage calls it has to wire together itself.

## Decision 1 — what feeds propagation when there's no `target_node_id`

`propagate_failure` requires exactly one causal-origin node id. A pure `EDGE_FAILURE`, or an
edge-targeted `PACKET_LOSS`/`BANDWIDTH_REDUCTION`, has no single node that is "the" failure — both
endpoints are only partially implicated. Picking one arbitrarily, or merging both into a synthetic
origin, would fabricate causal evidence that `CausalCandidate` (Phase 53) was specifically built to
avoid claiming — a `CausalCandidate` exists only where real temporal-precedence evidence supports a
specific direction, and an edge failure has no such directional evidence about which of its two
endpoints "caused" what. So propagation runs only when `scenario.target_node_id is not None`;
otherwise `propagation_impacts = []`. An edge-only failure still gets a real, honest routing-impact
answer from stage 3 — it simply has no causal-propagation stage, a scope limitation of Phase 54's
own node-oriented design, documented here rather than silently worked around.

## Decision 2 — what counts as "routing impact"

`compute_connectivity` already answers "did the graph fragment" globally in O(n) with no pair
selection required, so it is run once before and once after injection; a node that was in the
graph's largest connected component before, is still present in the post-failure graph (i.e. it
wasn't itself removed), but is no longer in the largest component after, is `newly_unreachable`.

`compute_route_change` needs explicit `(source, target)` pairs, and the only pairs with real
evidentiary justification are the failure site's own former direct neighbors (for a node failure)
or the failed edge's own two endpoints (for an edge failure) — these are the routes guaranteed to
have actually used the failed element, so a before/after comparison is meaningful for every pair
reported. An all-pairs comparison across every node in the graph was considered and rejected: it
would be undocumented O(n²) scope creep, and for most of the resulting pairs there would be no
evidence the failed element was ever on their path at all.

## Decision 3 — what "service impact" means

NETSCOPE-X has no service registry independent of nodes — a "service" is a node, optionally
role-classified via the already-existing but currently orphaned Phase 36-37
`RoleClassification`/`ServiceRole` (`backend/app/models/behavior.py`; its only planned consumer,
`GET /behaviors/{node_id}`, stays a 501 stub through this phase). Rather than resurrecting that
stub or inventing a new classification call inside this module, `run_failure_propagation_pipeline`
accepts an optional caller-supplied `Dict[str, RoleClassification]`; a `ServiceImpact` for a node
with no entry gets `role_classification=None` — an honest "role unknown," matching this codebase's
established no-fabrication convention (Phase 48/53's unconditional disclaimers), never a guessed
role.

Service impact stays strictly itemized, one `ServiceImpact` per affected node (`reason` –
`"propagation"`, `"routing"`, or `"propagation+routing"`; `propagation_order`; `newly_unreachable`;
`role_classification`) — no aggregate ratio, count, or score is computed here. That aggregation —
connectivity ratio, reachable-node ratio, affected-service *count*, path-degradation score,
bottleneck detection — is `ResilienceIndicators` (`backend/app/models/failure.py`), explicitly
reserved for spec Phase 62. This phase supplies exactly the itemized raw material that aggregation
will need, nothing more.

## `POST /simulation` stays a stub

`SimulationRun` (Phase 04/57-58) carries only run metadata — `run_id`, `twin_snapshot_id`,
`scenario`, `started_at`, `completed_at` — no results field. Wiring `POST /simulation` to return
real pipeline output would require either an unscoped schema change to `SimulationRun` or a new
`experiments/artifacts` persistence convention (that package's own docstring enumerates a fixed,
phase-cited layout with no "simulation" entry reserved by any phase's spec text). Neither is
mandated by FR-1.34, which asks only that the *simulation logic* be a connected pipeline, not that
it be exposed over HTTP or persisted. The route's docstring and `NotYetImplemented` message were
updated to say so explicitly — library complete, API wiring/persistence deliberately unscoped —
rather than leaving a stale "Phase 59-61" reference now that all three are implemented as library
code.

## What this phase deliberately does NOT do

- **No resilience indicators.** `ResilienceIndicators` aggregation is Phase 62's job (Decision 3).
- **No counterfactual scenario language.** `CounterfactualAction`/execution/comparison is Phase
  64-66's job (`backend/app/models/simulation.py`'s own later fields).
- **No API wiring or result persistence.** See the section above.
- **No new Pydantic schema.** Every input/output type this phase touches
  (`FailureScenario`/`PropagationImpact`/`RoleClassification`/`ServiceRole`) already existed;
  `FailurePipelineResult`/`ServiceImpact` are plain frozen dataclasses, matching the precedent
  already set by `FailureInjectionResult`/`PathResult`/`ConnectivityResult`/`RouteChange` — no
  Phase 04 schema was reserved for a pipeline-composition-level concept.

## Worked example

The diamond topology A→B→D (confidence 0.9/0.9, cheap) and A→C→D (confidence 0.5/0.5, expensive),
with one `CausalCandidate` B→D:

```
scenario = FailureScenario(scenario_id="s1", failure_type=NODE_FAILURE, target_node_id="B")
result = run_failure_propagation_pipeline(graph, scenario, candidates=[candidate_b_to_d])

result.injection.removed_node_ids            # ["B"]
result.propagation_impacts                    # [PRIMARY(B), SECONDARY(D, caused_by=B)]
result.connectivity_before.is_fully_connected # True
result.connectivity_after.is_fully_connected  # True (A still reaches D via C)
result.newly_unreachable_node_ids             # []
result.route_changes                          # 2 entries: (A, B) and (D, B) -- B's former neighbors
                                                #   both now report current_path=None (B is gone)
result.service_impacts                        # [ServiceImpact(B, reason="propagation", order="primary", ...),
                                                #  ServiceImpact(D, reason="propagation", order="secondary",
                                                #                role_classification=None, ...)]
```

## Verification actually performed this phase

- `pytest backend/tests/test_failure_propagation_pipeline.py -v` — **9/9 passed**: a node failure
  with a supporting `CausalCandidate` reports PRIMARY/SECONDARY propagation, route changes for both
  former neighbors, and a `ServiceImpact` for the propagated-to node with `role_classification is
  None`; an edge failure reports no propagation impacts but still reports routing impact for the
  edge's own two endpoints; a node failure with zero causal candidates still reports exactly the
  PRIMARY impact; a chain-graph node failure that structurally disconnects the graph reports the
  correct `newly_unreachable_node_ids`; a node that is both a propagation target and newly
  unreachable reports `reason="propagation+routing"`; a supplied `role_classifications` map is
  passed through verbatim while an unsupplied impacted node gets `None`; the pipeline never
  mutates its input graph's node/edge id sets; route changes stay bounded to the failure site's
  former direct neighbors (2, not an all-pairs explosion) on a 5-node graph; a real end-to-end run
  over a topology discovered from synthetic packets confirms the pipeline runs cleanly end to end.
- Full repo suite (`pytest backend/tests experiments/tests simulator/tests`, run from repo root) —
  **517/517 passed** (up from 508/508), no regressions.
- `python -m scripts.validate_data_contracts` — 38/38 passed, no regression (no schema changes
  this phase).
- `python -m scripts.check_ground_truth_boundary` — clean.

## Status

The failure propagation simulator (spec Phase 61, FR-1.34) is implemented and unit-verified: a
single `run_failure_propagation_pipeline` call now composes failure injection, dependency
propagation, routing impact, and itemized service impact into one connected result, with each of
the three composition boundaries (propagation-origin ambiguity, routing-impact pair scope,
service-impact/role-annotation scope) resolved as an explicit, documented decision rather than left
implicit. `POST /simulation` stays `NotYetImplemented`, now documented as library-complete with API
wiring/persistence deliberately unscoped. Aggregate resilience indicators (Phase 62) and
counterfactual scenario language/execution/comparison (Phase 64-66) remain ahead.
