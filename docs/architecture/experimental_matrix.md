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

- **`causal_analysis` was originally `0.0` in every cell (Phase 68's own finding); Phase 70 fixed
  this for real, partially** — see "Phase 70: synthetic traffic temporal-lag redesign" below for
  the full account. Root cause (as originally diagnosed): Phase 52's temporal-precedence signal
  needs genuine time-lagged cross-correlation between different node pairs' activity, and Phase 68's
  original synthetic traffic emitted all of one edge's packets in one simultaneous jittered burst,
  giving that detector nothing to find. Not evidence that Phase 50-53's causal inference is broken —
  that machinery is separately unit-tested against fixtures deliberately engineered with positive
  temporal precedence.
- **`topology_reconstruction`/`role_inference`/`pathforge`/`counterfactual` were numerically
  identical across all 5 completeness levels at `packets_per_edge=15`** (the default): e.g. the
  `medium` topology scored `pathforge` F1 = `0.7273`, `counterfactual` F1 = `0.8333` at every one of
  100%/90%/75%/50%/25% completeness (these single-target values are superseded by Phase 73's
  scoring fix and target sweep; see "Phase 73" below; Phase 74 explains the flat axis and adds
  a low-volume sweep that makes it move in the official run). Verified this is not a sampling bug, not a coincidence of
  identical results: re-running with a deliberately sparser `packets_per_edge=4` on the `large`
  topology shows a real, measurable effect — `edge_f1` = `1.0` at completeness 1.0/0.5, dropping to
  `0.951` at completeness 0.25 (3 of 32 declared edges lost). **Finding, stated plainly**: at this
  phase's default packet volume, individual declared edges have enough redundant evidence (multiple
  packet pairs) that losing up to 75% of them still leaves at least one surviving packet per edge
  for `discover_edges` to register it — real robustness to observation loss at this volume, not an
  absence of a completeness effect. The effect exists and is measurable, but only becomes visible
  once per-edge evidence volume is low enough that sampling can plausibly zero out an edge entirely.
- `role_inference` originally reported `accuracy=1.0`/`calibration_error≈0.0` in every cell because
  the role model was fit on the *same* synthetic fingerprints it was then scored against
  (in-sample). **Phase 71 replaced this with a real held-out measurement** — see "Phase 71" below.
- **`without_behavioral` produces byte-for-byte identical `pathforge`/`counterfactual` accuracy to
  baseline in every cell** — verified directly in `test_without_behavioral_ablation_produces_identical_pathforge_accuracy_to_baseline`.
  This is a real, honest null result: neither `run_failure_propagation_pipeline` nor
  `compare_counterfactual_outcome` reads `role_classifications` in any field that either evaluation
  module scores — only `ServiceImpact.role_classification`, an unscored annotation. A genuine
  finding (behavioral features are architecturally disconnected from PathForge/counterfactual
  prediction accuracy in this codebase as it stands today), not a placeholder.
- **`without_temporal` collapses `causal_analysis`'s `predicted_count` to `0`** in every cell —
  confirms the ablation mechanism works as designed (forcing every `temporal_precedence_score` to
  `0.0` before candidate generation reliably zeroes out promotion, matching Phase 53's own gate).

## Phase 70: synthetic traffic temporal-lag redesign

Per the master spec addendum (`NETSCOPE (1).pdf`, §"PHASE 70 — SYNTHETIC TRAFFIC TEMPORAL-LAG
REDESIGN"): fix `causal_analysis`'s degenerate `0.0` result by giving the synthetic traffic
generator genuine cross-node time-lagged structure.

**Design** (`experiments/synthetic_traffic.py`): a second, independent traffic component ("lag
pulses"), opt-in via new `pulse_*` parameters (default `pulse_cycles=0`, fully backward compatible
with every pre-existing caller/test). `_compute_tiers` assigns every declared node a real BFS
hop-distance from a root over the topology's undirected adjacency. For each of `pulse_cycles`
cycles, one shared random intensity multiplier is applied to every node's own pulse, timestamped
`tier(node) * pulse_lag_seconds` after the cycle start (`pulse_lag_seconds` defaults to `10.0`,
matching Phase 52's own bucket width exactly). Two nodes at tiers differing by `k` therefore carry
the same underlying intensity sequence, shifted by exactly `k` buckets.

**Two real bugs found and fixed during implementation** (both instructive, kept here rather than
silently smoothed over):

1. `estimate_temporal_precedence`'s bucketing counts **flows**, not packets
   (`Flow.first_seen` per bucket). The first pulse implementation put every intensity unit's packets
   on the *same* 5-tuple (same port), so they all reconstructed into a single flow regardless of
   intensity — the bucket-count series was completely insensitive to the intensity signal it was
   supposed to carry. Fixed by giving each intensity unit its own fresh source port, so intensity
   genuinely produces more distinct flows per bucket.
2. Per-packet timestamp jitter (a few hundred ms) was enough to independently tip one side of a
   lagged pair across its own bucket boundary while the other stayed put, corrupting the intended
   lag unpredictably. Fixed by removing randomized jitter from pulse timestamps entirely — every
   tier's nominal time differs from every other tier's by an *exact* multiple of the bucket width, so
   both sides shift by the identical fractional offset relative to whatever the detector's own
   `start` reference turns out to be, preserving the intended bucket-difference regardless of where
   the (separately jittered) structural-baseline traffic happens to set that reference.

**Real, measured result** (`matrix_runner.py`'s `_PULSE_CYCLES=12`, `_PULSE_PACKETS_PER_NODE=2`,
`_PULSE_INTENSITY_RANGE=(1,5)`, always enabled): a real 54-cell re-run (seed 42) now shows
**23 total predicted candidates, 11 correctly matched to ground truth**, up from `0`/`0` everywhere
before this phase:

| Topology level | `causal_analysis` F1 (completeness 1.0) |
|---|---|
| small (`simple_chain(3)`) | 0.0 — too few nodes/buckets for reliable signal |
| medium (`star(6)`) | 0.0 — hub fan-in (see below) |
| large (`multi_tier([2,4,4,2])`) | 0.0 at seed 42 (1 candidate promoted, wrong direction); non-zero at other seeds (verified directly, e.g. seed 1: 2/2 matched) |
| multi_path (`multi_path(3)`) | 0.286 — real, positive |
| multi_service (`star(10)`) | 0.0 — hub fan-in |
| dynamic (`dynamic_service_network`) | 0.143 — real, positive |

**Honest, traced limitation, not hidden**: star-shaped topologies (`medium`/`multi_service`) still
show no signal. The hub is every leaf's *only* neighbor, so the hub's own bucket-activity series
aggregates all leaves' pulses at one shared timing, and that aggregated, high-magnitude simultaneous
component dominates any single leaf-hub pair's lagged-correlation test. `multi_path`'s source/sink
have the same structural fan-in property but happened to still clear the bar at the tested seeds.
Fixing star/multi_path fully would need a different partner-selection scheme (e.g. round-robin
assignment so a hub doesn't receive every leaf's pulse at the identical instant) — left as further
work, not attempted here, since Phase 70's own stated bar ("make the score *sometimes* exceed 0.0,
not guarantee every edge") is met.

Also confirmed by direct measurement: `topology_reconstruction`/`role_inference`/`pathforge`/
`counterfactual` are numerically unaffected by enabling pulses (same values as Phase 68's own
findings above) — the new traffic component is additive and does not disturb the existing signal.

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
Scope decision above). Phase 70 (spec addendum) fixed `causal_analysis`'s original `0.0`-everywhere
result for real: a real 54-cell re-run now shows 23 total predicted candidates and 11 correctly
matched to ground truth, with 2 of 6 topology levels (`multi_path`, `dynamic`) reliably scoring a
genuine positive F1 — and the remaining 4 levels' continued `0.0` traced to a real, documented
structural limitation (hub fan-in for star-shaped topologies; too few nodes for `small`), not
silently glossed over. Phase 71 (Held-Out Role Inference Evaluation) and Phase 72 (Multi-Seed
Variance Reporting) are complete; see below. Phase 72's 10-seed run revises two earlier
single-seed claims (Phase 70's `multi_path` causal result and Phase 71's `large` held-out accuracy).
Phase 73 (Multi-Target Failure and Counterfactual Sweep) is complete. It also found and fixed a
scoring bug that had depressed every earlier `pathforge`/`counterfactual` number, so the Phase 68
and Phase 72 values for those two contexts are superseded; see "Phase 73" below. Phase 74
(Observation-Completeness Sensitivity Calibration) is complete: the official run now includes a
low-volume sweep whose persisted headline numbers vary with completeness.

## Phase 71: held-out role inference evaluation

`experiments/metrics/role_heldout.py::evaluate_role_held_out` runs leave-one-node-out
cross-validation: for each labeled node, a fresh `fit_role_model` is fit on every *other* node and
`classify_node_role` scores only the held-out one, so every held-out prediction comes from a model
that never saw that node's fingerprint or label (verified in
`experiments/tests/test_role_heldout.py`, which spies on every fit call and asserts each fold
trains on exactly n-1 examples). The matrix's `role_inference` raw result is now
`{in_sample, held_out, held_out_accuracy_seen_roles, unseen_role_fold_count, fold_count}`, and the
headline `MetricResult` (`precision`=accuracy, `calibration_error`=ECE) is the **held-out** score.
With fewer than 2 labeled nodes no fold is possible, so the cell falls back to in-sample only
(`held_out: None`).

Roles occurring exactly once in a topology cannot be learned when that node is held out, so that
fold is necessarily wrong; these are counted (`unseen_role_fold_count`) and
`held_out_accuracy_seen_roles` gives accuracy over only the folds whose role was learnable.

Real measurement (`run_matrix_cell`, completeness 1.0, seed 42, default `packets_per_edge`):

| topology | in-sample acc | held-out acc | held-out acc (seen roles) | unseen-role folds | held-out ECE |
|---|---|---|---|---|---|
| small | 1.000 | 0.000 | n/a | 3 / 3 | 1.000 |
| medium | 1.000 | 0.714 | 0.833 | 1 / 7 | 0.286 |
| large | 0.833 | 0.583 | 0.583 | 0 / 12 | 0.433 |
| multi_path | 0.800 | 0.200 | 0.333 | 2 / 5 | 0.800 |
| multi_service | 1.000 | 0.818 | 0.900 | 1 / 11 | 0.182 |
| dynamic | 0.750 | 0.250 | 0.333 | 2 / 8 | 0.700 |

Finding: the Phase 68 in-sample figures substantially overstated role-inference quality. Held-out
accuracy is lower in every cell, and calibration error is much higher, largely because these
topologies are small with several singleton roles (Naive Bayes over few examples per class). This
is a single seed; multi-seed variance is Phase 72's job. Full suite: 637/637 passed (up from
631/631); `validate_data_contracts` 55/55; `check_ground_truth_boundary` clean.

## Phase 72: multi-seed variance reporting

`experiments/multi_seed.py::run_multi_seed_matrix` runs the same 54-cell set as `run_full_matrix`
(6 topologies × 5 completeness levels, plus 4 ablations per topology at completeness 1.0) once per
seed through the real `run_matrix_cell`, persisting every run
(`matrix-<topology>-<completeness>-<ablation|baseline>-<seed>`). For each `(context, field)` pair
it reports `n` / mean / sample stdev (n−1) / min / max. `None` values (e.g. no detection latency)
are left out rather than counted as 0, and `n` records how many seeds contributed.

**What varies:** the seed drives traffic generation (`generate_packets_for_scenario`: timing,
jitter, pulse intensities) and observation loss (`sample_packets`). **What stays fixed:** the
declared topologies, including `dynamic`, whose generator seed stays 42. The spread below is
therefore traffic and observation variance on a fixed network.
`test_different_seeds_really_produce_different_traffic` guards against the seed being silently
ignored.

```
python -m scripts.run_experiment_matrix --root experiments_data --n-seeds 10   # seeds 42..51
python -m scripts.run_experiment_matrix --root experiments_data --seeds 42 43 44
```

Real measurement: 54 cells × 10 seeds (42–51), default `packets_per_edge`, 540 runs, 411 s wall
clock. Cells show `mean ± stdev [min, max]`. Baseline, completeness 1.0:

| topology | held-out role acc | role ECE | causal F1 | pathforge F1 | counterfactual F1 |
|---|---|---|---|---|---|
| small | 0.000 ± 0.000 [0.000, 0.000] | 1.000 ± 0.000 | 0.000 ± 0.000 | 0.667 ± 0.000 | 0.500 ± 0.000 |
| medium | 0.714 ± 0.000 [0.714, 0.714] | 0.286 ± 0.000 | 0.000 ± 0.000 | 0.727 ± 0.000 | 0.833 ± 0.000 |
| large | 0.375 ± 0.281 [0.000, 0.750] | 0.584 ± 0.251 | 0.030 ± 0.042 [0.000, 0.118] | 0.000 ± 0.000 | 0.000 ± 0.000 |
| multi_path | 0.340 ± 0.097 [0.200, 0.400] | 0.660 ± 0.097 | 0.057 ± 0.120 [0.000, 0.286] | 0.000 ± 0.000 | 0.000 ± 0.000 |
| multi_service | 0.827 ± 0.029 [0.818, 0.909] | 0.173 ± 0.029 | 0.000 ± 0.000 | 0.842 ± 0.000 | 0.900 ± 0.000 |
| dynamic | 0.375 ± 0.156 [0.250, 0.625] | 0.619 ± 0.145 | 0.143 ± 0.000 [0.143, 0.143] | 0.000 ± 0.000 | 0.000 ± 0.000 |

`topology_reconstruction` F1 and graph similarity, and `temporal_analysis` F1, are `1.000 ± 0.000`
in all 54 cells.

(The pathforge and counterfactual columns above are superseded by Phase 73's scoring fix and
target sweep; see "Phase 73" below.)

Held-out role accuracy across completeness levels (baseline):

| topology | 1.0 | 0.9 | 0.75 | 0.5 | 0.25 |
|---|---|---|---|---|---|
| medium | 0.714 ± 0.000 | 0.829 ± 0.060 | 0.857 ± 0.000 | 0.857 ± 0.000 | 0.857 ± 0.000 |
| large | 0.375 ± 0.281 | 0.225 ± 0.208 | 0.292 ± 0.193 | 0.250 ± 0.152 | 0.400 ± 0.179 |
| multi_path | 0.340 ± 0.097 | 0.480 ± 0.103 | 0.540 ± 0.097 | 0.580 ± 0.063 | 0.500 ± 0.141 |
| multi_service | 0.827 ± 0.029 | 0.891 ± 0.038 | 0.900 ± 0.029 | 0.900 ± 0.029 | 0.909 ± 0.000 |
| dynamic | 0.375 ± 0.156 | 0.250 ± 0.212 | 0.325 ± 0.105 | 0.312 ± 0.135 | 0.225 ± 0.079 |

(`small` is 0.000 at every level: all 3 of its roles are singletons.)

Findings:
- **Seed-stable metrics.** Topology reconstruction, temporal analysis, pathforge and
  counterfactual have stdev 0 at completeness ≥ 0.5; pathforge only moves at 0.25 (medium
  0.764 ± 0.077, multi_service 0.853 ± 0.033). These metrics do not respond to traffic noise at
  this scale. Their zeros (`large`, `multi_path`, `dynamic`) are structural, not unlucky seeds.
- **Held-out role inference is the noisiest metric.** On `large` it ranges from 0.000 to 0.750
  across seeds. Phase 71's single-seed 0.583 for `large` came from a favourable seed; the 10-seed
  mean is 0.375. `multi_path` (0.200 at seed 42, mean 0.340) and `dynamic` (0.250 at seed 42, mean
  0.375) were understated by seed 42.
- **Phase 70 is revised for `multi_path`.** Its causal F1 is not reliably positive: it is
  0.057 ± 0.120 at completeness 1.0 and 0.000 at every seed for completeness 0.75 and 0.5. Only
  `dynamic` is reliably positive (0.143 at every seed at completeness 1.0 and 0.9). `large` shows
  occasional positive seeds (max 0.118).
- **Some role accuracy rises as completeness drops** (medium 0.714 → 0.857, multi_path
  0.340 → 0.580, multi_service 0.827 → 0.909). This is what was measured, not an artifact of the
  aggregation. The cause has not been investigated. A plausible guess is that sampling thins
  noisy fingerprint features, but that is unverified.
- **Ablations.** Across all 10 seeds, only `without_temporal` changes any headline metric: it
  drives causal F1 to 0 wherever the baseline was positive. The other three ablations match
  baseline exactly on every headline column. The multi-seed data therefore confirms, rather than
  masks, that they have no measurable headline effect.

Verified: 7 tests in `experiments/tests/test_multi_seed.py`. Full suite 644/644 passed (up from
637/637). `validate_data_contracts` 55/55. `check_ground_truth_boundary` clean.

## Phase 73: multi-target failure and counterfactual sweep

Before this phase, PathForge and counterfactual failed one node per cell: the highest-degree
declared node. `run_matrix_cell` now fails up to `FAILURE_TARGET_COUNT = 3` structurally distinct
nodes. `_pick_failure_targets` chooses them on the *declared* topology, so target choice is part of
the experiment design and does not depend on inference quality.

- **Ranking.** Nodes are ranked by Phase 55's `compute_graph_criticality`: path-dependency impact,
  then betweenness, then degree, with the name breaking ties.
- **Distinctness.** Only the highest-ranked node of each structural signature is kept (articulation
  flag, impact, degree, betweenness, sorted neighbour degrees). A star therefore yields
  `{hub, one leaf}`, not three interchangeable leaves. The list is never padded, so fewer than K
  targets means fewer than K distinct classes exist.
- **Unobserved targets.** A target that sampling removed from the inferred graph is skipped and
  listed in `skipped_targets`, never replaced by another node.
- **Aggregation.** The headline `MetricResult` is the mean across targets. `Experiment.results`
  keeps every target's full evaluation. It also keeps an aggregate: n/mean/stdev/min/max for
  precision, recall and F1, `nontrivial_target_count` (targets whose failure strands at least one
  other node), and `max_leave_one_out_f1_shift`, the largest change in mean F1 from dropping any one
  target.

Selected targets (identical at every seed and completeness level; none were ever skipped):

| topology | targets (criticality order) |
|---|---|
| small | node-2 (articulation), node-1 |
| medium | hub (articulation), leaf-1 |
| large | tier1-1, tier0-1 |
| multi_path | sink, mid-1 |
| multi_service | hub (articulation), leaf-1 |
| dynamic | svc-1, svc-2, svc-5 |

`large`, `multi_path` and `dynamic` have no articulation point, so none of their targets strands
another node.

```
python -m scripts.run_experiment_matrix --root experiments_data --targets      # per-target report
python -m scripts.run_experiment_matrix --root experiments_data --n-seeds 10
```

### Scoring bug found and fixed

The first sweep scored every non-articulation target at F1 = 0.0, for PathForge and counterfactual
alike. The cause was not the prediction. PathForge and the counterfactual engine always list the
failed node itself as its primary service impact, but
`matrix_runner._actual_outcome_from_ground_truth` left the failed node out of the actual affected
set. A leaf failure therefore compared predicted `{leaf}` against actual `{}`, which scores 0.0 by
construction, even though `newly_unreachable` was correctly empty and connectivity accuracy was 1.0.
On hub targets the same mismatch added one guaranteed false positive.

The evaluators' own unit tests already count the failed node as affected
(`actually_affected_node_ids={"B", "D"}` for a failed `B` in both
`test_failure_propagation_validation.py` and `test_counterfactual_validation.py`). So the matrix
runner was the inconsistent part. It now adds the failed node to the actual set, and the
evaluators are unchanged. `test_failed_node_itself_counts_as_affected_so_a_leaf_is_not_zero_by_construction`
guards this.

This fix alone changes every earlier `pathforge`/`counterfactual` number. Phase 68's single hub
target on `medium` moves from 0.727 → 0.833 (PathForge) and 0.833 → 0.923 (counterfactual). On
`multi_service` it moves from 0.842 → 0.900 and 0.900 → 0.952. Phase 72's structural zeros on
`large`, `multi_path` and `dynamic` were this bug, not a property of those networks.

### Results

Real measurement: 54 cells × 10 seeds (42–51), 540 runs, 260 s. Baseline, `mean ± stdev [min, max]`
of the across-target mean F1:

| topology | pathforge F1 (c=1.0) | pathforge F1 (c=0.25) | counterfactual F1 (all c) |
|---|---|---|---|
| small | 1.000 ± 0.000 | 1.000 ± 0.000 | 0.733 ± 0.000 |
| medium | 0.917 ± 0.000 | 0.933 ± 0.035 [0.917, 1.000] | 0.795 ± 0.000 |
| large | 0.792 ± 0.081 [0.583, 0.833] | 0.775 ± 0.125 [0.583, 1.000] | 0.289 ± 0.008 [0.268, 0.292] |
| multi_path | 1.000 ± 0.000 | 1.000 ± 0.000 | 0.450 ± 0.000 |
| multi_service | 0.950 ± 0.000 | 0.955 ± 0.016 [0.950, 1.000] | 0.810 ± 0.000 |
| dynamic | 0.889 ± 0.000 | 0.922 ± 0.075 [0.778, 1.000] | 0.340 ± 0.000 |

(`large` counterfactual at c=0.25 is 0.287 ± 0.010; every other counterfactual cell is identical
across completeness levels.)

Per target, seed 42, completeness 1.0 (`--targets` output):

| topology | target | stranded | pathforge F1 | counterfactual F1 |
|---|---|---|---|---|
| small | node-2 | 1 | 1.000 | 0.800 |
| small | node-1 | 0 | 1.000 | 0.667 |
| medium | hub | 5 | 0.833 | 0.923 |
| medium | leaf-1 | 0 | 1.000 | 0.667 |
| large | tier1-1 | 0 | 0.667 | 0.250 |
| large | tier0-1 | 0 | 1.000 | 0.333 |
| multi_path | sink | 0 | 1.000 | 0.400 |
| multi_path | mid-1 | 0 | 1.000 | 0.500 |
| multi_service | hub | 9 | 0.900 | 0.952 |
| multi_service | leaf-1 | 0 | 1.000 | 0.667 |
| dynamic | svc-1 | 0 | 0.667 | 0.286 |
| dynamic | svc-2 | 0 | 1.000 | 0.333 |
| dynamic | svc-5 | 0 | 1.000 | 0.400 |

### Is the aggregate dominated by one target?

Largest `max_leave_one_out_f1_shift` over all 50 baseline cells (10 seeds × 5 completeness levels)
per topology:

| topology | pathforge | counterfactual |
|---|---|---|
| small | 0.000 | 0.067 |
| medium | 0.083 | 0.128 |
| large | 0.250 | 0.042 |
| multi_path | 0.000 | 0.050 |
| multi_service | 0.050 | 0.143 |
| dynamic | 0.111 | 0.030 |

Findings:
- **No single target dominates.** Dropping any one target moves the mean by at most 0.25, and by
  0.143 or less everywhere except `large` PathForge. On `large`, both targets vary by seed at
  completeness 1.0 (`tier1-1` 0.5–1.0, `tier0-1` 0.5–1.0), and the one that scores lower changes
  from seed to seed, so no single node consistently drives `large`'s 0.081 stdev. Before the
  scoring fix, the single-seed leave-one-out shift reached 0.450, and that spread was entirely the
  bug.
- **The old single-target choice was unrepresentative in one direction.** The highest-degree node
  was always the hardest case for PathForge on star topologies (hub 0.833 vs leaf 1.000 on
  `medium`) and the easiest for counterfactual (hub 0.923 vs leaf 0.667).
- **PathForge is accurate on non-articulation failures.** It correctly predicts that nothing is
  stranded. Its remaining errors are extra secondary service impacts. At seed 42, `tier1-1` and
  `svc-1` each report one dependent that ground truth does not count.
- **Counterfactual scores much lower on non-articulation targets (0.25–0.50).** The counterfactual
  engine reports service impacts on dependents that remain connected. The ground-truth outcome only
  models connectivity loss, so those impacts count as false positives. This is a limit of what the
  synthetic ground truth can express, not established evidence that the predictions are wrong.
  Scoring service-level impact would need a service-dependency ground truth, which does not exist
  yet.
- **Still mostly seed- and completeness-stable** (Phase 72's finding holds). Apart from `large`,
  PathForge varies only at completeness ≤ 0.75 (`dynamic`) or 0.25 (`medium`, `multi_service`).
  Counterfactual varies only on `large`.

Verified: 8 tests in `experiments/tests/test_multi_target.py` (target selection on real
topologies, headline = mean, leave-one-out shift, skip-never-substitute, report formatting, the
failed-node fix). Full suite 652/652 passed (up from 644/644). `validate_data_contracts` 55/55.
`check_ground_truth_boundary` clean.

## Phase 74: observation-completeness sensitivity calibration

Before this phase, the completeness axis was flat in the matrix's own output. Topology F1 was
1.000 in all 54 cells (Phase 72), and the only completeness effect ever shown came from an ad hoc
`packets_per_edge=4` side run (Phase 68).

**Mechanism.** `sample_packets` keeps each packet independently with probability c. A declared edge
disappears from the inferred topology only when every one of its packets is dropped, so an edge
carrying n packets survives with probability 1−(1−c)^n. `edge_survival_check` counts real
generated packets per declared edge:

- **Default volume.** 15 request/response pairs per edge, plus Phase 70's lag pulses, which each
  node sends repeatedly to its first neighbour. Declared edges carry 88–288 packets on average
  (`large` 88.5, `dynamic` 106.3, `medium` 160.7, `multi_service` 206.0, `small` 288.0). Expected
  survival is ≥ 0.9999 even at c=0.25, and every edge survived at seed 42. The flat axis is a
  consequence of volume, not of the pipeline ignoring completeness.
- **Low volume.** 1 pair per edge with pulses off gives n=2 packets per edge. Expected survival is
  0.75 at c=0.5 and 0.4375 at c=0.25. The observed fraction of surviving edges matches this. Over 30
  seeds at c=0.25 it averages 0.440 on `large` (32 edges) and 0.457–0.467 elsewhere; at c=0.5 it
  averages 0.750–0.789. So the sampler is unbiased, and single-seed deviations on small graphs are
  noise.

**Decision: a dedicated sweep, not a new default.** Lowering the default volume would break
comparability with every Phase 68–73 number. Removing pulses would destroy Phase 70's causal
signal. Instead, `matrix_runner.SENSITIVITY_SWEEP` (`variant="lowvol"`, `packets_per_edge=1`,
`pulse_cycles=0`) is part of the official matrix:

- `run_full_matrix` and `run_multi_seed_matrix` add one sweep baseline cell per (topology,
  completeness) pair, so the official run persists 84 cells.
- Sweep cells get their own id (`matrix-<topo>-<c>-baseline-lowvol-<seed>`) and record
  `packets_per_edge`, `pulse_cycles` and `variant` in `configuration`. Default cell ids and values
  are unchanged; the 10-seed default rows reproduce Phase 73 exactly.
- `run_experiment_matrix` prints the sweep table after every single-seed run.
  `--no-sensitivity-sweep` restores the 54-cell set.
- `causal_analysis` is not meaningful in sweep cells, because without pulses there is no lag signal.

```
python -m scripts.run_experiment_matrix --root experiments_data               # 84 cells + sweep table
python -m scripts.run_experiment_matrix --root experiments_data --n-seeds 10  # 840 runs
```

### Results

Official single-seed run (seed 42, 84 cells, 28 s): topology F1 varies with completeness on 5 of
6 levels. `large` falls from 1.000 → 0.984 → 0.792 → 0.694 (c=1.0/0.75/0.5/0.25), and `medium` role
accuracy falls from 0.857 to 0.167.

10 seeds (42–51, 840 runs, 236 s), sweep cells, `mean ± stdev`:

| topology | metric | c=1.0 | c=0.75 | c=0.5 | c=0.25 |
|---|---|---|---|---|---|
| small | topology F1 | 1.000 ± 0.000 | 1.000 ± 0.000 | 0.967 ± 0.105 | 0.667 ± 0.385 |
| medium | topology F1 | 1.000 ± 0.000 | 0.991 ± 0.029 | 0.915 ± 0.073 | 0.735 ± 0.148 |
| large | topology F1 | 1.000 ± 0.000 | 0.962 ± 0.030 | 0.835 ± 0.048 | 0.619 ± 0.085 |
| multi_path | topology F1 | 1.000 ± 0.000 | 0.991 ± 0.029 | 0.915 ± 0.073 | 0.735 ± 0.148 |
| multi_service | topology F1 | 1.000 ± 0.000 | 0.974 ± 0.028 | 0.891 ± 0.071 | 0.704 ± 0.143 |
| dynamic | topology F1 | 1.000 ± 0.000 | 0.972 ± 0.019 | 0.861 ± 0.065 | 0.656 ± 0.125 |
| medium | role accuracy | 0.857 ± 0.000 | 0.826 ± 0.059 | 0.671 ± 0.219 | 0.583 ± 0.243 |
| multi_service | role accuracy | 0.909 ± 0.000 | 0.847 ± 0.096 | 0.820 ± 0.127 | 0.704 ± 0.187 |
| multi_path | pathforge F1 | 1.000 ± 0.000 | 0.983 ± 0.053 | 0.908 ± 0.139 | 0.783 ± 0.153 |
| dynamic | pathforge F1 | 1.000 ± 0.000 | 0.989 ± 0.035 | 0.844 ± 0.101 | 0.721 ± 0.127 |
| large | counterfactual F1 | 0.292 ± 0.000 | 0.314 ± 0.031 | 0.387 ± 0.058 | 0.517 ± 0.091 |

Findings:
- **The effect is real and larger than seed noise.** On `large`, topology F1 at c=0.25 is
  0.619 ± 0.085, and the maximum over 10 seeds (0.745) is still well below 1.0. On every level
  except `small`, even the best of the 10 seeds at c=0.25 stays below 1.0 (max 0.745–0.909), while
  c=1.0 is 1.000 at every seed. The drop is at least 1.8 stdev (`medium`, `multi_path`) and up to
  4.5 stdev (`large`).
- **Edge survival fully explains the topology numbers.** Precision stays 1.0 (sampling removes
  evidence; it never invents it), so F1 ≈ 2s/(1+s) for survival s. The analytic s=0.75 gives 0.857
  at c=0.5, and s=0.4375 gives 0.609 at c=0.25. Measured: 0.835–0.915 and 0.619–0.735. The
  small-graph levels sit slightly high, consistent with their above-analytic survival.
- **Downstream metrics inherit the loss.** Role accuracy falls on `medium` and `multi_service` as
  fingerprints lose traffic. PathForge falls on `multi_path` and `dynamic`, where lost edges change
  which nodes a failure would strand. `large` and `dynamic` role accuracy are too noisy across seeds
  to show a clear trend.
- **Counterfactual F1 *rises* as completeness drops** (`large` 0.292 → 0.517, `dynamic` 0.340 →
  0.472). This is what was measured. A plausible but unverified reading: with fewer inferred edges,
  the counterfactual engine predicts fewer service impacts on connected dependents. Phase 73 showed
  those impacts are what the connectivity-only ground truth counts as false positives. The rise
  should therefore not be read as better prediction under loss.
- **`small` is the least sensitive.** It has only 2 edges, so it is almost all-or-nothing:
  0.667 ± 0.385 at c=0.25.

Verified: 6 tests in `experiments/tests/test_completeness_sensitivity.py` (distinct ids and
settings, `pulse_cycles=0` honoured, a real `large` topology F1 drop, default-volume survival,
observed-vs-analytic survival over 20 seeds, sweep persisted and skippable). Two Phase 72 tests
were updated for the new cell count and table column. Full suite 658/658 passed (up from 652/652).
`validate_data_contracts` 55/55. `check_ground_truth_boundary` clean.
