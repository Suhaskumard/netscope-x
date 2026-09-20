# NETSCOPE-X — Digital Twin Synchronization

Phase 58 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 58 — DIGITAL TWIN
SYNCHRONIZATION"): keep the digital twin "kept synchronized with new observations, including
additions, removals, behavior changes, and confidence changes."

FR-1.31 (second half): *"...kept synchronized with new observations, including additions,
removals, behavior changes, and confidence changes (spec Phase 58)."*

Code: new `backend/digital_twin/sync.py` (`TwinSyncResult`, `sync_digital_twin`).

## An assembly phase, not new inference

Matching Phase 57's own precedent (and Phase 32/45/46/47's before it), `sync_digital_twin`
introduces no new diffing logic. FR-1.31's four named signals map directly onto two primitives
this project already built and proved:

- **Additions, removals, confidence changes** → Phase 45's `diff_snapshots(root, capture_id,
  from_snapshot, to_snapshot)`. Its `_edge_attribute_events` already diffs `Edge.confidence` (and
  `protocols`) on every surviving edge — this *is* "confidence changes", real since Phase 45, not
  built here. Called once, between the twin's own anchoring snapshot and the new one.
- **Behavior changes** → Phase 46's `track_node_behavioral_evolution(fingerprints)`. It requires
  every fingerprint it's given to share one `(node_id, window)` (a real correctness guard, not
  relaxed here), so `sync_digital_twin` calls it once per `(node_id, window)` pair that has *both*
  a previous fingerprint (from `twin.behavioral_fingerprints`) and a newly supplied one — a node
  observed for the first time this round has nothing to diff against yet (Phase 46's own "single
  fingerprint, nothing to compare" convention), not an error.

## `sync_digital_twin(root, twin, new_snapshot, new_behavioral_fingerprints=None, ...)`

Three steps, each delegating to already-real machinery:

1. `structural_changes = diff_snapshots(root, twin.capture_id, twin.snapshot, new_snapshot)`.
2. For each `(node_id, window)` present in both the old and newly-supplied fingerprints,
   `track_node_behavioral_evolution([previous, new])`, concatenated and sorted deterministically by
   `(to_computed_at, node_id, feature_name)`.
3. **Fingerprint carry-forward**: a `(node_id, window)` not re-supplied this round hasn't stopped
   being the node's last-known state — it's carried forward unchanged into the rebuilt twin, not
   dropped. A re-supplied one replaces its predecessor. The merged list is passed to Phase 57's own
   `build_digital_twin(root, twin.capture_id, new_snapshot, merged_fingerprints, ...)` to produce
   the updated twin — a fresh, from-scratch rebuild, not an in-place mutation, the same
   "recompute fresh from persisted artifacts" convention `create_snapshot`/`diff_snapshots`
   themselves already rely on.

Returns `TwinSyncResult(twin, structural_changes, behavior_changes)` — the updated twin plus the
real, evidenced record of what changed, not just the new state on its own; a caller wanting to know
*why* the twin moved (e.g. to surface it to an operator) has the evidence, not just the delta
inferred by diffing two twins after the fact.

No new Pydantic schema (same precedent as Phase 57's own `DigitalTwin`), no persistence of the
result, no API route — nothing in Phase 09's fixed endpoint surface names a twin-sync resource.

## Worked example

The same two-episode fixture Phase 43-58's own tests use (A↔B at t=0, C↔D at t=100s), synced from
an early twin (anchored at t=50s, episode 1 only) to a later snapshot (t=200s, both episodes, plus
extra A↔B traffic added after t=50s):

```
result = sync_digital_twin(root, early_twin, later_snapshot, new_behavioral_fingerprints=[new_fp])

# structural_changes:
#   NODE_ADDED  x2   (10.0.0.3, 10.0.0.4)
#   EDGE_ADDED  x1   (10.0.0.3 <-> 10.0.0.4)
#   ATTRIBUTE_CHANGED x1  (10.0.0.1<->10.0.0.2 edge, confidence: previous_value < new_value)
#
# behavior_changes: real BehavioralEvolutionEvents from track_node_behavioral_evolution([old_fp, new_fp])
#
# result.twin.snapshot == later_snapshot
# result.twin.topology == read_snapshot_graph(root, capture_id, later_snapshot)
```

## Verification actually performed this phase

- `pytest backend/tests/test_digital_twin_sync.py -v` — **6/6 passed**: syncing across a new
  episode reports exactly the expected `NODE_ADDED`/`EDGE_ADDED` events and the rebuilt twin's
  topology matches `read_snapshot_graph` on the new snapshot directly; adding more traffic to a
  surviving edge between two snapshots produces exactly one `ATTRIBUTE_CHANGED`/`confidence` event
  with a strictly higher new value (confidence is monotonic by construction, per
  `edge_discovery.md`); a resupplied fingerprint for the same node produces the same behavior-change
  events `track_node_behavioral_evolution` itself would, and the rebuilt twin carries the *new*
  fingerprint object; an old fingerprint not resupplied produces no behavior-change events and is
  carried forward into the rebuilt twin unchanged; a brand-new node's first-ever fingerprint
  produces no behavior-change events (nothing to diff against) but is present in the rebuilt twin;
  a real end-to-end run confirms `sync_digital_twin`'s own outputs are byte-for-byte identical to
  `diff_snapshots`/`track_node_behavioral_evolution` called standalone on the same inputs — the
  wrapper adds no hidden behavior of its own.
- Full repo suite (`pytest backend/tests experiments/tests simulator/tests`, run from repo root) —
  **482/482 passed** (up from 476/476), no regressions.
- `python -m scripts.validate_data_contracts` — 38/38 passed, no regression (no schema changes this
  phase).
- `python -m scripts.check_ground_truth_boundary` — clean.

## Status

Digital twin synchronization (spec Phase 58, FR-1.31 second half) is implemented and
unit-verified: `sync_digital_twin` advances a `DigitalTwin` to a new `NetworkSnapshot`, reporting
genuine additions/removals/confidence changes (Phase 45) and behavior changes (Phase 46) alongside
a freshly rebuilt twin, rather than mutating the old one or inventing new diff logic. No API route
exists yet — nothing in the fixed Phase 09 surface calls for one. Controlled failure injection
(Phase 59), the dynamic path engine (Phase 60), and the simulation/counterfactual pipeline
(Phase 61+) remain ahead.
