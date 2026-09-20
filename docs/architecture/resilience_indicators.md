# NETSCOPE-X — Resilience Indicators

Phase 62 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 62 — RESILIENCE &
VULNERABILITY INDICATORS"): "compute resilience indicators: connectivity, reachable-node ratio,
affected services, path degradation, bottleneck emergence, alternative-path availability."

FR-1.35: *"The system shall compute resilience indicators: connectivity, reachable-node ratio,
affected services, path degradation, bottleneck emergence, alternative-path availability (spec
Phase 62)."*

Code: new `backend/simulation/resilience_indicators.py` (`compute_resilience_indicators`).

## Pure aggregation, not new logic

`ResilienceIndicators` (`backend/app/models/failure.py`) has existed since Phase 04 and was
explicitly reserved for this phase — both `docs/architecture/failure_propagation_simulator.md`
and `docs/architecture/dynamic_path_engine.md` deferred these six metrics here rather than
computing them early. This module reimplements none of:

- Phase 55 `compute_graph_criticality` (`backend/dependency/criticality.py`) — articulation
  points / structural bottlenecks.
- Phase 60 `compute_alternate_paths` (`backend/simulation/path_engine.py`) — Yen's algorithm.
- Phase 61 `run_failure_propagation_pipeline` (`backend/simulation/failure_propagation_pipeline.py`)
  — the connected failure→propagation→routing→service-impact pipeline whose output this module
  consumes.

## `compute_resilience_indicators(graph, result)`

Takes both the pre-failure `TopologyGraph` and a Phase 61 `FailurePipelineResult`. `result` alone
almost suffices — its `connectivity_before`/`connectivity_after`, `route_changes`,
`service_impacts`, and `injection.graph` cover five of the six metrics — but it carries no
pre-failure graph object, only `ConnectivityResult` component membership with no edge list. The
original `graph` is needed once, for `bottleneck_node_ids`'s pre/post articulation-point diff. No
stage of Phase 61's pipeline (injection, propagation, routing) is re-run here. `graph` must be the
exact pre-failure graph originally passed to `run_failure_propagation_pipeline`; this is
caller-trusted, not runtime-verified, matching `compute_route_change`'s own existing trust
convention in `path_engine.py`.

## Decision 1 — `connectivity_ratio`

`after_size / before_size`, where both are `len(...largest_component_node_ids)` from
`result.connectivity_after`/`connectivity_before` (`1.0` when `before_size == 0`, mirroring
`compute_connectivity`'s own empty-graph convention). Self-relative to the pre-failure largest
component: measures what *this* failure did to the main body, not pre-existing fragmentation in
the input graph. Always in `[0,1]` since a failure only ever removes nodes/edges, never adds them.

## Decision 2 — `reachable_node_ratio`

A deliberately different axis, not a rescaled duplicate of `connectivity_ratio`:
`len(nodes in any post-failure component of size >= 2) / (total originally-present node count)`.
Where `connectivity_ratio` asks "how big is the single largest surviving fragment relative to
before," this asks "what fraction of every originally-present node still has at least one peer it
can reach post-failure" — counting every healthy island, not just the largest, against the full
original node count. A stranded singleton (all its edges led to the failed element) is honestly
`0` — it cannot communicate, matching the plain-language meaning of "reachable." The two formulas
coincide whenever the post-failure graph stays a single component (correctly — nothing to
differentiate there) and diverge whenever a failure splits the graph into multiple still-healthy
islands. Proven, not merely asserted: `test_connectivity_ratio_and_reachable_node_ratio_diverge_on_fragmenting_failure`
removes the sole bridge node of a bowtie graph (B–A–M–D–E) and shows `connectivity_ratio == 0.4`
(the post-failure largest island {A,B} or {D,E}, size 2, over the pre-failure size 5) while
`reachable_node_ratio == 0.8` (both size-2 islands, 4 of the original 5 nodes, still have a peer).

## Decision 3 — `affected_service_count`

`len(result.service_impacts)` directly. Phase 61's `service_impacts` list is already deduplicated
per node by construction (one `ServiceImpact` per node id in the propagation ∪ newly-unreachable
union); no further filtering is needed.

## Decision 4 — `path_degradation_score`

Sum, not mean, over `result.route_changes` — a raw itemized-then-summed count, matching
`affected_service_count`'s own convention, so a failure hitting many pairs scores higher than one
hitting few:

- `baseline_path is None` → contributes `0.0` (nothing existed pre-failure for that pair — not a
  degradation, a non-event).
- `current_path is None` (the route fully collapsed) → contributes a fixed
  `_UNREACHABLE_PATH_PENALTY = -math.log(1e-9)` (≈20.72, reusing `path_engine.py`'s own
  `-log(confidence)` unit and epsilon-clamp convention) — explicitly *not* silently zero or
  dropped, since a fully dead route is the worst outcome a route can have, not a missing data
  point. `float('inf')` was rejected as unserializable and useless for cross-scenario comparison.
- otherwise → `max(cost_delta, 0.0)` (only worsening counts; an incidentally cheaper reroute is
  not "degradation").

## Decision 5 — `bottleneck_node_ids`

The *diff* of Phase 55 articulation points, not the raw post-failure set:
`compute_graph_criticality(graph)` and `compute_graph_criticality(result.injection.graph)` are
each run once; `bottleneck_node_ids = sorted(post_articulation_ids - pre_articulation_ids)`. Read
literally against the spec's own word "emergence": a node that was already a structural single
point of failure before any simulated failure is a pre-existing weakness, not something this
failure *caused* — `docs/architecture/criticality_analysis.md` already deliberately left that raw
signal un-scored, reserving the "what changed" question for this phase. Only nodes that became
newly critical *because of* this simulated failure count.

## Decision 6 — `alternative_path_available`

Over the same bounded, already-justified pair set Phase 61 derived (`result.route_changes`, the
failure site's former direct neighbors, or an edge failure's own two endpoints): for each pair
whose `current_path is not None`, `compute_alternate_paths(result.injection.graph, source, target,
k=2, failure=result.injection)` is run and checked for `len(paths) >= 2` — a genuine *second*
route via Yen's algorithm, not merely "still reachable" (which `reachable_node_ratio` already
covers). `True` if any pair qualifies. Uses `result.injection.graph`/`result.injection` (not the
original `graph`) so the search applies the same failure-adjusted weights `route_changes` was
computed with. Empty `route_changes` → `False`, an honest "no evidence gathered," never a
fabricated `True`.

## `POST /simulation` stays a stub

Unchanged from Phase 61's own decision: `SimulationRun` has no results field, and no
`experiments/artifacts` convention reserves a simulation-output path. FR-1.35 only asks that these
indicators be *computed*, not served over HTTP — that reasoning applies unchanged here.

## What this phase deliberately does NOT do

- **No counterfactual scenario engine.** The structured counterfactual scenario language
  (`REMOVE_NODE`/`REMOVE_EDGE`/etc.), its isolated-alternate-graph execution, and
  baseline-vs-counterfactual comparison are Phase 64-66's job (FR-1.36/1.37).
- **No digital-twin/experiment validation.** Comparing predictions against real controlled
  experiment outcomes is Phase 63's job (FR-1.38) — this phase computes indicators from a
  *simulated* failure only, and claims nothing about their accuracy against reality.
- **No re-running of Phase 55/60/61's own logic.** Every metric is derived from `result` and one
  extra `compute_graph_criticality` pass; no injection, propagation, or routing is recomputed.
- **No new Pydantic schema or API wiring.** `ResilienceIndicators` already existed unchanged.

## Worked examples

Continuing Phase 61's own diamond topology (A–B–D cheap / A–C–D expensive) with a `NODE_FAILURE`
on B and one `CausalCandidate` B→D:

```
result = run_failure_propagation_pipeline(graph, scenario, candidates=[candidate_b_to_d])
compute_resilience_indicators(graph, result)
# connectivity_ratio: 0.75      (post-failure {A,C,D} size 3 / pre-failure size 4)
# reachable_node_ratio: 0.75    (same single surviving component -- no fragmentation to differentiate here)
# affected_service_count: 2     (B, D)
# path_degradation_score: 2 * _UNREACHABLE_PATH_PENALTY  (both of B's former neighbors, A and D, lose their route to B)
# bottleneck_node_ids: ["C"]    (C becomes the sole cut-vertex once B, the other half of the A-B-D/A-C-D cycle, is gone)
# alternative_path_available: False  (B's own former-neighbor pairs are unreachable, not merely degraded)
```

The bowtie fixture (B–A–M–D–E, M the sole bridge) under a `NODE_FAILURE` on M demonstrates the
`connectivity_ratio`/`reachable_node_ratio` divergence:

```
# connectivity_ratio: 0.4    (largest surviving island {A,B} or {D,E}, size 2, over the pre-failure size 5)
# reachable_node_ratio: 0.8  (4 of 5 original nodes still have a peer, across BOTH size-2 islands)
```

## Verification actually performed this phase

- `pytest backend/tests/test_resilience_indicators.py -v` — **15/15 passed**: a diamond node
  failure reports all six fields populated and sane, including the correct emergent bottleneck;
  a chain node failure shows reduced connectivity (`1/3`) alongside total unreachability (`0.0`);
  the bowtie fixture proves `connectivity_ratio` (0.4) and `reachable_node_ratio` (0.8) genuinely
  diverge; `affected_service_count` matches `len(service_impacts)` directly; a fully-unreachable
  route contributes the real penalty constant, not zero; still-reachable degraded routes under a
  soft latency-injection failure sum their real positive cost deltas, cross-checked independently
  via `compute_route_change`; a hand-built route change with no baseline path contributes `0.0`;
  a triangle-plus-chain topology under an edge failure shows a newly emergent articulation point
  included and the pre-existing one excluded; a redundant diamond under a soft failure reports a
  genuine alternate route available while a chain under a soft failure with no redundancy reports
  none; an empty `route_changes` list reports `False`, not a fabricated `True`; the function never
  mutates its `graph`/`result` inputs; the returned fields round-trip through
  `ResilienceIndicators`' own Pydantic validation unchanged; a real end-to-end run over a topology
  discovered from synthetic packets confirms the pipeline runs cleanly end to end.
- Full repo suite (`pytest backend/tests experiments/tests simulator/tests`, run from repo root) —
  **532/532 passed** (up from 517/517), no regressions.
- `python -m scripts.validate_data_contracts` — 38/38 passed, no regression (no schema changes
  this phase — `ResilienceIndicators` already existed unchanged).
- `python -m scripts.check_ground_truth_boundary` — clean.

## Status

Resilience indicators (spec Phase 62, FR-1.35) are implemented and unit-verified:
`compute_resilience_indicators` turns a Phase 61 `FailurePipelineResult` into a real
`ResilienceIndicators` instance, with each of the six metrics' derivation resolved as an explicit,
documented decision rather than left implicit — including a proven (not asserted) divergence
between `connectivity_ratio` and `reachable_node_ratio`, and a literal reading of "bottleneck
emergence" as a pre/post articulation-point diff. `POST /simulation` remains `NotYetImplemented`,
unchanged from Phase 61. Digital-twin/experiment validation (Phase 63) and the structured
counterfactual scenario engine (Phase 64-66) remain ahead.
