# NETSCOPE-X — Topology Event Timeline

Phase 47 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 47 — TOPOLOGY EVENT
TIMELINE"): "Create a chronological network event stream."

FR-1.22 (second half): *"...and expose a chronological topology event timeline (spec Phase 47)."*
(The first half, per-node behavioral evolution, was Phase 46's job.)

Code: new `backend/archaeology/timeline.py` (`build_topology_event_timeline`,
`read_topology_event_timeline`); new `experiments/artifacts/paths.py::events_path`.

## No new schema — this reuses Phase 45's exactly

`GraphChangeEvent` (`backend/app/models/snapshot.py`, Phase 04) already declares its own scope in
its docstring: *"a single detected structural or attribute change between two snapshots (spec
Phase 45, 47-48)"* — Phase 47 was always meant to reuse it, not invent a new schema. This phase
does exactly that: `build_topology_event_timeline` returns `List[GraphChangeEvent]`, unmodified.

## The building block is already built — this phase is the chaining/persistence layer

`docs/architecture/graph_difference_engine.md` (Phase 45) said it outright: *"persisting/querying a
change-event history is naturally Phase 47's ('Topology Event Timeline') job once it exists to
consume this."* Phase 45's `diff_snapshots(root, capture_id, from_snapshot, to_snapshot)` is a pure,
unpersisted, exactly-two-snapshot comparison. Phase 47's entire job is:

1. Fetch every one of a capture's persisted `NetworkSnapshot`s via Phase 44's `list_snapshots`
   (already ordered by `version` ascending — generation order).
2. Call `diff_snapshots` unmodified on every consecutive pair.
3. Concatenate the results, in pair order, into one flat list — no new comparison logic, no new
   sorting logic within a pair (`diff_snapshots`'s own `(change_type, target_id, attribute_name)`
   ordering is preserved exactly as-is).
4. Persist the concatenated list.

No new inference happens here at all — this is pure assembly over already-real, already-evidenced
events, the same "combine, don't reinvent" pattern Phase 32's `build_topology_graph` already used
combining Phase 29's nodes and Phase 30-31's edges.

## Chaining by generation order, not by re-sorting on `captured_at`

`create_snapshot`'s own docstring (Phase 44) already documents that snapshot `version` numbering is
"generation order... not `captured_at` order" — creating snapshots out of chronological sequence is
unusual but not prevented. This phase's timeline chains by generation order (the order
`list_snapshots` returns), which is exactly what "chronological *event stream*" means under normal
usage (snapshots created in the order they're captured, which is how every other phase's own tests
and this phase's own tests use it). If snapshots were somehow generated out of `captured_at`
sequence, the resulting stream would reflect generation order, not wall-clock order — an explicit,
documented caveat, the same style of honestly-flagged edge case as Phase 45's own "removals are
structurally real but practically vacuous under normal usage" note, not a silently assumed-away
concern.

## Persistence: write-through, not a cache

`events_path(root, capture_id)` → `captures/<capture_id>/topology_events.jsonl`, written via the
existing generic `write_jsonl` (no new I/O primitive). `build_topology_event_timeline` always
recomputes from the current snapshot set and overwrites the file on every call — the same
"recompute fresh and persist every call, not a cache" convention Phase 32's `GET /topology` already
established for `topology_path`. `read_topology_event_timeline` reads it back, returning `[]` for a
capture with no timeline built yet, mirroring `list_snapshots`'s own missing-directory convention.

## No API wiring — that's explicitly Phase 49's job

`GET /history` (`backend/app/api/routes/history.py`) already declares its own backing
implementation as *"spec Phase 49 (Historical Investigation Engine)"* and stays an untouched 501
stub. This phase deliberately does not wire any route — it builds the capability Phase 49 will
later query (arbitrary `start`/`end` window filtering over exactly this event stream), the same
build-now-wire-later precedent already set by Phase 35's `fingerprints.jsonl` (unwired until Phase
36-37) and Phase 44's `NetworkSnapshot` itself (unwired until this phase and Phase 45 consumed it).

## Worked example

The same two-episode capture used throughout Phases 43-46 (A↔B at `t=0`, C↔D at `t=100s`), with
three snapshots created at `t+10s`, `t+100s`, `t+200s`:

```
edge_added | cap-1-snapshot-1 -> cap-1-snapshot-2 | edge ...:edge:1 (...node:2<->...node:3) not present as of the earlier snapshot
node_added | cap-1-snapshot-1 -> cap-1-snapshot-2 | node ...:node:2 (10.0.0.3) not present as of the earlier snapshot
node_added | cap-1-snapshot-1 -> cap-1-snapshot-2 | node ...:node:3 (10.0.0.4) not present as of the earlier snapshot
```

All three events belong to the first pair (`snapshot-1 -> snapshot-2`, spanning the second
episode's arrival at `t=100s`); the second pair (`snapshot-2 -> snapshot-3`) contributes nothing,
since no further packets exist after `t=100s` — confirming events are grouped and ordered by
generation pair, not re-sorted across the whole timeline.

## Known limitation

Same one Phase 45 already carries forward: this system's topology reconstruction is cumulative
with no expiry concept, so `NODE_REMOVED`/`EDGE_REMOVED` events will essentially never appear in a
normally-generated (chronologically increasing) timeline — a structurally real but practically
vacuous capability, documented, not hidden.

## Verification actually performed this phase

- `pytest backend/tests/test_archaeology_timeline.py -v` — **8/8 passed**: zero and one snapshots
  both produce an empty timeline, never an error; three snapshots produce a timeline exactly equal
  to the concatenation of two separate `diff_snapshots` calls; events are grouped by consecutive
  generation pair in order, not re-sorted globally; `read_topology_event_timeline` round-trips
  byte-for-byte with what `build_topology_event_timeline` just persisted; a capture with no
  timeline built yet reads back `[]`; repeated `build_topology_event_timeline` calls are
  deterministic; every emitted event carries real, non-empty evidence.
- Full repo suite (`pytest backend/tests experiments/tests simulator/tests`, run from repo root) —
  **387/387 passed** (up from 379/379), no regressions.
- `python -m scripts.validate_data_contracts` — 38/38 passed, no regression (no schema changes this
  phase — `GraphChangeEvent`/`ChangeType` reused unmodified).
- `python -m scripts.check_ground_truth_boundary` — clean.
- A real, manual end-to-end run (no Docker needed): built the same two-episode capture, created
  three snapshots, ran `build_topology_event_timeline`, and confirmed the printed output (2 node
  additions + 1 edge addition, all attributed to the first generation pair) exactly matches this
  doc's worked example.

## Status

The topology event timeline (spec Phase 47, FR-1.22's second half) is implemented and
unit-verified. `build_topology_event_timeline` produces a real, persisted, chronological
`GraphChangeEvent` stream by chaining Phase 45's `diff_snapshots` across a capture's full snapshot
history — no new schema, no new inference logic. No API wiring exists yet; `GET /history` remains
explicitly scoped to Phase 49, which will query exactly this persisted stream.
