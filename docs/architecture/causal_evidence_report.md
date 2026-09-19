# NETSCOPE-X — Causal Evidence Report

Phase 56 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 56 — CAUSAL EVIDENCE
REPORT"): "For every inferred dependency or propagation relationship provide: relationship,
evidence, confidence, counter-evidence, limitations."

FR-1.30: *"For every inferred dependency or propagation relationship, the system shall produce a
causal evidence report containing: relationship, evidence, confidence, counter-evidence, and
limitations (spec Phase 56)."*

Code: new `backend/dependency/causal_evidence.py` (`build_dependency_evidence_report`,
`build_propagation_evidence_report`) — the first real use of
`backend/app/models/dependency.py`'s `CausalEvidenceReport` (Phase 04).

## Two relationship kinds, per FR-1.30's own wording

FR-1.30 says "dependency **or** propagation" — both now real in this codebase: Phase 50-53's
`DependencyEdge`/`CausalCandidate`, and Phase 54's `PropagationImpact`. This phase builds one report
generator per kind, reusing every upstream signal already computed rather than re-deriving
anything.

## `build_dependency_evidence_report`

- **`relationship`** is worded differently depending on whether the dependency was promoted to a
  `CausalCandidate` (Phase 53) — *"X is a causal candidate for Y (not a confirmed cause)"* when it
  was, versus the weaker *"X and Y communicate (estimated dependency strength N); no causal
  direction is established"* when it wasn't. Never overclaims beyond what Phase 53 itself already
  established.
- **`evidence`**: the dependency's own real `frequency`/`persistence_seconds`/
  `directionality_score`/`temporal_precedence_score`, formatted concretely.
- **`confidence`**: `dependency.strength` directly — reused, not re-derived, this project's
  established convention.
- **`counter_evidence`**: genuine, per-edge signals only, never manufactured filler:
  - *"no positive temporal-precedence evidence supports a causal direction..."* when
    `temporal_precedence_score <= 0`.
  - *"traffic is largely bidirectional..."* when `directionality_score < 0.3`.
  - *"strength does not meet the causal-candidate threshold..."* when no `CausalCandidate` was
    supplied.
  
  Can be legitimately **empty** for a strong, fully-evidenced candidate — verified directly
  (`test_strong_candidate_can_have_empty_counter_evidence`), not padded with boilerplate just to
  look non-empty. `CausalEvidenceReport.counter_evidence` has no `min_length` constraint, unlike
  `evidence`/`limitations` — the schema itself already anticipated this asymmetry.
- **`limitations`**: **always** two real, already-documented structural caveats —
  `CONFOUNDER_LIMITATION` (the health-check-poller false-positive risk
  `algorithm_selection.md` §6 already named) and `THRESHOLD_LIMITATION` (Phase 51/52/53's own
  recurring "provisional, pending Phase 68 calibration" note). Both are properties of the scoring
  *approach*, true regardless of this specific edge's numbers — deliberately distinct in purpose
  from `counter_evidence`'s edge-specific signals, and always present because the schema requires
  at least one limitation to ever be stated.

## `build_propagation_evidence_report`

- Raises `ValueError` for a `PRIMARY` impact — a primary failure is the given input, not an
  *inferred* relationship; there is nothing to report evidence for.
- Looks up the specific `CausalCandidate` matching `(source=impact.caused_by_node_id,
  target=impact.affected_node_id)` from the caller-supplied `candidates` list (the same list
  `propagate_failure` was called with) — raises `ValueError` if none is found, the same fail-fast
  stance this project takes for internally inconsistent calls elsewhere (e.g. Phase 46/50's
  mismatched `node_id`/`window` checks).
- `relationship`: *"failure of X is estimated to propagate to Y (SECONDARY/TERTIARY impact)"*.
- `evidence`: `impact.evidence` directly — already real and concrete from Phase 54.
- `confidence`: the matched candidate's `strength`.
- `counter_evidence`: always `[]` — a promoted `CausalCandidate` by definition already cleared both
  of Phase 53's gates (sufficient strength *and* positive temporal precedence), so there is no
  genuine per-edge counter-signal left to surface at this stage — structural, not a gap.
- `limitations`: the same two structural caveats, plus a third, propagation-specific one
  (`PROPAGATION_LIMITATION`): multi-hop propagation compounds each hop's own uncertainty and has
  not itself been validated against a real controlled failure experiment (Phase 63/68's job).

## API wiring: `GET /causal/{dependency_id}`, a real scope difference from Phases 53-55

`backend/app/api/routes/causal.py`'s own docstring already said *"Backing implementation: spec
Phase 56"* — unlike the routes touched by the last several phases (each explicitly deferred to a
*later* phase in its own docstring), this one names Phase 56 as its backing implementation, the
same pattern Phase 51 followed for `GET /dependencies`.

Wired with one deliberate deviation from the bare `/causal/{dependency_id}` path: an **explicit
`capture_id: str = Query(...)` parameter**. Every sibling route (`GET /flows`, `GET /topology`,
`GET /dependencies`) takes `capture_id` as an explicit query parameter rather than parsing it out
of another id's internal string format; `dependency_id`'s `f"{capture_id}:dependency:{index}"`
shape was never meant to be a public parsing contract, and relying on it would be fragile.

Recomputes `estimate_dependency_strength` + `generate_causal_candidates` fresh on every call — the
same "recompute on every call" convention `GET /dependencies` already established. A
`dependency_id` not found — whether because the capture doesn't exist or the capture exists but
that specific id doesn't match — raises a new `DependencyNotFoundError` (`backend/dependency/
errors.py`) → `404`, mirroring `GET /flows`/`GET /topology`'s own single-resource-by-id 404
convention. This is a genuinely different convention from `GET /dependencies`/`GET /history`'s
"missing means empty, still 200" — that convention only applies to paginated *list* routes; a
route returning exactly one object correctly 404s when that object doesn't exist. `estimate_dependency_
strength` already returns `[]` for a missing capture, which naturally flows into "no matching
`dependency_id`" either way — one uniform error path, not two separate checks.

`build_propagation_evidence_report` stays **unwired** — there is no `propagation_impact_id`
concept anywhere in the fixed Phase 09 API surface (`PropagationImpact` doesn't even carry its own
id field), and `POST /simulation` remains explicitly scoped to Phase 59-61, mirroring exactly how
Phase 54's `propagate_failure` itself stayed unwired.

## Worked example

The same 3-hop lagged-activity chain from Phase 52-54's own worked examples (A precedes B precedes
C):

```
=== Dependency evidence report (A -> B) ===
relationship: A is a causal candidate for B (not a confirmed cause)
evidence: ['frequency 100.000 events/sec', 'persistence 0.0s', 'directionality_score 0.000',
           'temporal_precedence_score 0.892']
confidence: 1.000
counter_evidence: ['traffic is largely bidirectional (directionality_score=0.000), also
                    consistent with two independent peers rather than a clear dependency
                    direction']
limitations: 2 items

=== Propagation evidence report (A's failure -> B, secondary) ===
relationship: failure of A is estimated to propagate to B (secondary impact)
evidence: ['impact propagates from A via a causal candidate (strength=1.000,
            temporal_precedence=0.892)']
confidence: 1.000
counter_evidence: []
limitations: 3 items
```

A non-candidate dependency (via `GET /causal/{dependency_id}` on a minimal, non-lagged real
capture) shows the weaker wording and both applicable counter-evidence items:

```
relationship: <A> and <B> communicate (estimated dependency strength 0.773); no causal
              direction is established
counter_evidence: ['no positive temporal-precedence evidence supports a causal direction
                    between these nodes -- could be purely coincidental co-occurrence',
                   'strength does not meet the causal-candidate threshold (spec Phase 53)']
```

## Verification actually performed this phase

- `pytest backend/tests/test_dependency_causal_evidence.py -v` — **11/11 passed**: candidate-backed
  dependencies use the causal-candidate wording; non-candidates use the weaker wording with a
  threshold counter-evidence item; zero/positive temporal precedence correctly toggles that
  counter-evidence item; low/high directionality correctly toggles the bidirectional item; a
  strong candidate legitimately produces empty counter-evidence; a `PRIMARY` impact raises
  `ValueError`; a missing candidate raises `ValueError`; a real `SECONDARY` impact report uses the
  candidate's real strength and the impact's own real evidence; a real end-to-end run through the
  full `estimate_dependency_strength` → `generate_causal_candidates` → `propagate_failure`
  pipeline produces both report kinds from genuinely-computed objects.
- New API tests in `backend/tests/test_api.py`: unknown capture and unknown `dependency_id` within
  a real capture both 404 with `error="dependency_not_found"`; a real ingested capture's real
  dependency returns 200 with a genuine `CausalEvidenceReport`.
- Full repo suite (`pytest backend/tests experiments/tests simulator/tests`, run from repo root) —
  **467/467 passed** (up from 454/454), no regressions.
- `python -m scripts.validate_data_contracts` — 38/38 passed, no regression (`CausalEvidenceReport`
  unchanged — first real use only).
- `python -m scripts.check_ground_truth_boundary` — clean.
- A real, manual end-to-end run (no Docker needed): built the same 3-hop lagged-activity capture,
  ran the full pipeline, generated both report kinds, and confirmed the printed output exactly
  matches this doc's worked example; separately, exercised the real `GET /causal/{dependency_id}`
  route via `TestClient` against a real ingested capture, confirming a genuine 200 response with a
  real `CausalEvidenceReport` body.

## Status

The causal evidence report (spec Phase 56, FR-1.30) is implemented and unit-verified for both
relationship kinds the spec names. `GET /causal/{dependency_id}` is now real, the sixth of Phase
09's 12 endpoint groups to become real (after `/capture`, `/flows`, `/topology`, `/history`,
`/dependencies`). `build_propagation_evidence_report` remains unwired — no route exists for it in
the fixed API surface, and that machinery (Phase 59-61) is still ahead.
