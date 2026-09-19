# NETSCOPE-X — Concept Drift Detection

Phase 39 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 39 — CONCEPT DRIFT
DETECTION"): "Distinguish: temporary anomaly from: persistent behavioral evolution." FR-1.16
(`docs/requirements/system_requirements.md`): "The system shall distinguish temporary anomalies from
persistent behavioral evolution (concept drift) (spec Phase 39; RQ3/RQ4)."

Code: `backend/flowmind/drift/node_drift.py` (`track_feature_drift`/`track_node_drift`) — the first
code to populate `backend/app/models/anomaly.py`'s `AnomalyClass` enum (`TRANSIENT_ANOMALY`/
`CONCEPT_DRIFT`, Phase 04, unpopulated until now) with real classifications.

## Explicit non-scope: Phase 39 vs. 40

This phase classifies a *given* deviating sequence as transient or drift — it does **not** decide
*whether* a sequence is anomalous in the first place. That thresholding/detection decision is Phase
40's job ("Multi-Dimensional Anomaly Detection"). This mirrors the Phase 38→39→40→41 chain: 38 builds
the baseline, 39 (this phase) provides the transient-vs-drift classification mechanism, 40 will
decide when to actually flag a deviation, 41 will format the evidence. Each phase builds on the
previous without reaching into the next's job — the same discipline every phase since 29 has followed.

**Precondition, stated explicitly, not silently assumed**: `track_feature_drift`/`track_node_drift`
are only meaningful when applied to a sequence already known or suspected to deviate (Phase 40's
eventual job to flag such sequences). Calling either on ordinary, non-deviating history returns
`TRANSIENT_ANOMALY` vacuously — the EWMA never moves far from the baseline median, which is technically
true ("no persistent drift occurred") even though nothing anomalous happened at all. This is an
accepted scope limitation, not a bug — verified directly by `test_one_feature_drifts_while_another_
stays_stable`'s stable-feature assertion.

## Algorithm

`docs/architecture/algorithm_selection.md` §3 (already selected, Phase 05), quoted: "implemented as an
EWMA-updated baseline with a slower update rate than the anomaly-detection window — a sustained
deviation that the EWMA baseline eventually absorbs is classified `concept_drift`; a deviation that
reverts before the baseline shifts is classified `transient_anomaly`."

### Mechanism

For one feature, `track_feature_drift(baseline, feature_name, observed_values, alpha=0.05,
drift_threshold_mads=2.0, mad_floor=1e-6)`:
1. Seed `ewma = baseline.median` (Phase 38's robust median for this feature).
2. For each new observation `x` in `observed_values` (in time order): `ewma = alpha*x + (1-alpha)*ewma`.
3. After the full sequence, compute `deviation_in_mads = |final_ewma - baseline.median| /
   max(baseline.mad, mad_floor)`.
4. `CONCEPT_DRIFT` if `deviation_in_mads >= drift_threshold_mads`, else `TRANSIENT_ANOMALY`.

This directly implements §3's own description using only the EWMA's own slow rate against the
*original, static* Phase 38 baseline — no second, separately-defined "anomaly-detection window" rate
is needed (Phase 40, which would define one, doesn't exist yet). A sustained deviation has time to pull
the slow-moving EWMA measurably away from where it started; a single reverting blip gets pulled back
toward the original median before the slow EWMA can move far — the distinction emerges from the EWMA
dynamics themselves, not from a second comparison mechanism.

### Worked example (hand-verified, `alpha=0.5` for illustration)

Baseline median `10.0`. Observed `[20.0, 20.0, 20.0]`:
`ewma₀ = 0.5·20 + 0.5·10 = 15.0`, `ewma₁ = 0.5·20 + 0.5·15 = 17.5`, `ewma₂ = 0.5·20 + 0.5·17.5 = 18.75`.
Verified exactly by `test_ewma_trace_hand_computed`.

At the project's actual default `alpha=0.05` (much slower, as §3's "slower update rate" calls for): a
single blip `[20.0] + [10.0]×7` decays back toward the median (`ewma ≈ 10.35` after 8 steps,
`< 2` MADs away) → `TRANSIENT_ANOMALY`; a sustained shift `[20.0]×20` pulls the EWMA to `≈ 16.4`
(`> 2` MADs away) → `CONCEPT_DRIFT`. Both verified directly.

### `mad_floor`: deliberately not in Phase 38

Phase 38's `RobustFeatureBaseline.mad` is reported honestly un-floored (`docs/architecture/
behavioral_baseline.md`: "Whether/how a future consumer floors it against division-by-zero... is that
consumer's own choice to make and document, not baked into the baseline itself"). This is that
consumer: `mad_floor` (default `1e-6`) prevents a division by an MAD of exactly `0.0` (e.g. a feature
with identical historical values) when computing `deviation_in_mads`.

### Provisional numeric defaults

`alpha=0.05` and `drift_threshold_mads=2.0` are evidence-light, documented choices — the same honesty
standard already applied to every other undocumented numeric constant in this project (Phase 25's UDP
idle-timeout, Phase 30's packet scale, Phase 34's window durations, Phase 36's variance
floor/Laplace smoothing, Phase 38's `min_observations`). No spec text, FR, or `algorithm_selection.md`
gives concrete numbers for either.

### Batch convenience: `track_node_drift`

`track_node_drift(baseline, new_fingerprints, alpha=0.05, drift_threshold_mads=2.0, mad_floor=1e-6)`
runs `track_feature_drift` across all 4 continuous `NodeBehavioralBaseline` features
(`distinct_destinations`, `mean_flow_duration_seconds`, `outbound_byte_ratio`, `port_count`) for a
caller-supplied, time-ordered sequence of the same node's newly observed fingerprints — the
established single-feature-function-plus-batch-wrapper pattern already used in Phase 33/34 and Phase
36. Raises `ValueError` if any fingerprint's `node_id`/`window` doesn't match the baseline's — a real
correctness guard, the same spirit as Phase 38's own mixed-history guard in `build_node_baseline`.

## Failure cases

Empty `observed_values`/`new_fingerprints`: `ValueError` — nothing to classify from no observations,
mirroring every other "cannot compute from nothing" function in this project (`fit_role_model`,
`fit_temperature`, `build_node_baseline`). A `node_id`/`window` mismatch between `new_fingerprints` and
`baseline`: `ValueError`.

## Known limitations

- **Vacuous classification on non-deviating input** — explicitly documented above, not a bug.
- **`alpha`/`drift_threshold_mads` are provisional**, not empirically validated against real Docker-lab
  data (no Docker this session, the same constraint every FLOWMIND phase since 36 has carried).
- **Only the 4 continuous features are tracked** — the 2 set-valued features (`distinct_ports`,
  `distinct_protocols`) and the boolean (`is_persistent_talker`) have no EWMA-drift analogue defined
  here; a future phase would need to define what "drift" means for a historical set or a frequency,
  which §3 doesn't specify.
- No persistence — mirrors every prior FLOWMIND phase without a concrete downstream consumer yet
  (Phase 40 doesn't exist).

## Verification actually performed this phase

- `pytest backend/tests/test_flowmind_drift.py -v` — **9/9 passed**: empty input raises `ValueError`;
  a reverting single-blip sequence classifies as `TRANSIENT_ANOMALY`; a sustained 20-observation shift
  classifies as `CONCEPT_DRIFT`; the EWMA trace matches a hand-computed value exactly
  (`[15.0, 17.5, 18.75]`); `track_node_drift` raises on empty input, on `node_id` mismatch, and on
  `window` mismatch; it covers all 4 continuous features; a mixed scenario (one feature sustained-shifted,
  one stable) correctly classifies the shifted feature as drift and the stable one as (vacuously)
  transient.
- Full repo suite (`pytest`, run from repo root) — **306/306 passed** (up from 297/297), no
  regressions.
- `python -m scripts.validate_data_contracts` — 38/38 passed, no regression (`AnomalyClass` enum
  unchanged; this phase populates it, doesn't modify it).
- `python -m scripts.check_ground_truth_boundary` — clean.

## Status

Concept drift detection's mechanism (spec Phase 39, FR-1.16) is implemented and unit-verified: a real
EWMA-based transient-vs-drift classifier built directly on Phase 38's robust baseline, implementing
exactly the mechanism `algorithm_selection.md` §3 already selected. It classifies a given deviating
sequence — deciding *whether* a sequence deviates enough to classify in the first place remains
explicitly Phase 40's job.
