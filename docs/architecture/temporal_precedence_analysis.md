# NETSCOPE-X — Temporal Precedence Analysis

Phase 52 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 52 — TEMPORAL PRECEDENCE
ANALYSIS"): "Study whether changes in one component consistently precede changes in another."

FR-1.27 (first half): *"The system shall analyze temporal precedence between component changes as
one input to dependency/causal candidate generation, without equating correlation with causation
(spec Phase 52–53)."* Only the signal itself is this phase's job — candidate generation is
explicitly Phase 53's (`algorithm_selection.md` §6's option (c) rejection note cites the Phase 53
wording specifically).

Code: new `backend/dependency/temporal_precedence.py` (`estimate_temporal_precedence`); extends
`backend/dependency/strength.py`'s `estimate_dependency_strength` (Phase 51, same function) in
place.

## The algorithm was already committed, not decided here

`docs/architecture/algorithm_selection.md` §6 selected *"time-lagged cross-correlation for temporal
precedence"* as part of the same weighted multi-signal scoring function that already produces
`DependencyEdge.strength`, explicitly stating the approach *"produc[es] the `DependencyEdge.strength`
and `temporal_precedence_score` fields ... from the same combined scoring function"* — i.e., this
phase's job includes folding its result back into `estimate_dependency_strength`, not leaving a
disconnected utility. Complexity target: *"O(T) per node pair for T time-bucketed observations ...
candidate pairs are pruned first by the already-inferred topology edges."* Granger causality and
PC-algorithm causal discovery were both explicitly considered and explicitly deferred/rejected in
that same section — not re-litigated here.

## What "changes" means here, and why

Two other candidate signals exist in this repo:

- **Phase 45/47's `GraphChangeEvent`** (structural diffs, chained into a timeline) — rejected as the
  primary signal: per-node structural events are sparse (essentially one `NODE_ADDED` event ever,
  since this system's topology reconstruction is cumulative with no expiry concept, as Phase 45/47's
  own docs already document). Cross-correlating two near-single-point series isn't meaningful.
- **Phase 46's `BehavioralEvolutionEvent`** — rejected as the primary, automatic signal: it's only
  available from a *caller-supplied* fingerprint list (no persisted multi-batch fingerprint history
  exists on disk yet, per Phase 46's own documented limitation), which would make
  `estimate_dependency_strength` stop being self-sufficient and automatic like Phase 50/51.

**Selected: per-node flow activity, time-bucketed by `Flow.first_seen`.** Fully automatic (read
straight from `flows.jsonl`, the same source every one of Phase 51's four existing signals already
derives from), and information-dense enough to support real cross-correlation. Crucially, each
node's **overall** activity (with *any* counterpart) is used, not just its activity with the one
specific counterpart the `DependencyEdge` is about — using only the direct pair's own flows would
make source's and target's series nearly identical (every flow between A and B touches both nodes
at the same first_seen), collapsing into a trivial zero-lag correlation and conflating this signal
with the already-separate directionality signal. A node's "component" here is its own overall
network presence, and a genuine "does A getting busy predict B getting busy shortly after" pattern
is what's tested.

## Algorithm

`estimate_temporal_precedence(flows, source_node, target_node, bucket_seconds, max_lag_buckets)`:

1. `flows_touching_node` (already-existing Phase 33/34 utility,
   `backend/flowmind/features/node_features.py`) builds each node's own touching-flow list from the
   caller-supplied `flows` — a pure function over already-loaded data (the caller,
   `estimate_dependency_strength`, reads `flows_path` once and reuses it across every pair in its
   loop, not once per pair).
2. Both nodes' touching flows are bucketed into fixed-width `bucket_seconds` windows by
   `first_seen`, producing two aligned integer count series spanning the combined activity window.
3. Pearson correlation (stdlib `statistics.correlation` — the same module this project already uses
   for robust statistics, `node_baseline.py`'s median/MAD) is computed between the source series and
   the target series shifted by lag `k`, for `k = 1..max_lag_buckets` (a bounded set of positive lag
   offsets, per §6's complexity note): `target[t]` paired with `source[t-k]` — testing whether
   target's activity at time `t` matches source's activity `k` buckets earlier, i.e. **target lags
   behind source by `k` = source precedes target**, exactly matching
   `DependencyEdge.temporal_precedence_score`'s own docstring ("strength of evidence that
   source-side changes precede target-side changes").
4. The zero-lag (simultaneous) correlation is also computed as a baseline. The final score is the
   best positive-lag correlation **only if it's both positive and strictly stronger than the
   zero-lag baseline** — a merely-simultaneous relationship (both active at the same time, no real
   lag) is deliberately not counted as "precedes," avoiding overclaiming a lagged relationship that
   isn't actually there. Undefined correlation (zero-variance series — no activity, or perfectly
   constant activity) is honestly treated as no evidence, never fabricated. Empty/insufficient data
   → `0.0`, never an error.

## Integration into `estimate_dependency_strength`

Extends the existing three-secondary-term noisy-OR formula with a fourth, identically-scaled term:

```
survival = (1 - p_frequency)
         * (1 - s * p_persistence)
         * (1 - s * directionality_score)
         * (1 - s * edge.confidence)              # traffic characteristics
         * (1 - s * temporal_precedence_score)     # NEW (Phase 52)

strength = 1 - survival
```

This is the moment `DependencyEdge.strength` genuinely reflects **all five** of FR-1.26's named
signals (frequency, persistence, directionality, temporal relationships, traffic characteristics)
for the first time — Phase 51 explicitly left this incomplete, citing this exact phase.
`temporal_precedence_score` is now actually set on every constructed `DependencyEdge`, not left to
fall through to its schema default. Two new provisional `Settings` fields —
`dependency_temporal_bucket_seconds` (default `10.0`, mirroring Phase 34's short-window precedent)
and `dependency_temporal_max_lag_buckets` (default `5`) — follow the same "provisional pending Phase
68 calibration" convention every other numeric constant in this project already carries. `GET
/dependencies` threads both through from `Settings`, the same way Phase 51's own three settings
already are.

## What's deliberately not built this phase

- **No candidate causal-relationship generation** — explicitly Phase 53's job (FR-1.27 spans "Phase
  52–53"; `algorithm_selection.md` §6 scopes "generate candidate causal relationships" there
  specifically).
- **No topology-event-based precedence signal** — considered and rejected per the sparsity argument
  above; a plausible future enhancement, not attempted (NFR-9 convention already used throughout).
- **No re-validation against ground truth** — same "provisional, pending Phase 68" stance every
  other heuristic constant in this project already carries; the known health-check-poller failure
  mode Phase 51 already documented (a coincidental, high-frequency, persistent, one-directional
  pattern) equally applies here — a genuinely lagged coincidental pattern could still score high.

## Worked example

Node A talks to a third party C at irregularly-spaced times `t = 30, 34, 39, 45, 52`s; node B talks
to a fourth party D at exactly those same times shifted by `+4s`. A and B also share one small
direct exchange (so a `DependencyEdge(A, B)` exists at all):

```
A -> B: strength=1.000 freq=100.000 persist=0.0 direction=0.000 temporal_precedence=0.892
A -> C: strength=0.429 freq=0.227   persist=22.0 direction=0.000 temporal_precedence=0.000
B -> D: strength=0.429 freq=0.227   persist=22.0 direction=0.000 temporal_precedence=0.000
```

The `A -> B` edge (whose own direct traffic is too small to carry a temporal signal by itself) picks
up a real, high `temporal_precedence_score` from A's and B's *side* conversations correctly lagging
by the true offset — while the `A -> C`/`B -> D` edges each correctly show `0.000`, since for those
pairs "source's overall activity" collapses onto the edge's own flows (the same zero-lag-collapse
case this design deliberately avoids conflating with directionality).

## Verification actually performed this phase

- `pytest backend/tests/test_dependency_temporal_precedence.py -v` — **6/6 passed**: a genuine
  positive lag (irregularly-spaced bursts, to avoid periodicity aliasing where a periodic pattern
  would also show spurious correlation at other lags sharing the period) is detected with a high
  score; a purely simultaneous (zero-lag) pattern scores `0.0`, correctly not counted as precedence;
  unrelated/sparse activity scores low; reversed source/target roles score meaningfully lower than
  the true direction; a zero-activity counterpart never crashes; empty input returns `0.0`.
- `pytest backend/tests/test_dependency_strength.py -v` — grew from 7/7 to 8/8: the existing
  hand-computed formula test now explicitly includes the fourth noisy-OR term (a documented no-op
  for that minimal fixture, since `temporal_precedence_score` is honestly `0.0` there too — no room
  for a positive-lag window); a new end-to-end test with a genuinely lagged multi-node scenario
  confirms a real, non-zero `temporal_precedence_score` and that `strength`'s hand-recomputed value
  matches the extended formula exactly.
- Full repo suite (`pytest backend/tests experiments/tests simulator/tests`, run from repo root) —
  **426/426 passed** (up from 419/419), no regressions — including `test_api.py`'s existing `GET
  /dependencies` tests, whose minimal fixture still honestly scores `temporal_precedence_score ==
  0.0` (correctly, for the same "no room for a positive lag" reason, not a stale assertion).
- `python -m scripts.validate_data_contracts` — 38/38 passed, no regression (no schema changes —
  `DependencyEdge` unchanged; its already-reserved field is simply populated for real now).
- `python -m scripts.check_ground_truth_boundary` — clean.
- A real, manual end-to-end run (no Docker needed): built the same multi-node lagged-activity
  capture, ran `estimate_dependency_strength`, and confirmed the printed output exactly matches this
  doc's worked example.

## Status

Temporal precedence analysis (spec Phase 52, FR-1.27 first half) is implemented and unit-verified.
`estimate_temporal_precedence` provides a real, bounded, time-lagged cross-correlation signal over
per-node flow activity, folded into `estimate_dependency_strength` so `DependencyEdge.strength` and
`temporal_precedence_score` are both genuinely complete for the first time — closing out FR-1.26's
five-signal requirement as a side effect. Candidate causal-relationship generation
(`CausalEvidenceReport`, explicit "don't equate correlation with causation" framing) remains
explicitly Phase 53's job.
