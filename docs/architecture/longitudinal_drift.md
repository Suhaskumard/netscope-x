# Longitudinal drift study (Phase 105)

`python -m scripts.run_drift_study --root experiments_data [--weeks 12] [--checkpoints 0 6 11] [--quick]`
(`experiments/drift_study.py`). Output: `<root>/drift/report.{json,md}`.

**What it is.** A synthetic network that changes every week by a seeded process (retire ~1 service, add 1-2, rewire ~1 edge, change
~1 role; always connected, the client root is never retired), from 8 services at week 0 to 12 at week 11. Each week is run through
the real pipeline (`run_matrix_cell`, new optional `scenario=` argument; `None` is bit-identical to before) with the DEFAULT
constants, 5 traffic seeds x completeness {1.0, 0.5}. At checkpoint weeks the real Phase 82 `calibrate()` (new optional `evaluator=`
argument) is run on that week's network with train seeds 42-44 and disjoint validation seeds 100-103.
**What it is not.** Evidence about a real network's evolution. The change process is an assumption, network size grows as a side
effect (reported as a covariate), and recalibration was only tested at weeks 0, 6 and 11.

## Drift measures
Theil-Sen slope with CI and Kendall tau over weekly means; week-0 mean as reference; noise yardstick = within-week seed stdev pooled
over all weeks (one week's 4-5 seeds gave a stdev too noisy: it produced a false "sustained degradation" on a planted flat series, which
is why the pooled form is used); first sustained degradation = 2 consecutive weeks worse than reference by more than that spread.
Recalibration counts as supported at a week if the checkpoint's `calibrate()` adopts a group (gain > seed spread, no guard regression),
or if constants adopted at an earlier checkpoint pass the same rule against the defaults on that week's validation seeds.

## Result (12 weeks, 5 seeds, real run)
- **No measurable drift of the default constants.** Topology F1 and temporal F1 are 1.0000 in every week (constant series, at the
  ceiling). Causal F1 is near zero and noisy (0.00-0.14; Theil-Sen +0.003/week, CI -0.009..+0.012, Kendall p=0.30). Role calibration
  error is high and noisy (0.47-0.93, slope -0.019/week, CI -0.041..+0.006, p=0.12). No metric shows a sustained degradation. Two of
  the four metrics cannot show drift because they are at the ceiling, and causal F1 is near its floor, so "no drift" here is weak
  evidence for causal and calibration error and no evidence at all for topology/temporal beyond "stayed perfect".
- **Recalibration is supported at every checkpoint, but not because of drift.** At week 0, before anything evolved, the temporal group
  is adopted (causal F1 0.0071 -> 0.1000, gain +0.093 vs seed spread 0.014; `dependency_temporal_bucket_seconds` 10 -> 2, lag
  unchanged). Those week-0 constants also beat the defaults at week 6 (causal F1 +0.098, spread 0.000) and week 11 (+0.117, spread
  0.051) with topology and temporal F1 unchanged. So the defaults are mis-tuned for these evolving networks from the start (a static
  effect), and the tuned value stays useful as the network changes; nothing shows it decaying.
- **The tuner alone missed this at weeks 6 and 11** (its own checkpoint runs adopted nothing, 13 evaluations per group), which is
  why the carried-over check exists: a "not necessary" from the small search budget alone would have been wrong by the pre-registered
  rule. This also contradicts Phase 82's static-matrix result (nothing adopted; a 18.8 s bucket lowered causal F1): the optimum
  depends on the topology set, and this study's networks are small (8-12 services).
- Causal F1 at defaults is ~0 to begin with, so a 0.1 gain is large relative to it and small in absolute terms.

## Limits
Synthetic evolution; 12 weeks; 5 traffic seeds; three checkpoints; small BO budget (5 initial + 8 iterations per group); one
evolution seed (7). A different weekly process or a real network could drift differently. The constants were not applied to
`Settings`: adoption stays a deliberate manual step, as in Phase 82.
