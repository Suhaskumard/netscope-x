# Phase 79: real causal discovery

Spec addendum Phase 79: implement a constraint-based or score-based causal discovery algorithm (PC or
NOTEARS) as an alternative to Phase 53's correlation-plus-temporal-precedence heuristic, benchmark it
head-to-head against the existing generator on Phase 70's lagged traffic with Phase 68's `causal_analysis`
scoring, and never equate a discovered edge with proven causation.

**Decision: adopt conditionally, as an opt-in alternative candidate generator; not wired into the
pipeline.** Measured against Phase 53 it is better on every topology where either method scores above zero,
but its precision is low (about 0.3), and both methods fail on star topologies. Whether to route it into the
API or the Phase 56 evidence report is a separate decision this phase does not make.

**Non-negotiable stance (unchanged from Phase 53):** a discovered edge is a *candidate*. It means "after
conditioning on the other measured node activity, X_i's earlier activity still predicts X_j". It is not an
intervention result and is not proof of causation. Every candidate's rationale states the assumptions, and
`format_causal_candidate` appends `CAUSAL_CANDIDATE_DISCLAIMER`.

## What was built

- `backend/dependency/causal_discovery.py` (numpy + scipy, both already pinned): **time-series PC**, the
  parent-discovery stage of PCMCI. Constraint-based; PC rather than NOTEARS because a lag between series
  gives the orientation for free (a cause precedes its effect), so no v-structure phase is needed.
  - Variables: each node's per-bucket flow-arrival count (Phase 52's series, 10 s buckets), lags 1-5.
  - For each target node, every (node, lag) starts as a possible parent of X_j(t). A parent is removed when
    it is conditionally independent of the target given some subset (sizes 0-3, drawn from the 6 strongest
    remaining parents) of the others; the parent set is frozen per level so the result is order-independent
    (PC-stable). A final pass re-tests each survivor against the other survivors.
  - Test: partial correlation from least-squares residuals, Fisher-z p-value, alpha 0.05 (fixed in advance).
  - **Undefined tests are never resolved silently.** If the conditioning set is rank-deficient (one series
    is an exact delayed copy of another) or a residual has no variance, the parent is kept and the event is
    counted. A series with no variation at all is dropped and counted separately.
  - `to_causal_candidates` returns Phase 53's own `CausalCandidate`, so Phase 68's unmodified
    `evaluate_causal_analysis` scores it.
  - Assumptions (stated in every rationale): causal sufficiency, faithfulness, stationarity, linearity, and
    no simultaneous effect at the bucket width. Lag-0 links are neither found nor oriented. There is **no
    multiple-testing correction** (as in PCMCI), so about alpha of the candidate lagged parents pass by
    chance; a unit test pins this behavior.
- `experiments/causal_generators.py`: the control dataset. Each node's count is Poisson(base + coupling x
  its parents' counts one bucket earlier), roots are independent, so the declared directed edges are the
  true causal graph and no hidden common cause exists. Cycles in the declared edges are broken and reported.
  Caveat: the pipeline counts every flow *touching* a node, so a partner also sees the flows it receives and
  each observed series mixes in its dependants' activity.
- `experiments/causal_discovery_benchmark.py`, `scripts/run_causal_benchmark.py`: the benchmark.

## Why a control dataset

In Phase 70's traffic every node's pulses are the same intensity sequence delayed by its BFS tier
(`_pulse_packets`): each node is a delayed copy of one hidden driver, which violates causal sufficiency and
makes conditioning sets collinear. A poor result there would be ambiguous, so the same comparison was also
run on the control dataset, where the assumptions hold better.

## Benchmark

Both methods run on the same reconstructed capture and are scored by `evaluate_causal_analysis` against the
declared directed pairs (mapped to node ids by IP, as the matrix does). Six topologies x five completeness
levels x seeds 42-51 = 300 captures per dataset, 1,440 scored (method, capture) pairs. Alpha 0.05, max lag 5,
10 s buckets, all fixed in advance.

Pooled over every topology and completeness level:

| dataset | method | precision | recall | F1 | skeleton F1 | predicted / capture | reversed | spurious pairs | undefined tests |
|---|---|---|---|---|---|---|---|---|---|
| phase70 | phase53 | 0.217 | 0.018 | 0.033 ± 0.066 | 0.056 | 0.47 | 0.20 | 0.00 | n/a |
| phase70 | pc | 0.310 | 0.235 | 0.252 ± 0.233 | 0.341 | 10.33 | 1.49 | 5.78 | 0.209 |
| parent_driven | phase53 | 0.258 | 0.029 | 0.049 ± 0.104 | 0.050 | 0.58 | 0.03 | 0.00 | n/a |
| parent_driven | pc | 0.284 | 0.218 | 0.240 ± 0.226 | 0.329 | 9.87 | 1.05 | 5.97 | 0.000 |

("Skeleton F1" ignores direction: found the pair. "Reversed" is the right pair in the wrong direction;
"spurious" is a pair that is not a declared edge in either direction.)

Directed F1 at completeness 1.0 (mean ± stdev over 10 seeds):

| topology | phase70: phase53 | phase70: pc | parent_driven: phase53 | parent_driven: pc |
|---|---|---|---|---|
| small | 0.000 | 0.500 ± 0.000 | 0.067 ± 0.211 | 0.317 ± 0.277 |
| medium (star) | 0.000 | 0.000 | 0.000 | 0.012 ± 0.037 |
| large | 0.030 ± 0.042 | 0.296 ± 0.145 | 0.166 ± 0.017 | 0.323 ± 0.052 |
| multi_path | 0.057 ± 0.120 | 0.573 ± 0.017 | 0.000 | 0.406 ± 0.244 |
| multi_service (star) | 0.000 | 0.000 | 0.000 | 0.016 ± 0.034 |
| dynamic | 0.143 ± 0.000 | 0.231 ± 0.048 | 0.086 ± 0.074 | 0.392 ± 0.092 |

PC alpha sweep (completeness 1.0, pooled): on Phase 70 traffic F1 is 0.245 / 0.267 / 0.296 at alpha
0.01 / 0.05 / 0.10 with 9.5 / 10.7 / 11.7 spurious pairs per capture; on the control dataset 0.210 / 0.244 /
0.273 with 4.2 / 6.1 / 7.5. Precision does not improve with a stricter alpha (0.29 / 0.29 / 0.30 on Phase 70).

## Findings

1. **Better than Phase 53 everywhere it scores.** PC's pooled F1 is 0.252 against 0.033 on Phase 70 traffic
   and 0.240 against 0.049 on the control dataset. It is at least as good on every topology, and clearly
   better on `small`, `large`, `multi_path` and `dynamic`. Phase 53's near-zero score comes from finding
   almost nothing (0.47 candidates per capture); PC finds about ten.
2. **But roughly two thirds of PC's candidates are wrong.** Precision is 0.31 and 0.28; about 5.8-6.0
   spurious pairs per capture plus 1.0-1.5 reversed ones. A stricter alpha does not fix it. The likely cause
   is the absence of multiple-testing correction (with 12 nodes and 5 lags there are 60 candidate lagged
   parents per target and alpha 0.05 lets a few through by chance), which the independent-series unit test
   shows directly; this was not separately verified on the benchmark data.
3. **Star topologies are unsolved for both methods** (`medium`, `multi_service`: PC at most 0.08). The hub
   touches every leaf's flows, so its series is the sum of all of them and no single leaf-hub link stands out.
4. **The hidden-driver hypothesis was tested and only partly holds.** Phase 70's delayed-copy construction
   does hurt: 20.9% of PC's tests are undefined (collinear delayed copies) on Phase 70 traffic against 0.0%
   on the control dataset. But PC's F1 is about the same on both datasets (0.252 vs 0.240), so the assumption
   violation is not what limits it. A direct check over 20 Phase 70 captures (large, multi_path, dynamic,
   small; seeds 42-46; completeness 1.0) found 82 spurious pairs, of which only 23 (28%) had a lag equal to
   the pair's tier difference (the signature of two delayed copies of the driver); 60 of 86 true edges (70%)
   did. So delayed copies explain a minority of the false positives; the rest are unexplained.
5. **Direction errors are a minority of PC's mistakes.** Reversed pairs average 1.49 (Phase 70) and 1.05
   (control) per capture out of about 10 candidates, and skeleton F1 (0.341, 0.329) is only about 0.09 above
   directed F1 (0.252, 0.240). Time orients the edge; Phase 53 orients by node-id order. Most of PC's error is
   spurious pairs, not wrong direction.
6. **Observation loss.** F1 is largely stable down to completeness 0.5 on `small`, `multi_path`; `large` falls
   from 0.296 at 1.0 to 0.196 at 0.9 on Phase 70 traffic and stays near 0.2.
7. **Cost.** About 0.2-0.4 s per capture, versus 0.3-1.7 s for Phase 53's full dependency-strength pipeline.

## Complexity and data requirements

Per target node: up to (nodes x lags) candidate parents, and at each conditioning level up to C(6, s)
subsets per parent, so roughly nodes x lags x (1 + 6 + 15 + 20) tests, each a small least-squares solve. It
needs no labels and no training data, only enough time buckets: with T buckets the effective sample is T -
max_lag, and the Fisher-z test loses degrees of freedom with every conditioning variable. It was run on 60-100
buckets here; power at that size is limited and was not varied.

## Why adopt conditionally, and what would change that

Better measured F1 than the only existing generator, no training data, and orientation from time argue for
offering it. Low precision, the absence of multiple-testing control, and unsolved star topologies argue
against replacing Phase 53. Before it is used beyond a "lead to investigate," it would need a multiple-testing
correction or an FDR-controlled variant, a fix for hub fan-in (per-neighbour activity series rather than
per-node), and validation on traffic it was not designed against.

## Limitations

Linear Gaussian tests on count data; 6 topology shapes; no lag-0 effects; synthetic traffic with no hidden
real-world confounders other than the Phase 70 driver; the control dataset is this project's own
construction (it shows the method under its assumptions, not real-network performance) and still mixes
dependants' flows into a node's series; the alpha sweep is at completeness 1.0 only; power versus series
length was not swept; NOTEARS and lag-0 methods were not implemented.

## Verification

- `backend/tests/test_causal_discovery.py` (9 tests): Fisher-z values, chain direction and lag, common cause
  removed once conditioned on, false edges scale with alpha, exact delayed copies counted as undefined and not
  crashed, constant series dropped, short input and bad parameters, determinism, candidates carry the
  assumptions and the disclaimer and are scored by the real `evaluate_causal_analysis` (direction matters).
- `experiments/tests/test_causal_discovery_benchmark.py` (7 tests): control-dataset lag structure, determinism,
  cycles broken and reported, ground truth mapped by IP, reversed/spurious/skeleton scoring, both methods on
  identical ground truth, deterministic run and tables.
- Full suite 724/724; `validate_data_contracts` 55/55; `check_ground_truth_boundary` clean.
