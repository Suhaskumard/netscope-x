# NETSCOPE-X — Counterfactual Outcome Comparison

Phase 66 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 66 — COUNTERFACTUAL
OUTCOME COMPARISON"): compare baseline vs. counterfactual outcomes across paths, connectivity,
latency, affected services, bottlenecks, and propagation.

FR-1.37: *"The system shall compare baseline vs. counterfactual outcomes across paths,
connectivity, latency, affected services, bottlenecks, and propagation (spec Phase 66)."* FR-1.38
also cites Phase 66 for RQ7's "predicted vs. actual" comparison.

Code: new `backend/simulation/counterfactual_comparison.py`
(`compare_counterfactual_outcome`, `CounterfactualComparisonResult`) for FR-1.37, and new
`experiments/metrics/counterfactual_validation.py`
(`evaluate_counterfactual_prediction`, `ActualCounterfactualOutcome`) for FR-1.38/RQ7's second
half.

## Pure composition — `path_engine.py` and every consumed module stay untouched

This phase reimplements none of Phase 54's `propagate_failure`, Phase 55's
`compute_graph_criticality`, or Phase 60's `compute_connectivity`/`compute_route_change`; it only
calls them against a baseline `TopologyGraph` and a Phase 65 `CounterfactualExecutionResult`.
`path_engine.py`, `counterfactual_engine.py`, `failure_propagation_pipeline.py`,
`resilience_indicators.py`, `criticality.py`, `failure_propagation.py`, and every
`backend/app/models/*.py` file are consumed read-only — none of them are modified by this phase,
matching the session's established "don't modify a completed phase's module" convention.

## Decision 1 — the "propagation" axis (the harder of the two open design questions)

`CounterfactualScenario` carries no `CausalCandidate` feed at all — nothing ties a counterfactual
to causal evidence the way `FailureScenario` does via Phase 61's separately-supplied `candidates`
argument. A propagation axis that only worked when causal evidence happened to be supplied would
produce nothing for the common case (a caller who just built and executed a scenario with no
causal-candidate list in hand, exactly as Phase 65's own test suite does).

**Resolution: compute both, as two separate, clearly labeled fields, never merged:**

- **`structural_propagation_impacts`** (always computed, no extra input needed): a BFS
  hop-distance cascade from the change site (the targeted node, the targeted edge's two
  endpoints, or `ADD_ROUTE`'s two endpoints) over `baseline_graph`'s plain adjacency, restricted
  to nodes that actually became unreachable (`newly_unreachable_node_ids`), bucketed into
  `SECONDARY` (hop 1), `TERTIARY` (hop 2), or `FURTHER` (hop ≥ 3) — mirroring `ImpactOrder`'s own
  three-tier naming without claiming its causal meaning. Honestly derivable from data this module
  already computes; explicitly labeled *structural*, never overclaiming causal evidence it
  doesn't possess.
- **`causal_propagation_impacts`** (optional, only when both a `candidates` list is supplied AND
  the scenario has a `target_node_id`): calls Phase 54's real `propagate_failure(candidates,
  scenario.scenario_id, scenario.target_node_id)` completely unmodified — exactly Phase 61's own
  gating condition, reused rather than reinvented. `causal_propagation_evaluated` reports whether
  this ran at all.

Fusing the two into one list would misrepresent structural inference as causal evidence — exactly
the fabrication spec §21 ("No Fake Metrics") forbids, and the same reasoning Phase 61's own
propagation-origin decision already established for real failures.

## Decision 2 — the "latency" axis (the second hard design question)

For the three **hard** actions (`REMOVE_NODE`/`REMOVE_EDGE`/`ADD_ROUTE`) the isolated graph is
already structurally different from baseline, so `compute_route_change(baseline_graph,
execution.graph, source, target)` — called with no `failure=` argument — already captures the
real path-cost difference correctly; the structural diff alone does the work. For the three
**soft** actions (`INCREASE_LATENCY`/`REDUCE_BANDWIDTH`/`INCREASE_TRAFFIC`) the isolated graph is
structurally *identical* to baseline (only `degraded_edge_ids` marked) — the same call with no
`failure=` would show zero difference, defeating the entire point of comparing a
latency/bandwidth/traffic counterfactual.

**Resolution: `_maybe_adapter_injection`, a translation adapter, not a parallel reimplementation**
of `_edge_weight`'s formula:

| `CounterfactualAction` | Maps to | Extra field |
|---|---|---|
| `INCREASE_LATENCY` | `FailureType.LATENCY_INJECTION` | `latency_ms=scenario.magnitude` |
| `REDUCE_BANDWIDTH` | `FailureType.BANDWIDTH_REDUCTION` | `bandwidth_reduction_ratio=scenario.magnitude` |
| `INCREASE_TRAFFIC` | *(none)* | — returns `None`, no adapter |
| hard actions | *(none)* | — returns `None`, structural diff already correct |

The adapter constructs a synthetic `FailureScenario`+`FailureInjectionResult` pair and passes it
as `failure=` to `compute_route_change`, reusing Phase 60's exact tested weighting formula with
zero logic duplication — just field-name translation. An out-of-range `magnitude` for
`REDUCE_BANDWIDTH` (`FailureScenario.bandwidth_reduction_ratio` is `ge=0,le=1`) raises Pydantic
`ValidationError` from inside the adapter — a decidable, honest failure, never silently clamped,
consistent with this codebase's fail-fast convention elsewhere. `INCREASE_TRAFFIC` has no
`FailureType` analog (the same documented gap Phase 64/65 already recorded for this exact action)
— it correctly produces zero extra path cost, an honest limitation, not an invented number.
Reimplementing `_edge_weight`'s formula in this module instead was considered and rejected: it
would duplicate tested numeric logic every one of Phase 61-65's own module docstrings explicitly
commits to never re-deriving ("pure composition, not new logic").

## The remaining four axes

| Axis | Calls | Bounded pair/node set | Why |
|---|---|---|---|
| **Paths** | `compute_route_change` per pair, with the latency adapter applied uniformly | Change site's former direct neighbors × target; the targeted edge's own two endpoints; or `ADD_ROUTE`'s own `(source_node_id, target_node_id)` | Mirrors Phase 61's own already-justified bounded-pair convention exactly — no undocumented all-pairs sweep. |
| **Connectivity** | `compute_connectivity(baseline_graph)` vs `compute_connectivity(execution.graph)` | Whole graph | No `failure=` parameter exists on `compute_connectivity` by design (soft failures never change structure) — for the three soft actions this correctly reports "unchanged," the truthful answer. |
| **Affected services** | Union of `execution.removed_node_ids` (`"removed"`), `newly_unreachable_node_ids` (`"newly_unreachable"`), both endpoints of every `changed=True` route (`"route_changed"`), and every causally-propagated node (`"propagation"`) | Union of sets already computed elsewhere | Generalizes Phase 61's `ServiceImpact`/reason itemization from two reasons to four; reasons are `"+"`-joined per node when multiple apply, exactly Phase 61's `"propagation+routing"` pattern. |
| **Bottlenecks** | `compute_graph_criticality(baseline_graph)` vs `compute_graph_criticality(execution.graph)`; `sorted(post_articulation_ids - pre_articulation_ids)` | Whole graph | Reimplements Phase 62's own ~4-line diff inline (it's a private helper there) rather than importing a `_`-prefixed cross-module symbol. |

## RQ7: `evaluate_counterfactual_prediction` (FR-1.38, second half)

Mirrors `experiments/metrics/failure_propagation_validation.py` (Phase 63, RQ6) closely, narrowed
to three of its four metrics (affected-node precision/recall/f1, path-prediction match rate,
connectivity-prediction accuracy) plus a single optional `affected_service_count` resilience
component — `path_degradation_score`/`bottleneck_node_ids`-style "actual" values remain honestly
un-evaluable from a minimal caller-supplied outcome, exactly the reasoning Phase 63 already
established for RQ6.

**Lab-realizability gating** is the one genuinely new piece RQ7 requires beyond Phase 63's
pattern. RQ7's own text: *"Where a counterfactual is not realizable in the lab (e.g., a purely
hypothetical route that doesn't exist), report the prediction as unvalidated rather than implying
it was tested."* Whether a given `CounterfactualScenario` corresponds to something that could
actually be done in the lab is a caller judgment, not inferable from `CounterfactualAction` alone
(a `REMOVE_NODE` is usually realizable but not universally; an `ADD_ROUTE` might correspond to
real spare cabling in some lab topologies) — so `ActualCounterfactualOutcome.lab_realizable` is
caller-supplied, and `False` short-circuits every metric to `None`/empty rather than computing
anything, an honest "not tested," never a fabricated score.

Returns a plain `@dataclass(frozen=True)`, never `MetricResult` — no experiment registry exists
yet; `MetricContext.COUNTERFACTUAL` stays reserved and unpopulated, deferred to Phase 68, exactly
as `MetricContext.PATHFORGE` is for Phase 63's own module.

## What this phase deliberately does NOT do

- **No modification to any consumed module.** See "Pure composition" above.
- **No new Pydantic schema.** Both new modules' result types are plain dataclasses, matching
  every prior phase with no Phase-04-reserved schema.
- **No API wiring.** `POST /counterfactual` stays `NotYetImplemented`, unchanged.
- **No experiment-recommendation consumption.** Using this module's structural evidence (e.g. a
  high-criticality node → suggest a removal experiment) is Phase 67's job (FR-1.39).
- **No `MetricResult`/ablation-matrix wrapping.** Deferred to Phase 68.
- **No real Docker-lab capture mechanism** for `ActualCounterfactualOutcome` — same "no Docker
  this session" limitation already recorded in Phase 63's own docstring for `ActualFailureOutcome`.

## Worked example

Diamond topology (A-B-D cheap / A-C-D expensive), `REMOVE_NODE` on B:

```
execution = execute_counterfactual_scenario(graph, scenario)
result = compare_counterfactual_outcome(graph, execution)
# bottleneck_node_ids: ["C"]  (C becomes the sole cut-vertex once B, the other half of the cycle, is gone)
# route_changes: 2 entries, (A,B) and (D,B), both current_path=None (B removed)
# total_latency_delta: 2 * _UNREACHABLE_PATH_PENALTY
# newly_unreachable_node_ids: []  (single component preserved: {A,C,D})
# service_impacts: A("route_changed"), B("removed+route_changed"), D("route_changed")
# structural_propagation_impacts: []  (nothing became unreachable)
# causal_propagation_evaluated: False  (no candidates supplied)

# RQ7, lab-realizable:
evaluate_counterfactual_prediction(result, ActualCounterfactualOutcome(lab_realizable=True, ...))
# validated=True, real scored metrics

# RQ7, not lab-realizable (e.g. a hypothetical ADD_ROUTE):
evaluate_counterfactual_prediction(result, ActualCounterfactualOutcome(lab_realizable=False))
# validated=False, unvalidated_reason="counterfactual not lab-realizable (RQ7)", every metric None
```

## Verification actually performed this phase

- `pytest backend/tests/test_counterfactual_comparison.py -v` — **12/12 passed**: a `REMOVE_NODE`
  on a diamond topology creates a real new bottleneck and shows real route collapse; a
  `REMOVE_NODE` on a chain topology genuinely splits connectivity and produces a real one-hop
  structural propagation impact, with `"+"`-joined service-impact reasons; a `REMOVE_EDGE` with a
  real alternate route shows a real nonzero cost delta with unchanged connectivity; an
  `INCREASE_LATENCY` counterfactual's adapter produces the exact expected `+1.0` cost per degraded
  edge (matching Phase 60's own latency-injection test numbers); an out-of-range `REDUCE_BANDWIDTH`
  magnitude raises `ValidationError`; `INCREASE_TRAFFIC` correctly shows zero latency delta (the
  documented gap); `ADD_ROUTE` shows a real new route with no structural propagation; the
  propagation axis is verified both without and with real `CausalCandidate`s (matching a direct
  `propagate_failure` call exactly); a `baseline_graph_id` mismatch raises; the function never
  mutates its inputs; a real end-to-end run over a topology discovered from synthetic packets.
- `pytest experiments/tests/test_counterfactual_validation.py -v` — **6/6 passed**: a
  non-lab-realizable outcome reports every metric `None`; a perfect-match outcome (derived
  directly from the real predicted result) scores 1.0 on every metric; a deliberate affected-node
  mismatch degrades only that metric; an empty-vs-empty affected-node case reports perfect
  agreement; an unsupplied `actual_affected_service_count` is honestly skipped, not fabricated; a
  predicted pair absent from `actual_reachable_pairs` is excluded from the match-rate denominator.
- Full repo suite (`pytest backend/tests experiments/tests simulator/tests`, run from repo root) —
  **573/573 passed** (up from 555/555), no regressions.
- `python -m scripts.validate_data_contracts` — 55/55 passed, unchanged (no schema changes).
- `python -m scripts.check_ground_truth_boundary` — clean.

## Status

Counterfactual outcome comparison (spec Phase 66, FR-1.37) is implemented and unit-verified: all
six named axes — paths, connectivity, latency, affected services, bottlenecks, and propagation —
are computed by composing Phase 54/55/60/61's already-tested machinery, with the two hardest
design questions (propagation's structural-vs-causal split, latency's translation adapter)
resolved as firm, documented decisions. RQ7's predicted-vs-actual counterfactual validation
(FR-1.38's second half) is also implemented, narrowed and gated for lab-realizability exactly as
RQ7's own text requires. `path_engine.py` and every other consumed module remain untouched. Phase
67 (experiment recommendations from structural evidence) and Phase 68 (ablation matrix,
`MetricResult` wrapping) remain ahead.
