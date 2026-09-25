# Automated Constant Calibration (Phase 82)

Spec (master spec addendum, Arc B): calibrate every constant flagged "provisional, pending Phase 68" against real
ground truth across the matrix, report before/after for each, and never adopt a value without measured improvement.

**Verdict: no constant was adopted. The defaults were not beaten on held-out seeds. Nothing in `Settings` changes.**
Code: `experiments/calibration/` (`bayes_opt.py`, `calibrate.py`, `constants.py`), CLI
`scripts/run_constant_calibration.py`, tests `experiments/tests/test_constant_calibration.py`.

## Protocol
- Constants are tuned in three groups (topology, temporal, causal_strength), each by numpy Gaussian-process
  Bayesian optimization on TRAIN seeds 42-44 against its stage's real matrix F1 (`run_matrix_cell`).
- Baseline and tuned values are re-scored on disjoint VALIDATION seeds 100-103 over the full completeness range
  (60 cells per seed). Adoption rule, fixed in advance: validation gain must exceed the baseline's own across-seed
  standard deviation, and no guard metric may fall by more than its own spread.
- Groups run in order on top of adopted values; each adopted constant would also be reverted alone to give its
  marginal gain. The tool only reports; applying a value is manual.

## Results (real run, 6144 cells)
| group | objective | validation before | after | gain | baseline spread | decision |
|---|---|---|---|---|---|---|
| topology | topology F1 | 0.9433 | 0.9433 | +0.0000 | 0.0071 | keep |
| temporal | causal F1 | 0.0370 | 0.0222 | -0.0148 | 0.0301 | keep |
| causal_strength | causal F1 | 0.0370 | 0.0370 | +0.0000 | 0.0301 | keep |

The optimizer returned the defaults for six constants (nothing it tried beat them on train). For the temporal
group it proposed bucket 18.8 s and max lag 9, which lowered validation causal F1. Joint adopted = joint baseline
in every context (topology 0.9433, temporal 0.9940, causal 0.0370).

## Limits
- `path_engine._DEFAULT_LATENCY_COST_SCALE` cannot be calibrated: it only enters `LATENCY_INJECTION` scenarios and the
  matrix injects `NODE_FAILURE` only. It stays 100.0 ms, still provisional.
- Causal F1 is about 0.04 at baseline, so its baseline spread (0.030) is close to the score and small gains are
  undetectable; a null result there says the constants are not the bottleneck, not that they are optimal.
- Behavior windows, node_baseline minimum history and the Phase 78 floors were out of scope (no ground truth to
  score them against). One run, fixed seeds.
