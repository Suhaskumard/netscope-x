# NETSCOPE-X — Digital Twin Validation

Phase 63 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 63 — DIGITAL TWIN
VALIDATION"): compare digital-twin predictions against actual controlled experiment outcomes.

FR-1.38: *"The system shall compare digital-twin/counterfactual predictions against actual
controlled experiment outcomes and shall not claim correctness without this measurement (spec
Phase 63, 66; RQ6/RQ7)."*

This FR spans two phases. **This phase covers RQ6 only** — failure-propagation prediction vs.
actual, using Phase 55/57/61/62 machinery already built. RQ7 (counterfactual scenarios) is Phase
66's job, built on top of the counterfactual scenario engine (Phase 64-66), which does not exist
yet; `CounterfactualAction`/`CounterfactualScenario` (`backend/app/models/simulation.py`) are
untouched here.

Code: new `experiments/metrics/failure_propagation_validation.py`
(`ActualFailureOutcome`, `FailurePropagationValidationResult`,
`evaluate_failure_propagation_prediction`).

## Honesty and limitations — read this first

RQ6's own experiment design (`docs/research/research_questions.md`) has four steps: (1) record
the digital twin's predicted propagation before touching the real network, (2) execute the real
failure in the isolated lab, (3) capture the actual impact, (4) score prediction against reality.

Steps (2) and (3) cannot be performed this session. Two independent facts combine to make that
true:

- `simulator/ground_truth/` (Phase 16-17) has never captured a post-failure "actual outcome" —
  every function it exposes (`build_topology_graph`, `build_roles`, `build_expected_paths`)
  describes the network's static, steady-state topology. There is no existing primitive anywhere
  in this codebase for "what actually happened after a failure was injected."
- This session has no Docker (`docker --version` fails), so the real lab cannot be exercised
  regardless.

This mirrors an extremely well-established project convention, repeated 30+ times throughout
`docs/PROJECT_STATE.md` — for example Phase 36/37's role classifier and temperature scaling were
"verified only against synthetic labeled fixtures this session," since "no Docker this session
means no real lab traffic exists to label."

**This phase therefore honestly scopes itself to step (4) only**: a real, deterministic scoring
function, `evaluate_failure_propagation_prediction`, that accepts an "actual outcome" as an
ordinary parameter — `ActualFailureOutcome` — so it works equally whether that parameter comes
from a hand-built test fixture (this session) or a real second capture (a future phase, once
Docker and a real capture-of-actual-outcome mechanism both exist). Building that capture
mechanism is explicitly **not** attempted here: doing so now, with no way to verify it against a
real lab, would itself risk producing exactly the kind of not-really-validated artifact spec §21
("No Fake Metrics") warns against. This does not make the module fake work — the scoring logic
itself is real, deterministic, and unit-tested against synthetic fixtures this session, precisely
as Phase 36/37's classifier/calibration code was real despite having no real lab data to fit or
score it against.

## `ActualFailureOutcome` — capture-mechanism-agnostic by design

```python
@dataclass(frozen=True)
class ActualFailureOutcome:
    actually_affected_node_ids: Set[str]
    actual_largest_component_node_ids: List[str]
    actual_reachable_pairs: Dict[Tuple[str, str], bool]
    actual_affected_service_count: Optional[int] = None
    actual_alternative_path_available: Optional[bool] = None
```

Represents what real monitoring *would* observe, deliberately decoupled from *how* it's captured.
`actual_reachable_pairs` reuses the exact same bounded `(source_node_id, target_node_id)` pair set
Phase 61's `route_changes` already established (the failure site's former direct neighbors, or an
edge failure's own two endpoints) rather than inventing a new pair-selection policy this phase
would have to separately justify. `actual_affected_service_count`/`actual_alternative_path_
available` are `Optional`, defaulting to `None` — `None` means "not supplied," honestly distinct
from a real `0`/`False`, so the module never has to guess whether an omitted field means "zero" or
"unknown."

## `evaluate_failure_propagation_prediction(predicted, predicted_resilience, actual)`

Follows the exact precedent of `experiments/metrics/topology_comparison.py` (Phase 32),
`role_calibration.py` (Phase 37), `anomaly_evaluation.py` (Phase 42): pure function, no I/O, lives
under `experiments/metrics/` (already allowlisted by `scripts/check_ground_truth_boundary.py`),
returns a plain `@dataclass(frozen=True)` — never `MetricResult` (`backend/app/models/metric.py`):
its `experiment_id` field is required/non-optional and no experiment registry exists anywhere in
this repository yet (`experiments/runners/` doesn't exist); inventing a plausible-looking
`experiment_id` with no real registered experiment behind it would be exactly the kind of
metric-that-looks-legitimate-but-isn't spec §21 forbids. `MetricContext.PATHFORGE` already exists
as a reserved enum value for this eventual wrapping, left unpopulated here, deferred to Phase 68.

Computes four metrics, matching RQ6's own named dependent variables exactly:

### 1. Affected-node-prediction accuracy

Precision/recall/f1 (the same `_precision_recall_f1` helper convention `topology_comparison.py`
established: empty-vs-empty is perfect agreement 1.0/1.0/1.0, empty-vs-nonempty is 0.0 on
whichever side is empty) between the *union* of `predicted.service_impacts` node ids and
`predicted.newly_unreachable_node_ids`, and `actual.actually_affected_node_ids`. Union, not either
alone: `newly_unreachable_node_ids` can include nodes with no itemized `ServiceImpact` entry
(Phase 61's routing impact is connectivity-based, separate from service itemization) — union is
the more faithful "everything the twin predicted as affected."

### 2. Path-prediction accuracy

A fraction-correct match rate, not precision/recall — reachability is a binary per-pair fact, not
a set-membership problem, so there's no meaningful "false positive reachable pair" concept the way
there is for a node set. For each `predicted.route_changes` pair, predicted reachability
(`current_path is not None`) is compared against `actual.actual_reachable_pairs[(source,
target)]`; a predicted pair absent from `actual`'s dict is excluded from both the numerator and
`path_prediction_pair_count`, never silently scored either way — an honest "not evaluated," not a
free correct or incorrect. `1.0` for zero evaluated pairs (the same empty-vs-empty convention).

### 3. Connectivity-prediction accuracy

`connectivity_prediction_accuracy = 1 - connectivity_prediction_error`, where the error averages
the absolute differences between `predicted_resilience.connectivity_ratio`/`reachable_node_ratio`
and their actual-side equivalents. `actual_connectivity_ratio =
len(actual.actual_largest_component_node_ids) / len(predicted.connectivity_before
.largest_component_node_ids)` — the exact same self-relative formula Phase 62 uses for the
predicted side (`1.0` if the pre-failure denominator is 0). `actual_reachable_node_ratio` is a
documented conservative approximation: `len(actual.actual_largest_component_node_ids) / (total
original node count)`. This is a simplification, not an oversight — `ActualFailureOutcome`
deliberately carries only the largest actual component, not the full post-failure partition, to
keep the actual-outcome shape minimal; the approximation undercounts any healthy non-largest
islands that a real capture might reveal.

### 4. Resilience-indicator accuracy

Explicitly scoped to avoid double-counting `connectivity_ratio`/`reachable_node_ratio`, which
metric 3 already fully covers. Only evaluates what's honestly derivable from
`ActualFailureOutcome`:

- `affected_service_count` vs. `actual.actual_affected_service_count` (if supplied): `1 -
  abs(predicted - actual) / max(predicted, actual, 1)` — a normalized relative error kept in
  `[0,1]`, with `max(..., 1)` avoiding a divide-by-zero when both sides are `0` (which then scores
  a clean `1.0`, matching the zero-fabrication and empty-vs-empty conventions used elsewhere).
- `alternative_path_available` vs. `actual.actual_alternative_path_available` (if supplied): a
  binary match, `1.0` if equal else `0.0`.
- `path_degradation_score` and `bottleneck_node_ids` are explicitly **not evaluable** from this
  minimal `ActualFailureOutcome` shape — there is no honest source of "actual path cost delta" or
  "actual articulation-point diff" without a full post-failure topology capture. They are never
  scored and always listed in `resilience_indicator_components_skipped`.

The result is the mean of whichever of the two evaluable components were actually supplied, or
`None` if neither was — never a fabricated score.
`resilience_indicator_components_evaluated`/`_skipped` make this honesty visible in the returned
result itself, not just in the docstring, so a caller or report can't silently misread a partial
score as complete.

## What this phase deliberately does NOT do

- **No real lab execution or capture.** See "Honesty and limitations" above.
- **No counterfactual validation.** RQ7/Phase 66 (comparing counterfactual predictions, built on
  Phase 64-66's engine) is untouched.
- **No `MetricResult` wrapping.** Deferred to Phase 68, per the established
  `experiments/metrics/` precedent.
- **No new Pydantic schema.** Both new types are plain frozen dataclasses, matching Phase
  32/37/42's own precedent for evaluation-only, no-experiment-registry-yet results.

## Worked example

Diamond topology (A-B-D cheap / A-C-D expensive), `NODE_FAILURE` on B with a `CausalCandidate`
B→D — the same scenario used throughout Phase 61/62's own worked examples. Predicted side:
`service_impacts` = {B, D}, `route_changes` = [(A,B): unreachable, (D,B): unreachable],
`connectivity_ratio` = 0.75, `reachable_node_ratio` = 0.75, `affected_service_count` = 2,
`alternative_path_available` = False.

**Actual outcome matching the prediction exactly:**

```
actual = ActualFailureOutcome(
    actually_affected_node_ids={"B", "D"},
    actual_largest_component_node_ids=["A", "C", "D"],
    actual_reachable_pairs={("A", "B"): False, ("D", "B"): False},
    actual_affected_service_count=2,
    actual_alternative_path_available=False,
)
# affected_node_f1: 1.0
# path_prediction_match_rate: 1.0 (2/2)
# connectivity_prediction_accuracy: 1.0
# resilience_indicator_accuracy: 1.0
```

**Actual outcome that fragmented much worse than predicted** (only node A survived as its own
component, instead of the predicted {A, C, D}):

```
actual = ActualFailureOutcome(..., actual_largest_component_node_ids=["A"], ...)
# connectivity_prediction_error: 0.5   (both ratios off by 0.5: 0.25 actual vs. 0.75 predicted)
# connectivity_prediction_accuracy: 0.5
# (other three metrics unaffected, still 1.0 -- proving the metrics are independent)
```

## Verification actually performed this phase

- `pytest experiments/tests/test_failure_propagation_validation.py -v` — **10/10 passed**: a
  perfect-match actual outcome scores at/near 1.0 on all four metrics; a deliberate mismatch on
  each of the four metrics individually drops only that metric while the other three stay at
  their perfect-match values, proving independence; an empty-vs-empty case (hand-zeroed via
  `dataclasses.replace`, since the real pipeline structurally cannot produce a truly empty
  `service_impacts`/`route_changes` set for any failure type) reports perfect node/path scores and
  an honest `None` resilience-indicator accuracy with all four components listed as skipped; a
  case with neither optional resilience field supplied confirms `resilience_indicator_accuracy is
  None` rather than a fabricated score; a partial case with only one optional field supplied
  confirms the mean reflects only that component; the function never mutates any of its three
  arguments; a predicted route-change pair absent from `actual.actual_reachable_pairs` is excluded
  from the match-rate denominator rather than silently scored.
- Full repo suite (`pytest backend/tests experiments/tests simulator/tests`, run from repo root) —
  **542/542 passed** (up from 532/532), no regressions.
- `python -m scripts.validate_data_contracts` — 38/38 passed, no regression (no schema changes
  this phase — both new types are plain dataclasses, not Pydantic models).
- `python -m scripts.check_ground_truth_boundary` — clean.

## Status

Digital twin validation (spec Phase 63, FR-1.38's RQ6 half) is implemented and unit-verified:
`evaluate_failure_propagation_prediction` scores a Phase 61/62 prediction against a
caller-supplied `ActualFailureOutcome` on all four of RQ6's named metrics, with each metric's
formula resolved as an explicit, documented decision — including how resilience-indicator
accuracy avoids double-counting the connectivity-prediction metric, and which resilience fields
are honestly un-evaluable from this minimal actual-outcome shape. RQ6's steps (2)/(3) — actually
executing a real failure and capturing its actual impact — remain unperformed this session, for
the structural and environmental reasons stated up front, and are not fabricated. RQ7/Phase 66
(counterfactual validation) remains ahead, along with the rest of the counterfactual scenario
engine (Phase 64-66).
