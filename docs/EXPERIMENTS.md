# NETSCOPE-X — Experiments Guide

Phase 69 documentation deliverable. Covers running the research validation matrix built in Phase 68
(FR-1.40) and how to read its output; see `docs/architecture/experimental_matrix.md` for the full
design rationale and `docs/acceptance_testing.md` FR-1.38/1.39/1.40 rows for what's verified.

## Running the full matrix

```bash
python -m scripts.run_experiment_matrix --root experiments_data
```

Runs the real pipeline (capture -> normalize -> flows -> topology -> roles -> archaeology ->
dependencies -> causal candidates -> digital twin -> simulation -> counterfactuals) over synthetic,
seeded packet captures across:

- **6 topology-complexity levels**: `small`, `medium`, `large`, `multi_path`, `multi_service`,
  `dynamic` (`experiments/matrix_runner.py::TOPOLOGY_LEVELS`)
- **5 observation-completeness levels**: `1.0, 0.9, 0.75, 0.5, 0.25` (packet sub-sampling via
  `experiments/observation_sampling.py`)
- **4 minimum ablation studies**: `without_temporal`, `without_dependency_weighting`,
  `without_confidence_modeling`, `without_behavioral` (one run per topology level at completeness 1.0)

Options: `--seed <int>` (default 42, for reproducibility per REPRO-2), `--no-ablations` to skip the
ablation runs.

A full run (54 cells) completed in ~13s in Phase 68's own verification. Results are written to
`<root>/experiments/<experiment_id>/{experiment.json, metrics.jsonl}` — real `Experiment` and
`MetricResult` records (spec REPRO-1: every record carries `experiment_id`, `dataset_version`,
`code_version`, `configuration`, `random_seed`, `timestamp`, `environment`, `parameters`, `results`).

## What gets scored

6 of the 7 `MetricContext`s are scored for real: `topology_reconstruction`, `role_inference`,
`temporal_analysis`, `causal_analysis`, `path_prediction` (PathForge), `counterfactual_prediction`.
`anomaly_detection` is deliberately left unscored — no synthetic anomaly-injection dataset exists
(a Phase 42 decision documented in `experiments/metrics/anomaly_evaluation.py`'s own docstring).

RQ6/RQ7's "actual outcome" baseline is independently recomputed from the ground-truth graph itself
(never reusing the inferred prediction's own graph, which would be tautological), since no live
Docker lab is available to produce a truly independent actual outcome.

## Known result: `causal_analysis` measures 0.0

Every cell of the Phase 68 run measured `0.0` accuracy for `causal_analysis`. This traces to
`experiments/synthetic_traffic.py` not producing genuine time-lagged cross-correlation structure for
Phase 52's temporal-precedence gate to detect — a limitation of the synthetic data generator, not a
defect in the causal-candidate logic (Phases 50-53), which is independently unit-verified against
hand-constructed temporal-precedence cases in `backend/tests/test_dependency_temporal_precedence.py`.

## Reading results back via the API

`GET /experiments` and `GET /metrics?context=<MetricContext>` read real records from whatever
`Settings.artifact_root` points at — set `NETSCOPE_ARTIFACT_ROOT` to the same `--root` you ran the
matrix against. `POST /experiments` (live-triggering a run via the API) is intentionally not wired —
see `docs/API.md`.

## Extending the matrix

Add a new topology level to `TOPOLOGY_LEVELS`, a new observation-completeness value to
`OBSERVATION_COMPLETENESS_LEVELS`, or a new ablation name to `ABLATIONS`
(`experiments/matrix_runner.py`) — each is a plain dict/list entry, no structural change needed. A new
`MetricContext` requires a new evaluation module under `experiments/metrics/` plus a mapping branch in
`matrix_runner.py::_to_metric_result`.
