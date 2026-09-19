# NETSCOPE-X — Behavioral Baseline

Phase 38 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 38 — BEHAVIORAL BASELINE"):
"Build a normal-behavior model from historical observations." FR-1.15
(`docs/requirements/system_requirements.md`): "The system shall maintain a behavioral baseline of
normal behavior derived from historical observations (spec Phase 38)."

Code: `backend/flowmind/baseline/node_baseline.py` (`build_node_baseline`/`NodeBehavioralBaseline`) —
the first code to maintain a *historical* model of a node's behavior, as opposed to Phase 33-37's
single-snapshot feature/fingerprint/classification computations.

## Explicit non-scope: Phase 38 vs. 39

`docs/architecture/algorithm_selection.md` §3 (Anomaly detection, Phase 05, already selected — not
re-derived here) names two distinct mechanisms: a robust median/MAD baseline (this phase), and a
separate "EWMA-updated baseline with a slower update rate than the anomaly-detection window" used
specifically to distinguish a **transient anomaly** from **concept drift** (spec Phase 39, FR-1.16:
"distinguish temporary anomalies from persistent behavioral evolution"). That drift-vs-transient
*decision logic* is Phase 39's job — this phase only maintains the baseline itself, matching FR-1.15's
literal scope ("maintain a behavioral baseline"), not FR-1.16's ("distinguish... concept drift").

## Algorithm

`docs/architecture/algorithm_selection.md` §3's selected approach, quoted: "(a) Per-dimension
statistical baseline (robust z-score / MAD-based deviation against a rolling historical baseline per
node/feature) + explicit set-difference novelty checks (new destination/port not in historical set)
... using a robust (median/MAD-based, outlier-resistant) rather than mean/std baseline to avoid the
baseline itself being skewed by prior anomalies."

`build_node_baseline(fingerprint_history: List[BehavioralFingerprint], min_observations=5) ->
NodeBehavioralBaseline` maps every one of `BehavioralFingerprint`'s 6 feature fields onto one of
three baseline representations:

| Feature | Representation | Why |
|---|---|---|
| `distinct_destinations` | robust median/MAD | continuous, §3's named mechanism |
| `mean_flow_duration_seconds` | robust median/MAD | continuous |
| `outbound_byte_ratio` | robust median/MAD | continuous |
| `distinct_ports` → `port_count = len(distinct_ports)` | robust median/MAD | continuous *magnitude* proxy — reuses the exact "port count as the honest entropy proxy" framing Phase 36 already established, for consistency |
| `distinct_ports` | historical union (`historical_ports`) | §3's "new destination/port not in historical set" novelty mechanism needs the actual historical *values*, not just their count |
| `distinct_protocols` | historical union (`historical_protocols`) | same reasoning |
| `is_persistent_talker` | historical frequency (`persistent_talker_frequency`) | boolean — neither median/MAD nor set-difference cleanly applies |

Note `distinct_ports` feeds **both** a continuous baseline (`port_count`, "is the *number* of ports
unusual?") and a historical set (`historical_ports`, "is *this specific* port new?") — these answer
different questions and both are named by §3 (statistical deviation vs. explicit novelty check), so
neither is redundant.

### Median/MAD computation

`median = statistics.median(values)`; `mad = statistics.median(|v - median| for v in values)` — the
standard median absolute deviation formula, no invented variant. **Reported honestly, un-floored**:
`mad` can legitimately be `0.0` when historical values are identical or there are too few of them —
stated as a documented fact of the statistic, not a bug. Whether/how a future consumer floors it
against division-by-zero (e.g. computing a z-score in Phase 39/40) is that consumer's own choice to
make and document; baking a floor in here would be presuming an application this phase doesn't itself
have.

### Cold-start

§3 flags a "minimum baseline observation period before deviations are meaningful (cold-start
limitation)" qualitatively, without a concrete number. `min_observations` (default `5`) is a
provisional, evidence-light choice — MAD is degenerate (`0.0`) with fewer than 2 points and remains
wildly unstable through the first handful, since a single outlier pair dominates the statistic at
small sample sizes. `NodeBehavioralBaseline.observation_count`/`is_sufficient` expose this explicitly
so a consumer never silently treats a cold-start baseline as meaningful.

### Input shape: no historical store, by design

`build_node_baseline` takes an already-ordered `List[BehavioralFingerprint]` as a plain parameter —
there is no fingerprint-history store anywhere in this repo yet (Phase 35's `fingerprints.jsonl` is a
single-capture snapshot, one `computed_at` per batch, not a time series). Building that store is a
separate, later concern this phase's literal scope ("maintain a baseline," not "build a fingerprint
history store") doesn't require solving. This matches every prior FLOWMIND function's "pure function
over caller-supplied data" convention (`compute_node_behavioral_features`, `compute_node_features_
for_window`, `fit_role_model`, `fit_temperature` all take their inputs the same way).

Raises `ValueError` on empty input (a baseline cannot be built from nothing, mirroring `fit_role_model`/
`fit_temperature`'s stance) and on a history mixing more than one `node_id` or `window` (a baseline is
inherently node+window scoped — a real correctness guard, not previously needed by simpler prior
functions).

## Complexity

O(N log N) per feature for N historical fingerprints (median/MAD both require a sort), O(N) for the
set unions and frequency — dominated by the sort, negligible at any realistic history length.

## Failure cases

Empty `fingerprint_history`: `ValueError`. Mixed `node_id` or `window` in the history: `ValueError`.
Both are real failures, not gracefully-empty output — a baseline genuinely cannot be built from
mismatched or absent data.

## Known limitations

- **No persistence, no cross-capture historical store.** Mirrors Phase 33/34/36's own "no artifact
  yet" decisions — inventing a bespoke serialization/store for an intermediate research object with no
  concrete consumer yet would be premature complexity (NFR-9). A future phase (39, or a dedicated
  historical-observation phase) would need to actually accumulate fingerprints across captures/time
  before this function has real multi-capture data to consume.
- **`min_observations=5` is provisional**, not empirically validated — the same honesty standard
  applied to every other undocumented numeric constant in this project (e.g. Phase 25's UDP
  idle-timeout, Phase 34's window durations).
- **`mad` un-floored** — a documented design choice, not an oversight; see above.
- No EWMA-based drift tracking — explicitly Phase 39's job.

## Verification actually performed this phase

- `pytest backend/tests/test_flowmind_baseline.py -v` — **8/8 passed**: empty input raises
  `ValueError`; mixed `node_id`s raise `ValueError`; mixed `window`s raise `ValueError`; median/MAD
  match a hand-computed value exactly (median `3.0`, MAD `1.0` for `[1,2,3,4,100]`); historical ports
  and protocols correctly accumulate as a union across non-overlapping per-fingerprint sets;
  persistent-talker frequency computed correctly (`0.75` for 3-of-4 `True`); `is_sufficient`/
  `observation_count` behave correctly around the `min_observations` threshold; a real end-to-end-shaped
  test building fingerprints via `assemble_node_fingerprint` from constructed `Flow`/`Node` data
  produces a correct baseline (including confirming `historical_ports` stays empty for a node that
  never acts as a flow destination, consistent with Phase 33's destination-only port convention).
- Full repo suite (`pytest`, run from repo root) — **297/297 passed** (up from 289/289), no
  regressions.
- `python -m scripts.validate_data_contracts` — 38/38 passed, no regression (no Pydantic schema
  changed; this phase's output is a plain dataclass).
- `python -m scripts.check_ground_truth_boundary` — clean.

## Status

The behavioral baseline (spec Phase 38, FR-1.15) is implemented and unit-verified: a real, robust
median/MAD baseline plus historical-set novelty tracking, covering every `BehavioralFingerprint`
feature field, implementing exactly the mechanism `algorithm_selection.md` §3 already selected. No
persistence or cross-capture accumulation exists yet, and the EWMA-based drift-vs-transient decision
logic remains explicitly Phase 39's job.
