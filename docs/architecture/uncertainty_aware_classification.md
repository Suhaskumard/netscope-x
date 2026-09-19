# NETSCOPE-X — Uncertainty-Aware Classification

Phase 37 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 37 — UNCERTAINTY-AWARE
CLASSIFICATION"): "Represent uncertainty. Example: Database: 72%, Cache: 21%, Unknown: 7%. Confidence
must be calibrated." FR-1.14 is explicitly joint (36–37): "The system shall infer a service role per
node ... with a calibrated confidence distribution across candidate roles, not a single hard label
(spec Phase 36–37; RQ2)." There is no separate Phase-37-only FR.

## What's already done, and what's genuinely new here

`RoleClassification` (`backend/app/models/behavior.py`, populated for real since Phase 36) already
*represents* uncertainty — `role_probabilities: Dict[ServiceRole, float]` is a real probability
distribution, never a hard label. The spec line's first half was satisfied by Phase 36's own output
shape. What remained, and what this phase actually delivers, is the second half: **"confidence must be
calibrated."** RQ2 defines calibration precisely: "does a node classified 'Database: 72%' actually turn
out to be a database roughly 72% of the time across many such classifications?" — answering that
requires scoring predicted confidence against ground truth across many real classifications.

## Two halves, split along the same line Phase 30/31/32 already established

**Half A — Temperature scaling** (`backend/flowmind/classification/role_classifier.py`,
inference-side): a real, fitted calibration *mechanism*. **Half B — Calibration-error measurement**
(`experiments/metrics/role_calibration.py`, evaluation-only): a real calibration *measurement*
capability, mirroring Phase 32's `compare_topology_to_ground_truth`/`TopologyComparisonResult`
precedent. Neither half proves the classifier is calibrated against real, ground-truth-labeled lab
data — that validation is out of scope this session (see "No Docker" below) — but both are real,
tested, principled implementations, not placeholders.

### Half A: temperature scaling

`role_classifier.py`'s internals were refactored (behavior-preserving — Phase 36's 7 original tests
re-verified unchanged) to expose `_log_posteriors(model, fingerprint)` (the raw Bayes-rule
log-posterior per role, previously computed and immediately softmaxed inline) and
`_softmax(log_posteriors, temperature=1.0)`. `classify_node_role` gained an optional
`temperature: float = 1.0` parameter — the default reproduces Phase 36's exact original behavior.

`fit_temperature(model, labeled, bounds=(0.05, 20.0), grid_size=200) -> float` fits a single scalar
temperature `T` on held-out labeled data by minimizing the negative log-likelihood of the true role
under `softmax(log_posteriors / T)`. `T > 1` flattens an overconfident distribution toward uniform;
`T < 1` sharpens an underconfident one; `T = 1` leaves it unchanged. This is a real, standard technique
(temperature scaling), not an invented rescaling — the same "no principled basis to weight/adjust
things arbitrarily" reasoning already established and cited verbatim for Phase 31's noisy-OR
edge-confidence signals ("there is no principled basis today to claim... asserting different...
weights would itself be exactly the 'arbitrary' judgment... forbids") applies here too: a *fitted*
single parameter is defensible; a hand-picked one would not be.

**No `scipy.optimize` dependency added.** `_grid_search_minimize` is a small, self-contained two-pass
log-spaced grid search (coarse pass over the full bounds, refined pass narrowed around the coarse
optimum) — deterministic, easily testable, and this is a one-dimensional, well-behaved search that
doesn't justify the added dependency weight (NFR-9).

### Half B: calibration-error measurement

`evaluate_role_calibration(classifications, true_roles, num_bins=10) -> RoleCalibrationEvaluation`
computes real accuracy, the standard multiclass **Brier score** (mean squared error between each
prediction's full probability vector and the true role's one-hot vector), and the standard **expected
calibration error** (bin predictions by `best_role` confidence into equal-width bins, take the
sample-weighted average absolute gap between each bin's mean confidence and its actual accuracy) —
no invented variant of either formula.

Returns a plain frozen `RoleCalibrationEvaluation` dataclass, **not** a `MetricResult`
(`backend/app/models/metric.py`). `MetricResult.experiment_id` is required, and no experiment registry
exists anywhere in this repository yet (`experiments/runners/` doesn't exist) — this is the identical
tension Phase 32 already resolved the same way for `TopologyComparisonResult`. `MetricResult.
calibration_error`'s own docstring already scopes that field to "the Phase 68 evaluation matrix," not
this phase — confirming this deferral matches the schema's own stated intent, not just Phase 32's
precedent.

**Ground-truth-boundary compliance**: `evaluate_role_calibration` lives in `experiments/metrics/`,
takes real labels as a plain parameter (never reads `simulator.ground_truth` itself), and is never
imported by anything under `backend/nettrace/`/`backend/app/` — the same import-graph argument already
traced explicitly for `compare_topology_to_ground_truth` in `docs/architecture/
topology_reconstruction.md`.

## No Docker, no real calibration validation this session — explicit, prominent limitation

Fitting a real temperature and measuring real calibration error both require labeled data from real
node behavior — this session has no Docker, so no real lab traffic can be captured and labeled, the
same constraint Phase 36 already documented. **Both halves are verified this session only against
synthetic labeled fixtures**, the same convention every other phase's tests already use. No real,
Docker-lab-validated temperature is fit or shipped; `GET /behaviors/{node_id}` stays a 501 stub
(unchanged from Phase 36 — nothing in this phase removes that blocker, since `RoleClassification`'s
real content still comes from a classifier with no real lab-trained model).

## Failure cases

`fit_temperature`: raises `ValueError` on empty labeled input (mirrors `fit_role_model` — a
temperature cannot be fit from nothing). `evaluate_role_calibration`: raises `ValueError` on empty
input or mismatched `classifications`/`true_roles` lengths (an evaluation genuinely cannot be computed
from nothing or from misaligned data).

## Known limitations

- No temperature fit against real Docker-lab data; no calibration-error measurement against real
  ground truth — both explicit, carried-forward limitations from Phase 36.
- `evaluate_role_calibration`'s ECE uses fixed equal-width confidence bins (the standard formula) —
  adaptive/quantile binning is a known alternative not implemented here, not assessed as necessary
  without real data to show fixed bins are insufficient (NFR-9).
- `GET /behaviors/{node_id}` remains unwired.

## Verification actually performed this phase

- `pytest backend/tests/test_flowmind_role_classifier.py -v` — **12/12 passed** (7 original Phase 36
  tests re-verified unchanged after the refactor, plus 5 new): `fit_temperature` raises on empty input;
  fitting never does worse than the unscaled posterior (NLL comparison); temperature scaling's core
  mathematical property (higher temperature flattens, lower sharpens) verified directly against
  `_softmax` with hand-picked, moderately-separated log-posteriors (real classifier output on cleanly
  separated synthetic classes saturates to exactly 1.0/0.0 at float precision, leaving no headroom to
  demonstrate further sharpening — this test isolates the scaling math itself instead); a
  non-default-temperature `RoleClassification` still validates against the real schema; log-posteriors
  are finite (no NaN) and cover every candidate role.
- `pytest experiments/tests/test_role_calibration.py -v` — **5/5 passed**: confident-and-correct
  predictions score high accuracy and low error; confident-but-wrong predictions score strictly worse
  on all three metrics than an equally-confident-but-correct baseline; empty input and mismatched
  lengths both raise `ValueError`; a hand-computed 4-sample set's accuracy (0.75) and Brier score match
  by-hand arithmetic exactly.
- Full repo suite (`pytest`, run from repo root) — **289/289 passed** (up from 279/279), no
  regressions.
- `python -m scripts.validate_data_contracts` — 38/38 passed, no regression (`RoleClassification`
  schema unchanged; this phase transforms its output, never modifies the schema).
- `python -m scripts.check_ground_truth_boundary` — clean.

## Status

Uncertainty-aware classification's mechanisms (spec Phase 37, FR-1.14) are implemented and
unit-verified: real, fitted temperature scaling (not an invented rescaling) and a real,
standard-formula calibration-error measurement capability, both built directly on Phase 36's real Bayes
posterior. Neither has been validated against real Docker-lab ground truth this session — that
validation, and any resulting evidence about whether Phase 36-37's classifier is genuinely calibrated,
remains explicitly out of scope until real lab access exists.
