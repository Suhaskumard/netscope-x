# NETSCOPE-X — Experiment Recommendation Engine

Phase 67 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 67 — EXPERIMENT
RECOMMENDATION ENGINE"): generate experiment recommendations from measurable structural evidence.

FR-1.39: *"The system shall generate experiment recommendations from measurable structural
evidence (e.g., high-criticality node → suggest removal experiment, with stated reasoning) (spec
Phase 67)."*

Code: new `backend/dependency/experiment_recommendations.py` (`ExperimentRecommendation`,
`generate_experiment_recommendations`).

No research question governs this phase — RQ1-RQ7 is the full list; none names Phase 67. Only one
Phase 55 criticality signal was ever explicitly earmarked for it: `criticality.py`'s own
`METRIC_RATIONALE["is_articulation_point"]` already says it "directly feeds failure-injection
experiment suggestions (spec Phase 67)." This phase is exactly RQ6's own missing first step:
`docs/research/research_questions.md`'s RQ6 experiment design opens with *"for each candidate
critical component identified by criticality analysis (Phase 55)..."* — this module supplies that
candidate-selection step for real, closing the loop back to Phase 59 (real injection) and Phase 63
(predicted-vs-actual validation).

## Why `Experiment` isn't reused

`backend/app/models/experiment.py`'s `Experiment` schema is unsuited for a not-yet-run
recommendation: `random_seed`, `code_version`, `dataset_version`, `timestamp`, and `environment`
are all required with no default, since it models an executed/about-to-execute run record, not a
recommendation. This module returns its own plain `@dataclass(frozen=True)` instead, matching the
"no new Pydantic schema unless truly a Phase-04-reserved contract" precedent every prior no-schema
phase already followed.

## Placement

Lives in `backend/dependency/`, not `backend/simulation/`: its only real input is Phase 55's
`GraphCriticalityReport` (a `backend/dependency/` type), and its output (`FailureScenario`) has no
tie to any `backend/simulation/` pipeline result type — unlike Phase 61/62/66, which each lived
beside the `backend/simulation/` result type they consumed and extended.

## The two-category design

FR-1.39 gives one example (articulation point → removal experiment) but phrases the requirement
generically ("recommendations," plural, from "measurable structural evidence," not singular).
This module generalizes to two well-justified, evidence-grounded categories, both derived purely
from Phase 55's already-real `compute_graph_criticality` output — no new algorithm:

### 1. Structural single point of failure

Every node where `is_articulation_point` is `True` (FR-1.39's own literal example). Suggests a
`NODE_FAILURE` `FailureScenario`. Ranked by `path_dependency_impact` descending — a real measured
severity (how many other nodes would actually be stranded), not an invented score.

### 2. Routing chokepoint

Every node that is *not* an articulation point but whose `betweenness_centrality` exceeds the
graph's own mean betweenness across all nodes — a self-relative threshold, not an arbitrary
constant, matching this codebase's strong preference for non-magic-number formulas (Phase 61/62's
own ratio formulas). These nodes are central to routing without being a structural cut-vertex —
testing them with a hard failure would be uninformative, since redundant paths already exist — so
this category suggests `SERVICE_DEGRADATION` instead of `NODE_FAILURE`: it needs only
`target_node_id`, with no magnitude field to fabricate a number for (unlike `LATENCY_INJECTION`,
whose `latency_ms` this module would otherwise have to invent out of nothing). Ranked by
`betweenness_centrality` descending.

The threshold is strict (`>`, not `>=`): a fully symmetric graph, where every node's betweenness
equals the mean, produces zero chokepoint recommendations — there is no node genuinely more
central than the rest to single out.

## Reasoning and the disclaimer

Every recommendation's reasoning cites real measured values (`degree_centrality`,
`betweenness_centrality`, `path_dependency_impact`, `mean_incident_edge_confidence` — or an honest
"no incident edges observed" note when `None`), never a fabricated number, and always ends with an
unconditional disclaimer (mirroring Phase 48/53's own unconditional-disclaimer convention)
pointing back at Phase 59 (real injection) and Phase 63 (validation) — a recommendation is
structural evidence, not a validated prediction.

## What this phase deliberately does NOT do

- **No API wiring.** `GET`/`POST /experiments` (`backend/app/api/routes/experiments.py`) stays
  `NotYetImplemented`, tagged "Phase 67-68" in its own docstring, unchanged.
- **No execution of the suggested scenarios.** Running a recommendation's `suggested_scenario` is
  the caller's job via Phase 59's `apply_failure_scenario` (or Phase 65's counterfactual engine).
- **No edge-level recommendations.** Phase 55 computes no edge-level criticality metric, so this
  module makes no edge-level claim.
- **No new Pydantic schema.** `ExperimentRecommendation` is a plain dataclass;
  `FailureScenario`/`NodeCriticality` are reused exactly as Phases 59/55 left them.

## Worked example

Triangle-chain topology (A-B-C triangle, plus a C-D-E chain):

```
recommendations = generate_experiment_recommendations(graph)
# [0] node_id="C", category="structural_single_point_of_failure",
#     suggested_scenario.failure_type=NODE_FAILURE, evidence.path_dependency_impact=2
# [1] node_id="D", category="structural_single_point_of_failure",
#     suggested_scenario.failure_type=NODE_FAILURE, evidence.path_dependency_impact=1
# (C ranks first: removing it strands 2 nodes vs. D's 1)
```

A K_{2,3} bipartite topology (two hubs, three leaves, no articulation points anywhere) instead
produces two `"routing_chokepoint"` recommendations (`SERVICE_DEGRADATION`) for the two hubs, and
zero `"structural_single_point_of_failure"` recommendations — real, structurally correct evidence
that hard removal there would be uninformative.

## Verification actually performed this phase

- `pytest backend/tests/test_experiment_recommendations.py -v` — **7/7 passed**: a triangle-chain
  topology's two real articulation points are recommended for `NODE_FAILURE`, correctly ranked by
  `path_dependency_impact` severity; a K_{2,3} bipartite topology's two non-articulation-point
  hubs are recommended for `SERVICE_DEGRADATION` with zero structural-SPOF recommendations (no
  articulation points exist in that graph); a symmetric 4-cycle produces zero recommendations of
  either category; recommendations are fully deterministic across repeated calls; the exact real
  `path_dependency_impact` integer appears verbatim in its reasoning text; every recommendation
  ends with the disclaimer; a real end-to-end run over a topology discovered from synthetic
  packets confirms every returned recommendation carries a valid, already-schema-checked
  `FailureScenario`.
- Full repo suite (`pytest backend/tests experiments/tests simulator/tests`, run from repo root) —
  **580/580 passed** (up from 573/573), no regressions.
- `python -m scripts.validate_data_contracts` — 55/55 passed, unchanged (no schema changes).
- `python -m scripts.check_ground_truth_boundary` — clean.

## Status

The experiment recommendation engine (spec Phase 67, FR-1.39) is implemented and unit-verified:
`generate_experiment_recommendations` turns Phase 55's already-real criticality evidence into
concrete, ready-to-run `FailureScenario` suggestions across two well-justified categories, each
with real cited evidence and an honest disclaimer. No API route exists yet. Phase 68 (the full
experimental matrix and ablation studies) remains ahead.
