# Formal statistical significance of the ablation effects (Phase 104)

`python -m scripts.run_significance_analysis --root experiments_data --n-seeds 10` (`experiments/significance.py`) runs the baseline
and each of the 4 ablations for real at completeness 1.0, per topology and seed, using the same seed for a baseline/ablation pair so
both share generated packets and differ only by the ablation. It reports `d = ablated - baseline` per (ablation, context, field).

## Method
- Paired two-sided t-test (verified against a hand formula and scipy), Cohen's dz.
- Percentile bootstrap 95% CI of the mean difference (10,000 resamples, seeded, deterministic).
- Minimum mean difference detectable at 80% power for the n actually run, so a non-significant result says what it could not detect.
- Holm-Bonferroni within each family (per-topology rows; pooled rows). **Significant** = Holm p < 0.05 and CI excludes 0;
  only one of the two = **inconclusive**.
- All-zero differences are **identical** (t undefined), a stronger statement than p = 1. A None metric drops that pair and is
  counted; it is never coerced to 0. A constant nonzero shift (zero variance) gets p = 0 and is flagged by a degenerate CI.
- Pooled rows (topology x seed) are not independent samples of networks: the six topologies are fixed designs. Per-topology rows have
  n = seeds and are the more conservative reading.

## Result of the run (10 seeds, 42..51, all 6 topologies; 456 per-topology and 76 pooled groups)
- Only `without_temporal` has any effect. The other three ablations (`without_dependency_weighting`, `without_confidence_modeling`,
  `without_behavioral`) are **identical** to the baseline on every metric, every pair.
- Pooled, Holm-significant: causal F1/precision/recall drop (F1 -0.038, CI [-0.058, -0.022]) and pathforge F1/precision **rise**
  (F1 +0.053, CI [+0.032, +0.076]). Removing temporal precedence made pathforge look better here; that is a measured result, not a
  bug claim, and the mechanism was not investigated. Counterfactual F1/precision moved by about 0.0004 and is indistinguishable from noise.
- Per topology, the effects live in only two topologies: `dynamic` and `large`. In `dynamic` every seed shifted by exactly the same
  amount (deterministic, so p = 0 with a zero-width CI). In `large` pathforge F1 (+0.208) is significant but causal F1 (-0.030) is
  only **inconclusive** after Holm (adjusted p 0.408, though the CI excludes 0). Of 456 per-topology groups: 441 identical,
  7 significant, 3 inconclusive, 5 indistinguishable from noise.
- The mean of differences equals the difference of means over the same pairs to 7e-17.

## Limits
- n = 10 seeds per topology; the report gives the detectable difference for each group.
- Seeds vary traffic generation only, not the topology, so this says nothing about generalizing across networks.
- Synthetic data with a known generator; identical results across three ablations show those switches do not change these metrics on
  this data, not that the components are useless in general.
- Only completeness 1.0 and default cell parameters were tested. About 6 minutes for 10 seeds x 6 topologies.
