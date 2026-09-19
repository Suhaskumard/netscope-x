# NETSCOPE-X — Multi-Dimensional Anomaly Detection

Phase 40 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 40 — MULTI-DIMENSIONAL ANOMALY
DETECTION"): "Detect deviations in: traffic volume, destinations, ports, protocols, timing, topology,
behavior." FR-1.17: "The system shall detect multi-dimensional anomalies (volume, destinations, ports,
protocols, timing, topology, behavior) (spec Phase 40)." FR-1.18 (evidence formatting) is a separate,
later FR (Phase 41) — confirmed no evidence-formatting requirement lives in FR-1.17 itself, though
`Anomaly.evidence` (Phase 04) already requires at least one string, so this phase unavoidably produces
*some* real evidence as a side effect of computing each deviation.

Code: `backend/flowmind/anomaly/node_anomaly.py` (`detect_node_anomalies`/
`detect_node_anomalies_with_drift`) — the first code to populate `backend/app/models/anomaly.py`'s
`Anomaly` schema with real detections, and the piece Phase 39's own doc and `PROJECT_STATE.md` already
named as "Phase 40's job": deciding *whether* a sequence deviates enough to flag in the first place.

## Two real gaps, resolved explicitly

**`TRAFFIC_VOLUME` — closed via a backward-compatible schema extension.** No node-level byte/packet
count existed anywhere before this phase: `compute_node_behavioral_features` already computed a
`total_bytes` running sum internally (to derive `outbound_byte_ratio`) and discarded it. `total_byte_count`
was added to `NodeBehavioralFeatures` (dataclass default `0`), `BehavioralFingerprint`
(`Field(default=0, ge=0)`), and `NodeBehavioralBaseline` (a 5th `RobustFeatureBaseline`), with
`track_node_drift` (Phase 39) extended to track it as a 5th continuous feature. Every default value
means no existing test fixture across 5 files needed updating — only the one hardcoded "all four
continuous features" set-equality assertion in `test_flowmind_drift.py` needed widening to five,
confirmed re-passing.

**`TOPOLOGY` — scoped out explicitly, not silently.** No time-series graph-diff capability exists
anywhere in this repo (`backend/nettrace/topology/` only builds and compares graphs at a single point
in time or against ground truth — Phase 32's `compare_topology_to_ground_truth` is inferred-vs-ground-
truth, not inferred-at-T1-vs-inferred-at-T2). Building one (versioned snapshots + structural diff) is
explicitly Phase 45's job — `GraphChangeEvent`/`NetworkSnapshot` (`backend/app/models/snapshot.py`,
Phase 04) are already reserved, unimplemented schemas for exactly this. `detect_node_anomalies` never
emits `AnomalyDimension.TOPOLOGY` — verified directly by `test_no_topology_anomaly_is_ever_produced`.
Building a shadow diff engine here would duplicate/pre-empt Phase 45's actual job.

## Algorithm

`docs/architecture/algorithm_selection.md` §3 (already selected, Phase 05) names two mechanisms, both
implemented here for the 5 dimensions that are honestly detectable from Phase 33-39's existing
machinery:

### Continuous z-score deviation (`DESTINATIONS`, `TIMING`, `BEHAVIOR`, `TRAFFIC_VOLUME`)

`z = (current_value - baseline.median) / max(baseline.mad, mad_floor)`, flagged when `|z| >=
z_threshold`. `DESTINATIONS` uses `distinct_destinations` (a count comparison — matches spec Phase
41's own worked example, "historical destinations: 4, current destinations: 9," literally); `TIMING`
uses `mean_flow_duration_seconds`; `BEHAVIOR` uses `outbound_byte_ratio`; `TRAFFIC_VOLUME` uses the new
`total_byte_count`. `mad_floor` (default `1e-6`) prevents division by an MAD of exactly `0.0` — the
same floor-belongs-to-the-consumer reasoning already established by Phase 39.

### Set-difference novelty (`PORTS`, `PROTOCOLS`)

Flagged when the current fingerprint's `distinct_ports`/`distinct_protocols` contains any value absent
from `baseline.historical_ports`/`historical_protocols` — directly implements §3's "explicit
set-difference novelty checks (new destination/port not in historical set)." Both historical sets
already existed from Phase 38 with zero new work needed. `port_count`'s own continuous baseline is
deliberately *not* also checked under `PORTS` — that would double-detect the same underlying signal
via two mechanisms; novelty (specific new value) and magnitude (how many) answer different questions,
and only the novelty framing matches §3's literal example wording.

### Score formula

Reuses the exact saturating-curve shape already established for Phase 30's edge confidence
(`1 - exp(-x/scale)`): continuous dimensions use `score = 1 - exp(-|z| / z_threshold)`; novelty
dimensions use `score = 1 - exp(-num_new_items / novelty_scale)`. Bounded in `[0, 1)` by construction —
verified directly (`test_scores_are_bounded_and_never_reach_exactly_one`), consistent with every other
saturating score already in this project.

### Cold-start guard

Both entry points return `[]` immediately if `baseline.is_sufficient` is `False` — reusing Phase 38's
own flag for exactly the purpose it was built for: an unreliable, barely-estimated baseline should
never produce a confident-looking anomaly.

### Two entry points, matching what a caller has

- **`detect_node_anomalies(baseline, fingerprint, ...)`** — single new fingerprint. Every emitted
  `Anomaly` gets `anomaly_class=AnomalyClass.TRANSIENT_ANOMALY` as a documented, provisional label — a
  single observation cannot itself establish drift (Phase 39's mechanism needs a *sequence*).
- **`detect_node_anomalies_with_drift(baseline, new_fingerprints, ...)`** — detects against the *last*
  fingerprint in a caller-supplied sequence, then for any continuous-feature anomaly, calls Phase 39's
  `track_feature_drift` over the full sequence's values for that feature to set the *real*
  `anomaly_class`. This is the literal "hand a flagged deviation to Phase 39's `track_feature_drift`"
  `PROJECT_STATE.md` already committed to — verified directly
  (`test_detect_with_drift_upgrades_sustained_deviation_to_concept_drift`).

### Evidence convention

One human-readable string plus `evidence_values: Dict[str, str]` (stringified numbers, snake_case
keys), following the exact convention already established in `scripts/validate_data_contracts.py`'s
own `Anomaly` example (`historical_destinations`/`current_destinations`).

### Provisional numeric defaults

`z_threshold=3.0` and `novelty_scale=1.0` — evidence-light, documented choices, the same honesty
standard applied to every other undocumented numeric constant in this project (Phase 25's UDP
idle-timeout, Phase 30's packet scale, Phase 34's window durations, Phase 36's variance floor/Laplace
smoothing, Phase 38's `min_observations`, Phase 39's `alpha`/`drift_threshold_mads`).

## Failure cases

A `fingerprint`/`new_fingerprints` entry whose `node_id`/`window` doesn't match `baseline`'s:
`ValueError`. Empty `new_fingerprints` in `detect_node_anomalies_with_drift`: `ValueError`. A
cold-start-insufficient baseline: `[]`, never an error.

## Known limitations

- **`TOPOLOGY` dimension never produced** — explicitly deferred to Phase 45, stated above, not a
  silent gap.
- **`z_threshold`/`novelty_scale` are provisional**, not empirically validated against real Docker-lab
  data (no Docker this session, the same constraint every FLOWMIND phase since 36 has carried).
- **`port_count`/`is_persistent_talker`/`persistent_talker_frequency` aren't separately checked** —
  `port_count`'s magnitude is deliberately not double-detected alongside `PORTS`' novelty check (see
  above); a persistence-flip anomaly (historically persistent, suddenly not) has no dedicated check
  this phase, since it's a frequency-vs-single-boolean comparison the existing `RobustFeatureBaseline`
  pattern doesn't cleanly cover — a plausible future enhancement, not attempted here (NFR-9).
- No persistence, no API wiring — Phase 41's evidence formatting and any eventual `/anomalies` route
  are separate, later work.

## Verification actually performed this phase

- `pytest backend/tests/test_flowmind_anomaly.py -v` — **12/12 passed**: cold-start guard returns
  `[]`; a `DESTINATIONS` anomaly's `evidence_values` exactly match the historical median and current
  count; `TIMING`/`BEHAVIOR`/`TRAFFIC_VOLUME` anomalies fire correctly on their respective deviations;
  `PORTS`/`PROTOCOLS` anomalies fire only for genuinely new values, confirmed both positive and
  negative; every score stays in `[0, 1)`, never saturating to exactly `1.0` at a realistic (not
  degenerate) baseline MAD; `detect_node_anomalies` always assigns the provisional
  `TRANSIENT_ANOMALY`; `detect_node_anomalies_with_drift` correctly upgrades a sustained 20-observation
  deviation to `CONCEPT_DRIFT`; no `TOPOLOGY` anomaly is ever produced; a real end-to-end run through
  `assemble_node_fingerprint` from constructed `Flow`/`Node` data produces a real `DESTINATIONS`
  anomaly.
- `pytest backend/tests/test_flowmind_node_features.py backend/tests/test_flowmind_baseline.py
  backend/tests/test_flowmind_drift.py -v` — **26/26 passed** (9+8+9), confirming the `total_byte_count`
  schema extension didn't break Phases 33/38/39 (one test in `test_flowmind_drift.py` updated from
  "four" to "five" continuous features, re-verified).
- Full repo suite (`pytest`, run from repo root) — **318/318 passed** (up from 306/306), no
  regressions.
- `python -m scripts.validate_data_contracts` — 38/38 passed, no regression (`Anomaly` schema
  unchanged; `BehavioralFingerprint`'s new field is additive/defaulted).
- `python -m scripts.check_ground_truth_boundary` — clean.

## Status

Multi-dimensional anomaly detection (spec Phase 40, FR-1.17) is implemented and unit-verified for 5 of
the 7 `AnomalyDimension` values, using exactly the two mechanisms `algorithm_selection.md` §3 already
selected. `TOPOLOGY` is explicitly deferred to Phase 45's graph-diff machinery. Real integration with
Phase 39's drift classification is genuine, not stubbed — `detect_node_anomalies_with_drift` calls the
real `track_feature_drift` function. No persistence or API wiring exists yet; Phase 41's evidence
formatting is separate, later work.
