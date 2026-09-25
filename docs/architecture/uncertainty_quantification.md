# End-to-End Uncertainty Quantification (Phase 83)

Spec (master spec addendum, Arc B): propagate real error bars from packet-level observation noise through
topology, dependency and PathForge predictions as one model; a known-noisy input must show a correspondingly
wider band, measured.

**Verdict: the combined band widens with observation noise and the pre-registered criterion is met, but the
widening comes almost entirely from the topology stage. Dependency and PathForge bands do not reliably widen.**
Code: `experiments/uncertainty.py`, `experiments/uncertainty_benchmark.py`, CLI `scripts/run_uncertainty_benchmark.py`,
tests `experiments/tests/test_uncertainty.py`. Not wired into the pipeline.

## Method
One nonparametric bootstrap over the observed packets (per-packet resampling with replacement, matching
`sample_packets`' independent per-packet inclusion). Each draw runs the real, unmodified pipeline:
`reconstruct_flows -> build_topology_graph -> estimate_dependency_strength -> generate_causal_candidates ->
run_failure_propagation_pipeline`. Because one draw feeds all stages, outputs are jointly distributed. Reported:
edge presence probability and 90% band on `Edge.confidence`; 90% band on dependency `strength`; per-node
affected-set probability and 90% band on affected-set size (as a fraction of nodes). Ground truth is used only in
the benchmark for scoring; the module does not import it (tested).

## Results (real run: 6 topologies x 5 completeness levels x 3 seeds = 90 cells, 20 draws each)
Mean 90% band width:
| completeness | topology | dependency | pathforge | combined |
|---|---|---|---|---|
| 1.0 | 0.0225 | 0.1707 | 0.0120 | 0.0684 |
| 0.9 | 0.0269 | 0.1732 | 0.0117 | 0.0706 |
| 0.75 | 0.0323 | 0.1904 | 0.0118 | 0.0781 |
| 0.5 | 0.0528 | 0.2456 | 0.0144 | 0.1042 |
| 0.25 | 0.0944 | 0.2865 | 0.0357 | 0.1389 |

Lowest (0.25) vs highest (1.0) completeness, per (topology, seed), 18 pairs: topology wider 18/0/0 (Spearman
+0.529, p 8e-8); dependency 11 wider / 7 narrower (+0.121, p 0.26, not significant); pathforge 7 wider / 11 ties
(+0.141, p 0.18, not significant); combined 18/0/0 (+0.329, p 0.0015). Criterion (combined wider on a majority): MET.

Calibration against ground truth (Brier, lower is better): affected-node probability from the bootstrap beats
the point prediction's 0/1 membership at every level (0.0498 vs 0.0575 at 1.0; 0.0289 vs 0.0472 at 0.25).
Edge presence: bootstrap Brier is about 0 everywhere and beats `Edge.confidence` (0.0447 at 0.25), but that is
close to trivial here: every declared edge has 15+ packets, so the bootstrap gives presence 1.0 (blind-edge rate
0.000 at all levels).

## Limits (stated, not hidden)
- The bootstrap cannot see evidence that was never observed; blind-edge rate is 0 only because default volume
  makes edge loss rare (Phase 74). It should be re-measured on the Phase 74 low-volume sweep.
- Dependency width is already large at completeness 1.0 (0.17) and noisy, so the noise-driven change is not
  detectable at 3 seeds; PathForge width is 0 for most cells (affected set rarely changes).
- Bands are percentile bootstrap intervals, not verified to have nominal coverage; only Brier calibration was
  scored. One run, fixed seeds, B = 20.
