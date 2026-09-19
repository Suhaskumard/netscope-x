# NETSCOPE-X — Behavioral Evolution Tracking

Phase 46 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 46 — BEHAVIORAL EVOLUTION
TRACKING"): "Track behavioral changes for individual nodes."

FR-1.22 (first half): *"The system shall track behavioral evolution per node over time (spec Phase
46) and expose a chronological topology event timeline (spec Phase 47)."* Only the first half is
this phase's job — the topology event timeline is Phase 47's.

Code: new `backend/archaeology/behavior_evolution.py` (`track_node_behavioral_evolution`).

## Why this isn't a duplicate of Phase 39

Phase 39's `track_node_drift` already exists and already does something that sounds similar:
classify a sequence of new values, relative to a static baseline, as `CONCEPT_DRIFT` or
`TRANSIENT_ANOMALY`. That is a **FLOWMIND anomaly-detection judgment** — "has this node's behavior
deviated enough from its established baseline to matter?" — and it stays exactly where it is.

Phase 46 sits in the Network Archaeology group (Phase 43-49), alongside Phase 45's
`diff_snapshots`. Its job, per the spec's plain wording, is different: a **structural, evidenced
historical record** of what a node's fingerprint values actually did over time — no baseline, no
statistical judgment, no classification. It is the direct behavioral analogue of Phase 45's graph
diff engine, applied to `BehavioralFingerprint` (Phase 33-35) instead of `NetworkSnapshot`/
`TopologyGraph` (Phase 43-44). A caller who wants Phase 39's drift classification on top of this
record already has `track_node_drift` for that — this phase does not call into it, to keep the two
concerns (raw record vs. statistical judgment) separate, exactly as Phase 30→31 kept "aggregate the
evidence" and "score the evidence" as two distinct steps rather than one.

## Why a plain dataclass, not a new Pydantic schema

`GraphChangeEvent` (`backend/app/models/snapshot.py`, Phase 04) already exists, but its own
docstring scopes it to *"spec Phase 45, 47-48"* — deliberately not 46. Nothing in Phase 04 reserved
a schema for per-node behavioral change events. This phase follows the precedent already set by
Phase 38's `NodeBehavioralBaseline` and Phase 39's `DriftTrackingResult`: a plain
`@dataclass(frozen=True)` (`BehavioralEvolutionEvent`), not a new schema addition to
`backend/app/models/`.

## Why a pure function over caller-supplied history, no new store

Phase 35's `fingerprints_path` (`captures/<capture_id>/fingerprints.jsonl`) is written via
`write_jsonl`, which opens the file in `"w"` mode — every call **overwrites** the previous batch,
it does not append. So no real cross-batch fingerprint history exists on disk today; there is
nothing yet to read multiple historical batches back from. Phase 38 and 39 already made this same
call for their own history parameters ("no cross-capture historical store exists yet, building one
is out of scope"), and this phase makes it again: `track_node_behavioral_evolution` takes a plain,
caller-supplied, time-ordered `List[BehavioralFingerprint]` for one node/window, the same
convention `track_node_drift`'s own `new_fingerprints` parameter already establishes and documents.
Building a real persistent fingerprint-history store remains open future work, not silently
side-stepped.

## Algorithm

`track_node_behavioral_evolution(fingerprints)`:

1. Raises `ValueError` on empty input (nothing to track from no observations, mirroring every
   other "cannot compute from nothing" function in this project). Raises `ValueError` if any
   fingerprint's `node_id`/`window` doesn't match the first one's — the same mixed-history guard
   `build_node_baseline`/`track_node_drift` already enforce. A single fingerprint has nothing to
   compare against yet and returns `[]`, not an error.
2. Walks consecutive pairs `(prev, curr)` in the caller's own chronological order (the same
   precondition `track_node_drift` already documents rather than re-deriving order internally).
3. Compares all 7 `BehavioralFingerprint` feature fields between each pair:
   - `distinct_ports` / `distinct_protocols`: set comparison; evidence names the concrete added/
     removed elements (mirrors Phase 38's set-valued historical novelty tracking).
   - `distinct_destinations`, `mean_flow_duration_seconds`, `outbound_byte_ratio`,
     `total_byte_count`: exact value inequality (`!=`) — the same "no invented magnitude threshold"
     precedent Phase 45 already set comparing `Edge.confidence` (also a continuous float) the exact
     same way.
   - `is_persistent_talker`: boolean flip.
4. Emits one `BehavioralEvolutionEvent` per changed field per transition, each carrying concrete,
   non-empty `evidence` (old value → new value, or the specific added/removed set elements) — never
   a bare label, matching the project-wide rule already enforced for `Anomaly`/`GraphChangeEvent`.
5. Returns events deterministically ordered by `(to_computed_at, feature_name)`.

## Worked example

Two fingerprints for the same node, 5 minutes apart:

```
distinct_ports        | [80] -> [443, 80]   | added [443]
is_persistent_talker   | False -> True
outbound_byte_ratio    | 0.4 -> 0.9
total_byte_count       | 5000 -> 52000
```

(`distinct_destinations` and `mean_flow_duration_seconds` were unchanged in this example and
correctly produced no events.)

## No persistence, no API wiring

No new artifact path is added — `track_node_behavioral_evolution` is a pure computation over a
caller-supplied fingerprint list, mirroring Phase 41's `format_anomaly_report`, Phase 42's
`evaluate_anomaly_detection`, and Phase 45's `diff_snapshots` (all pure, unpersisted). `GET
/behaviors/{node_id}` stays a 501 stub — unrelated to this phase, still structurally blocked on
Phase 36-37's role wiring per Phase 35's own note.

## Known limitation

No real cross-batch fingerprint history exists on disk yet (see above) — this phase's function is
verified against caller-constructed and `assemble_node_fingerprint`-derived fingerprint lists only,
not against a real persisted multi-batch history, since no such history can be produced by any
existing code yet. Building a real fingerprint-history store is future work.

## Verification actually performed this phase

- `pytest backend/tests/test_archaeology_behavior_evolution.py -v` — **12/12 passed**: empty/mixed-
  node/mixed-window `ValueError`s; a single fingerprint returns `[]`; no changes between identical
  fingerprints returns `[]`; a changed continuous feature produces exactly one event with correct
  previous/new values; a changed port set names the added port; a removed protocol names it;
  an `is_persistent_talker` flip is detected; every event carries non-empty evidence; multiple
  transitions are chronologically ordered and identical repeated calls produce identical output; a
  real end-to-end-shaped test building fingerprints via Phase 35's `assemble_node_fingerprint` from
  two distinct flow sets for the same node.
- Full repo suite (`pytest backend/tests experiments/tests simulator/tests`, run from repo root) —
  **379/379 passed** (up from 367/367), no regressions.
- `python -m scripts.validate_data_contracts` — 38/38 passed, no regression (no schema changes this
  phase).
- `python -m scripts.check_ground_truth_boundary` — clean.
- A real, manual end-to-end run (no Docker needed): built two synthetic `BehavioralFingerprint`s for
  the same node 5 minutes apart with a deliberately widened port set, byte ratio, persistence flag,
  and byte volume, ran `track_node_behavioral_evolution`, and confirmed the printed events exactly
  match this doc's worked example.

## Status

Behavioral evolution tracking (spec Phase 46, FR-1.22 first half) is implemented and
unit-verified. `track_node_behavioral_evolution` produces a real, evidenced, chronological record
of per-node fingerprint changes, deliberately distinct from Phase 39's statistical drift
classification. No persistence or API wiring exists yet — both remain natural jobs for later
phases (Phase 47's topology event timeline is the structural counterpart; a real fingerprint-history
store is open future work).
