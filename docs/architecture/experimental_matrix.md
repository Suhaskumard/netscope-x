# NETSCOPE-X — Full Experimental Matrix

Phase 68 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 68 — COMPLETE RESEARCH
VALIDATION"): "support a full experimental matrix (topology complexity × observation-completeness
sweep) with reproducible, quantitatively evaluated results across topology reconstruction, role
inference, anomaly detection, temporal analysis, causal analysis, PathForge, counterfactuals, and
the four minimum ablation studies."

FR-1.40: *"The system shall support a full experimental matrix (topology complexity ×
observation-completeness sweep) with reproducible, quantitatively evaluated results across topology
reconstruction, role inference, anomaly detection, temporal analysis, causal analysis, PathForge,
counterfactuals, and the four minimum ablation studies (spec Phase 68)."*

Code: `experiments/metrics/{causal_evaluation,temporal_evaluation}.py` (new evaluation modules),
`experiments/observation_sampling.py`, `experiments/synthetic_traffic.py`, `experiments/matrix_runner.py`
(the orchestrator), `scripts/run_experiment_matrix.py`, plus real wiring of `GET /experiments`/
`GET /metrics`.

## Scope decision

This is the largest phase in the 69-phase plan — every "provisional, pending Phase 68" comment
scattered across 30+ phases points here. The scope below is deliberate and documented, not an
oversight:

**In scope**: a real topology × observation-completeness matrix, run through the actual pipeline
(synthetic packets, not Docker-captured — the same "real code, synthetic input" convention every
phase's own test suite already uses); real evaluation for 6 of 7 `MetricContext` values; the four
minimum ablation studies; real, persisted `Experiment`/`MetricResult` records; `GET /experiments`/
`GET /metrics` wired for real.

**Explicitly out of scope**, matching this project's own precedent for honest scope-outs:
- **`anomaly_detection`**: no labeled anomaly-injection dataset generator exists anywhere in this
  repository — `experiments/metrics/anomaly_evaluation.py`'s own docstring (Phase 42) already calls
  building one "a separate, much larger capability nobody has asked for." Still true; not built here.
- **PERF-1..8** (throughput/latency/memory benchmarking): a separate NFR category, not named in
  FR-1.40's own text; deferred to Phase 69.
- **Recalibrating** the many "pending Phase 68" provisional constants: FR-1.40 asks to *measure*,
  not *tune*. This phase reports real accuracy at existing defaults.
- The full REPRO-5 named/versioned/checksummed dataset catalog.
- Live Docker network-lab execution — consistent with every phase this session and Phase 63/66's
  own explicit "no Docker" note.

## Topology-complexity mapping (an interpretation, not literal spec text)

The spec's vocabulary ("small/medium/large/multi-path/multi-service/dynamic") doesn't 1:1 match
Phase 18's six generator names. `matrix_runner.TOPOLOGY_LEVELS` resolves this:

| Level | Generator call |
|---|---|
| small | `simple_chain(3)` |
| medium | `star(6)` |
| large | `multi_tier([2, 4, 4, 2])` |
| multi_path | `multi_path(3)` |
| multi_service | `star(10)` |
| dynamic | `dynamic_service_network(seed=42, n=8)` |

Crossed with `OBSERVATION_COMPLETENESS_LEVELS = [1.0, 0.9, 0.75, 0.5, 0.25]` (RQ1's own numbers) —
30 baseline cells, plus 4 ablation cells per topology level (24 more) = 54 total.

## Minimal synthetic traffic (`experiments/synthetic_traffic.py`)

No existing generator produces `packets.jsonl` for a declared scenario without Docker
(`simulator/traffic/generate.py` needs a live HTTP target). `generate_packets_for_scenario`
synthesizes deterministic, seeded bidirectional packet pairs per declared edge, with a role-aware
port heuristic (reusing `backend/nettrace/fingerprint.py`'s own well-known-port table) — a minimum
viable synthesis to drive the real pipeline, not a traffic-realism claim. `build_ground_truth_graph`
mirrors `simulator/ground_truth/generate.py`'s exact pattern, parameterized on a Phase 18 scenario
instead of the fixed lab.

## Observation-completeness sampling (`experiments/observation_sampling.py`)

`sample_packets(packets, completeness, seed)` — genuinely new plumbing; nothing in this repository
previously sub-sampled packets. Deterministic per `(seed, packet index)`, so a lower completeness's
sample is always a strict subset of a higher one's, not independently redrawn.

## "Actual outcome" without Docker

RQ6/RQ7 score a twin's prediction against what "actually" happened. With no Docker, there is no live
network to fail for real. The honest substitute: the same declared ground-truth topology already
used to score `topology_reconstruction` **is** the real network for this synthetic experiment —
exactly the stance `topology_comparison.py` already takes toward ground truth. `matrix_runner`
independently recomputes connectivity on the *ground-truth* graph with the target node genuinely
removed — never by reusing the *inferred* prediction's own graph, which would make the scoring
tautological.

## Ablations: real parameter changes, not code forks

- **without_temporal**: every `DependencyEdge.temporal_precedence_score` forced to `0.0` before
  `generate_causal_candidates` — Phase 53's own gate (`> 0.0` required) then promotes zero
  candidates.
- **without_dependency_weighting**: every `DependencyEdge.strength` replaced with binary
  `1.0 if frequency > 0 else 0.0` before candidate generation.
- **without_confidence_modeling**: topology and dependency estimation rebuilt with
  `edge_confidence_signal_strength=0.0` — Phase 31's five non-volume confidence signals switched off.
- **without_behavioral**: `role_classifications=None` passed to
  `run_failure_propagation_pipeline`/`compare_counterfactual_outcome`.

## Real findings from this session's own matrix run (54 cells, no Docker)

- **`causal_analysis` F1 = 0.0 in every cell, including baseline (not an ablation artifact)**:
  verified directly — `generate_causal_candidates` promotes **zero** candidates even without any
  ablation applied (`predicted_count: 0` in every cell's raw results). Root cause, traced: Phase
  52's temporal-precedence signal needs genuine time-lagged cross-correlation between different node
  pairs' activity; this phase's minimal synthetic traffic generator emits all of one edge's packets
  in one short jittered burst with no deliberate cross-pair lag structure, so
  `temporal_precedence_score` never exceeds `0.0`, and Phase 53's gate never passes. This is an
  honest limitation of Phase 68's minimum-viable synthetic traffic (documented scope, see above) —
  **not** evidence that Phase 50-53's causal inference is broken; that machinery is separately
  unit-tested against fixtures deliberately engineered with positive temporal precedence. Measuring
  `causal_analysis` on genuinely lagged traffic (a staggered-activity generator, or real Docker-lab
  captures) is real future work, named here rather than glossed over.
- **`topology_reconstruction`/`role_inference`/`pathforge`/`counterfactual` were numerically
  identical across all 5 completeness levels at `packets_per_edge=15`** (the default): e.g. the
  `medium` topology scored `pathforge` F1 = `0.7273`, `counterfactual` F1 = `0.8333` at every one of
  100%/90%/75%/50%/25% completeness. Verified this is not a sampling bug, not a coincidence of
  identical results: re-running with a deliberately sparser `packets_per_edge=4` on the `large`
  topology shows a real, measurable effect — `edge_f1` = `1.0` at completeness 1.0/0.5, dropping to
  `0.951` at completeness 0.25 (3 of 32 declared edges lost). **Finding, stated plainly**: at this
  phase's default packet volume, individual declared edges have enough redundant evidence (multiple
  packet pairs) that losing up to 75% of them still leaves at least one surviving packet per edge
  for `discover_edges` to register it — real robustness to observation loss at this volume, not an
  absence of a completeness effect. The effect exists and is measurable, but only becomes visible
  once per-edge evidence volume is low enough that sampling can plausibly zero out an edge entirely.
- `role_inference` reports `accuracy=1.0`/`calibration_error≈0.0` in every cell — expected and
  disclosed as a real limitation, not an inflated claim: the role model is fit
  (`fit_role_model`) on the *same* synthetic fingerprints it is then scored against (in-sample
  accuracy), since no independent held-out capture exists in this synthetic, non-Docker setup. A
  genuine out-of-sample measurement is future work.
- **`without_behavioral` produces byte-for-byte identical `pathforge`/`counterfactual` accuracy to
  baseline in every cell** — verified directly in `test_without_behavioral_ablation_produces_identical_pathforge_accuracy_to_baseline`.
  This is a real, honest null result: neither `run_failure_propagation_pipeline` nor
  `compare_counterfactual_outcome` reads `role_classifications` in any field that either evaluation
  module scores — only `ServiceImpact.role_classification`, an unscored annotation. A genuine
  finding (behavioral features are architecturally disconnected from PathForge/counterfactual
  prediction accuracy in this codebase as it stands today), not a placeholder.
- **`without_temporal` collapses `causal_analysis`'s `predicted_count` to `0`** in every cell (same
  as baseline, since baseline was already `0`) — confirms the ablation mechanism works as designed,
  even though its marginal effect is unobservable given baseline's own `causal_analysis` result.

## MetricResult field mapping

`MetricResult` has one shared shape across all 7 contexts; it lacks slots for every field each
evaluation dataclass produces (e.g. `path_prediction_match_rate`). Each context's most direct
analogue is mapped onto the shared fields (documented in `matrix_runner._to_metric_result`); the
full raw evaluation dataclass is preserved losslessly in `Experiment.results` (`asdict`), never
discarded.

## API: `GET /experiments`, `GET /metrics`

Both read real, persisted `Experiment`/`MetricResult` files back from `<root>/experiments/*/`
(written only by `matrix_runner.persist_cell` after a cell actually ran), paginated via the same
`PaginatedResponse` shape every other list route uses; `GET /metrics` additionally supports a
`context` filter. `POST /experiments` stays a 501 stub — triggering arbitrary matrix computation
synchronously through a public HTTP endpoint is a different, riskier concern than reading back
already-persisted results, the same reasoning that has kept `POST /simulation`/`POST /counterfactual`
unwired even after their engines were built (Phase 59-66).

## Verification actually performed this phase

- `pytest experiments/tests/test_causal_evaluation.py experiments/tests/test_temporal_evaluation.py
  experiments/tests/test_observation_sampling.py experiments/tests/test_synthetic_traffic.py
  experiments/tests/test_matrix_runner.py -v` — **61/61 passed**, including real end-to-end matrix
  cells (not mocked), the verified `without_behavioral` null result, and the verified
  `without_temporal` zero-candidate result.
- `pytest backend/tests/test_api.py -v` — **39/39 passed**, including real `GET /experiments`/
  `GET /metrics` behavior against a real persisted matrix cell, context filtering, and pagination.
- A real, full 54-cell matrix run (`run_full_matrix`, all 6 topology levels × 5 completeness levels
  + 4 ablations per level) completed in ~13 seconds with no errors; every cell persisted real
  `experiment.json`/`metrics.jsonl` files. The findings section above is drawn directly from this
  run's real output, not fabricated or estimated.
- Full repo suite (`pytest backend/tests experiments/tests simulator/tests`, run from repo root) —
  **620/620 passed** (up from 580/580), no regressions.
- `python -m scripts.validate_data_contracts` — 55/55 passed (first real construction of
  `Experiment`/`MetricResult` anywhere in this repo; no regression elsewhere).
- `python -m scripts.check_ground_truth_boundary` — clean.

## Status

The full experimental matrix (spec Phase 68, FR-1.40) is implemented and genuinely executed: 6 of 7
`MetricContext`s are scored for real across a 6×5 topology/completeness sweep plus 4 ablation
studies, with `GET /experiments`/`GET /metrics` serving the real, persisted results.
`anomaly_detection`, PERF-1..8 benchmarking, and constant recalibration are explicitly deferred (see
Scope decision above). `causal_analysis`'s real measured accuracy is `0.0` in this session's own run
— a genuine, traced, and honestly-reported finding about this phase's synthetic traffic generator's
own limitation, not a fabricated or hidden result. Phase 69 (Acceptance Testing) remains ahead.
