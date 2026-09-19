# NETSCOPE-X — FLOWMIND Evaluation

Phase 42 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 42 — FLOWMIND EVALUATION"):
"Measure: precision, recall, F1, false-positive rate, false-negative rate, detection latency."

FR-1.19: *"The system shall measure and report FLOWMIND's own precision, recall, F1,
false-positive rate, false-negative rate, and detection latency against labeled experiments (spec
Phase 42)."* RQ3 (`docs/research/research_questions.md`) ties this directly to Phase 40's anomaly
detector: *"Dependent: precision, recall, F1, false-positive rate, false-negative rate, detection
latency (Phase 42)... computed against `dataset_anomaly` and `dataset_noisy` (Phase 19-generated,
with injected known anomalies whose onset time and type are recorded as ground truth)."*

Code: new `experiments/metrics/anomaly_evaluation.py` (`evaluate_anomaly_detection`,
`LabeledAnomalyEvent`, `AnomalyDetectionEvaluation`).

## Scope: scoring, not dataset generation

`dataset_anomaly`/`dataset_noisy` — RQ3's own named evaluation data source, a Phase-19-replay-based
dataset with injected, timestamped, known anomalies — do not exist anywhere in this repo yet.
Building an anomaly-injection dataset generator is a separate, much larger capability, not implied
by FR-1.19's literal text ("measure and report ... against labeled experiments" — it describes the
measurement, not how the labels are produced). Every prior evaluation phase in this project (Phase
32's `compare_topology_to_ground_truth`, Phase 37's `evaluate_role_calibration`) is a pure scoring
function over caller-supplied real+labeled data; Phase 42 follows the identical, already-established
pattern. `LabeledAnomalyEvent` is deliberately the minimal shape a caller who already knows the
ground truth (however obtained — hand-constructed today, `dataset_anomaly`-sourced in a future
phase) needs to supply: `node_id`, `dimension`, `onset_at`.

## Why a plain dataclass, not `MetricResult`

`backend/app/models/metric.py`'s `MetricResult` already has `precision`/`recall`/`f1`/
`false_positive_rate`/`false_negative_rate`/`detection_latency_seconds` fields — clearly designed
with exactly this evaluation in mind. But `MetricResult.experiment_id` is required, and no
experiment registry exists anywhere in this repository (`Experiment`,
`backend/app/models/experiment.py`, is never constructed for real anywhere — confirmed by search).
Wrapping this evaluation's output in a `MetricResult` would mean fabricating an experiment identity
with nothing real behind it — exactly what spec §21 ("No Fake Metrics") forbids. This is the same
gap Phase 32 and Phase 37 each hit and resolved identically: return a plain, frozen dataclass
instead. `GET /metrics` (`backend/app/api/routes/metrics.py`) is explicitly scoped to Phase 68 in
its own docstring already ("Backing implementation: spec Phase 68") — not touched by this phase.

## Matching algorithm

Greedy, per `(node_id, dimension)`: each `LabeledAnomalyEvent` claims at most one detected
`Anomaly` (the earliest with `detected_at >= onset_at`), and a claimed detection cannot be reused
for another label.

- **True positive**: a labeled event with a match.
- **False negative**: a labeled event with no match.
- **False positive**: any detected anomaly not claimed as a match — including one that shares
  `node_id`/`dimension` with a label but fired *before* `onset_at` (it cannot be credited to an
  anomaly that hadn't started yet, and is itself an unexplained alarm).

This scores at most one labeled anomaly episode per `(node_id, dimension)` per call — a real,
documented simplification (see "Known limitations").

## Metric formulas

- `precision = TP/(TP+FP)`, or `0.0` if `TP+FP == 0` (nothing was ever detected — the standard
  scikit-learn "zero_division" convention, applied explicitly rather than silently reporting a
  misleadingly perfect `1.0`).
- `recall = TP/(TP+FN)` — always defined, since `labeled_events` is validated non-empty
  (`TP+FN == len(labeled_events) >= 1`).
- `f1 = 2*precision*recall/(precision+recall)`, or `0.0` if both are `0`.
- `false_negative_rate = FN/(FN+TP)` (algebraically `1 - recall`) — always defined.
- `false_positive_rate` genuinely needs a countable negative-instance universe (`TN`: checks that
  correctly stayed silent), which `detected`/`labeled_events` alone cannot supply — there is no
  fixed universe of "possible negatives" to enumerate from a plain detection list. It stays
  honestly `None` unless the caller supplies `total_checks` (the real number of node×dimension
  detection attempts run during the evaluated period — a number the caller genuinely knows, since
  they ran the detector that many times). When supplied: `TN = total_checks - TP - FP - FN`
  (`ValueError` if negative — an inconsistent `total_checks` smaller than the events that actually
  occurred); `false_positive_rate = FP/(FP+TN)`, or `0.0` if that denominator is `0`.
- `mean_detection_latency_seconds` = mean of `(matched.detected_at - event.onset_at)
  .total_seconds()` across every true positive. `None` if there are zero true positives — never
  fabricated as `0.0`.

## Worked example

A node `API-2` deviates on `distinct_destinations` (median 4 → 9) starting at `t=0`; the detector
picks it up at `t=6s` (its own recompute cadence). One labeled event, one detection, run with
`total_checks=50` (50 total node×dimension checks performed during the evaluated period):

```
AnomalyDetectionEvaluation(
    label_count=1, detected_count=1,
    true_positive_count=1, false_positive_count=0, false_negative_count=0,
    precision=1.0, recall=1.0, f1=1.0, false_negative_rate=0.0,
    false_positive_rate=0.0,               # TN = 50 - 1 = 49; FP=0 -> 0/(0+49)
    mean_detection_latency_seconds=6.0,
)
```

## Failure cases

`evaluate_anomaly_detection([], [])` (or any empty `labeled_events`): `ValueError` — an evaluation
cannot be computed against nothing. A supplied `total_checks` smaller than `TP+FP+FN`: `ValueError`
— internally inconsistent, since those are real events that occurred within however many checks
were run.

## Known limitations

- **No injected-anomaly dataset generator** — `dataset_anomaly`/`dataset_noisy` don't exist; this
  phase only scores against whatever labels a caller supplies, whether hand-constructed (as in this
  phase's own tests) or eventually `dataset_anomaly`-sourced.
- **At most one labeled episode per `(node_id, dimension)` per call** — the matching algorithm
  doesn't handle multiple distinct anomaly episodes for the same node+dimension within one
  evaluation run (e.g. a node that goes anomalous, recovers, then goes anomalous again). Handling
  that would need real temporal windowing (Phase 43's temporal graph model, or Phase 68's fuller
  evaluation matrix) — a plausible future enhancement, not attempted here (NFR-9).
- **`false_positive_rate` requires an honestly-supplied `total_checks`** — there is no way to
  derive a real negative-instance count from `detected`/`labeled_events` alone; the field stays
  `None` rather than guessing one.
- No persistence, no API wiring — `GET /metrics` remains scoped to Phase 68's own registry-backed
  implementation.

## Verification actually performed this phase

- `pytest experiments/tests/test_anomaly_evaluation.py -v` — **10/10 passed**: perfect detection
  scores precision/recall/f1 all `1.0`; a missed label drops recall without touching precision; an
  extra/spurious detection drops precision without touching recall; a detection fired before its
  label's `onset_at` counts as neither a match (the label becomes a false negative) nor a free pass
  (the early detection itself becomes a false positive); empty `labeled_events` raises
  `ValueError`; a hand-computed mean detection latency across two true positives matches exactly;
  zero true positives leaves `mean_detection_latency_seconds` honestly `None`;
  `false_positive_rate` is `None` without `total_checks` and a real value with it; an inconsistent
  `total_checks` raises `ValueError`; a real end-to-end run through
  `build_node_baseline`/`detect_node_anomalies` (not hand-built `Anomaly` fixtures) scores a
  genuinely detector-produced anomaly as a true positive with a real, non-fabricated latency.
- Full repo suite (`pytest backend/tests experiments/tests simulator/tests`, run from repo root) —
  **335/335 passed** (up from 325/325), no regressions.
- `python -m scripts.validate_data_contracts` — 38/38 passed, no regression (no schema changes this
  phase).
- `python -m scripts.check_ground_truth_boundary` — clean.
- A real, manual end-to-end run (no Docker needed): built a synthetic 10-observation fingerprint
  history for node `API-2` (destinations jittering 3-5, median 4), ran `detect_node_anomalies`
  against a new fingerprint (9 destinations, `computed_at` 6 seconds after the labeled onset),
  labeled the true onset via `LabeledAnomalyEvent`, and confirmed `evaluate_anomaly_detection`
  reported real `precision=1.0`/`recall=1.0`/`f1=1.0`/`mean_detection_latency_seconds=6.0`, plus a
  real `false_positive_rate=0.0` when `total_checks=50` was supplied.

## Status

FLOWMIND evaluation (spec Phase 42, FR-1.19) is implemented and unit-verified as a pure,
evaluation-only scoring function over real `Anomaly` output and caller-supplied labeled ground
truth. Precision/recall/F1/false-negative-rate/detection-latency are always real and computable;
false-positive-rate is real when `total_checks` is supplied, honestly `None` otherwise — never
fabricated. No injected-anomaly dataset generator exists yet (RQ3's `dataset_anomaly`/
`dataset_noisy`), and multi-episode matching per `(node_id, dimension)` is an explicit, documented
limitation for a later phase.
