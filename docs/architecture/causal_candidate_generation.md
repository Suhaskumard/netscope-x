# NETSCOPE-X — Causal Candidate Generation

Phase 53 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 53 — CAUSAL CANDIDATE
GENERATION"): "Generate candidate causal relationships. Do not equate correlation with causation."

FR-1.27 (second half): *"...as one input to dependency/causal candidate generation, without
equating correlation with causation (spec Phase 52–53)."*

Code: new `backend/dependency/causal_candidates.py` (`CausalCandidate`,
`generate_causal_candidates`, `format_causal_candidate`).

## The design boundary was already committed at Phase 05

`docs/architecture/algorithm_selection.md` §6 evaluated and rejected constraint-based causal
discovery (option (c), e.g. the PC algorithm) over the full node-activity dataset, stating outright:
*"the spec's own Phase 53 wording ('generate candidate causal relationships,' 'do not equate
correlation with causation') is satisfied by a scored-candidate approach without requiring full
causal-graph discovery."* This phase is not a new causal-inference algorithm — it's a
**filter/promotion step** over Phase 51/52's already-real `DependencyEdge` list, producing an
explicitly-labeled *candidate* set, never a confirmed claim.

`GET /causal/{dependency_id}` (`backend/app/api/routes/causal.py`) stays untouched — its own
docstring already scopes it to *"spec Phase 56 (Causal Evidence Report)"*, a later phase. RQ5's own
experiment design (`docs/research/research_questions.md`) confirms the same split: *"Run causal
candidate generation (Phase 53) and dependency-strength estimation (Phase 51)... Every **accepted**
dependency claim must carry the causal evidence report format (Phase 56)."* Phase 53 produces
candidates; Phase 56 is what eventually wraps an *accepted* one in the full report format. This
phase does not touch `CausalEvidenceReport`, `GET /causal`, or anything resembling a confirmed-cause
claim.

## The qualifying rule is the literal implementation of "do not equate correlation with causation"

A `DependencyEdge` is promoted to a `CausalCandidate` only when **both**:

- `strength >= strength_threshold` (a new provisional `Settings.causal_candidate_strength_threshold`,
  default `0.5`), and
- `temporal_precedence_score > 0.0` (Phase 52's real signal).

`strength` alone (built from frequency, persistence, directionality, and traffic characteristics —
Phase 51's four signals, all fundamentally about *how much and how* two nodes communicate, i.e.
correlation/communication evidence) is **deliberately never sufficient by itself**, however high. A
high-strength edge with zero temporal-precedence evidence — simultaneous or time-uncorrelated
activity — is excluded, since temporal precedence is the one signal that specifically supports
directional, time-ordered evidence: the logical prerequisite for a causal claim (a cause must
precede its effect), not proof of one. This directly implements FR-1.27's own framing of temporal
precedence as "**one input** to... causal candidate generation" — necessary, not sufficient,
alongside the strength gate — and reuses Phase 52's already-real signal rather than inventing new
inference machinery.

## `CausalCandidate`: a plain dataclass, not a new schema

Following the precedent already set by Phase 32's `TopologyComparisonResult`, Phase 37's
`RoleCalibrationEvaluation`, Phase 42's `AnomalyDetectionEvaluation`, and Phase 46's
`BehavioralEvolutionEvent` (all downstream, filtering/evaluation-style concepts with no Phase 04
schema reserved for them): `dependency_id`, `source_node_id`, `target_node_id`, `strength`,
`temporal_precedence_score`, `rationale: List[str]`. `generate_causal_candidates(dependencies,
strength_threshold)` is a pure function over caller-supplied `DependencyEdge`s, mirroring Phase
41/42's "pure function over already-computed data" style — the caller runs Phase 51/52's
`estimate_dependency_strength` first and passes the result in.

`rationale` names the concrete, specific evidence (e.g. `"strength 0.850 meets threshold 0.500"`,
`"temporal_precedence_score 0.720 indicates <source> consistently precedes <target>"`) — never a
bare label, matching this project's evidence convention everywhere else. Results are
deterministically ordered by `strength` descending, tie-broken by `dependency_id`.

## The disclaimer

`CAUSAL_CANDIDATE_DISCLAIMER` (a new module-level constant, worded for *this* context — distinct
from, not reused from, Phase 48's `attribution.py::CAUSAL_DISCLAIMER`, which explains a structural
change event, a different kind of claim) is unconditionally appended by `format_causal_candidate`,
mirroring Phase 48's own "structural, not confidence-gated" disclaimer pattern exactly, extended to
this new artifact type: every rendered candidate states plainly that it is a candidate for further
investigation, not a confirmed causal relationship, and that a full causal evidence report (Phase
56) is required before treating it as more than a lead.

## No persistence, no API wiring

`generate_causal_candidates`/`format_causal_candidate` are pure, unpersisted computation, mirroring
Phase 41/42/45's own precedent.

## Worked example

The same lagged multi-node capture used in Phase 52's own worked example (A's side conversation with
C consistently precedes B's side conversation with D by 4 seconds; A and B also share one small
direct exchange):

```
3 dependency edges -> 1 causal candidate

Candidate: 10.0.0.1 -> 10.0.0.2
Dependency: cap-1:dependency:0
Strength: 1.000
Temporal precedence: 0.892
Rationale:
- strength 1.000 meets threshold 0.300
- temporal_precedence_score 0.892 indicates 10.0.0.1 consistently precedes 10.0.0.2
This is a candidate for further investigation only -- strength and temporal precedence are
correlational and temporal-ordering evidence, not proof of causation. A full causal evidence
report (spec Phase 56) is required before this can be treated as more than a lead.
```

The `A -> C` and `B -> D` edges (real strength, but zero temporal-precedence evidence for those
specific pairs) are correctly excluded — exactly the "don't equate correlation with causation" case
this phase exists to guard against.

## Verification actually performed this phase

- `pytest backend/tests/test_dependency_causal_candidates.py -v` — **10/10 passed**: a qualifying
  dependency (strength + temporal precedence both real) becomes a candidate; the key case — high
  strength but zero temporal precedence — does *not* qualify, however high the strength; low
  strength with real temporal precedence also does not qualify; multiple qualifying edges are
  deterministically ordered by strength descending, tie-broken by `dependency_id`; every candidate's
  `rationale` is non-empty and references its actual values; empty input returns `[]`; a custom
  threshold changes qualification; `format_causal_candidate` always includes the disclaimer and full
  content; a real end-to-end run through `estimate_dependency_strength` (not hand-built
  `DependencyEdge` fixtures) confirms the genuinely-leading pair becomes a real candidate while its
  side-conversation edges do not.
- Full repo suite (`pytest backend/tests experiments/tests simulator/tests`, run from repo root) —
  **436/436 passed** (up from 426/426), no regressions.
- `python -m scripts.validate_data_contracts` — 38/38 passed, no regression (no schema changes this
  phase).
- `python -m scripts.check_ground_truth_boundary` — clean.
- A real, manual end-to-end run (no Docker needed): built the same multi-node lagged-activity
  capture, ran `estimate_dependency_strength` then `generate_causal_candidates`, and confirmed the
  printed output exactly matches this doc's worked example — 3 dependency edges reduced to 1 genuine
  candidate.

## Status

Causal candidate generation (spec Phase 53, FR-1.27 second half) is implemented and unit-verified.
`generate_causal_candidates` structurally guards against overclaiming causation from mere
correlation/communication strength, requiring genuine temporal-precedence evidence as a second,
independent gate. No persistence, API wiring, or `CausalEvidenceReport` population exist yet — all
explicitly later phases' jobs (Phase 56 and beyond).
