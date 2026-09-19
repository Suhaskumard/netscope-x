# NETSCOPE-X — Graph Difference Engine

Phase 45 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 45 — GRAPH DIFFERENCE
ENGINE"): "Detect: node additions, node removals, edge additions, edge removals, attribute
changes."

FR-1.21 (second half): *"...and compute structural diffs between them (node/edge
additions/removals, attribute changes) (spec Phase 45)."*

Code: new `backend/archaeology/diff.py` (`diff_snapshots`) — the first real use of
`backend/app/models/snapshot.py`'s `GraphChangeEvent`/`ChangeType` (Phase 04).

## The schema is already exactly built for this

`ChangeType` (`NODE_ADDED`/`NODE_REMOVED`/`EDGE_ADDED`/`EDGE_REMOVED`/`ATTRIBUTE_CHANGED`) is the
master spec's bullet list verbatim. `GraphChangeEvent` carries `from_snapshot_id`/`to_snapshot_id`/
`occurred_at`, `affected_node_id`/`affected_edge_id`/`attribute_name`/`previous_value`/`new_value`,
and required non-empty `evidence` — with a validator already enforcing that the target field
matches the declared `change_type`. Nothing needed to change in Phase 04's schema; this phase
populates it for the first time.

## The key property this design depends on — verified, not assumed

`Node.node_id`/`Edge.edge_id` are deterministic index-based ids (`f"{capture_id}:node:{index}"`/
`f"{capture_id}:edge:{index}"`), assigned by sorting on `first_observed` (nodes) /
`(first_observed, source_node_id, target_node_id)` (edges). Because Phase 43's `as_of` filtering
only ever *adds* more evidence as `as_of` increases — a strict superset relationship — an
already-included node/edge's `first_observed` never changes as later evidence is added. Every node/
edge newly included at a larger `as_of` necessarily has a `first_observed` strictly later than
every node/edge already included at the smaller `as_of` (otherwise it would already have been
included). Given ascending sort, this means the relative order — and therefore the assigned index/
id — of anything already present is preserved exactly at any later `as_of` for the same
`capture_id`.

This means two snapshots of the same capture can be diffed by plain `node_id`/`edge_id` set
comparison — no separate "same real-world entity" matching problem to solve, unlike Phase 32's
inferred-vs-ground-truth comparison (which had to match via IP sets because the two sides' id
schemes were independently generated and structurally incomparable).

`test_node_and_edge_ids_are_stable_across_growing_as_of` verifies this directly rather than trusting
the reasoning alone — the whole algorithm depends on it holding.

## Algorithm

`diff_snapshots(root, capture_id, from_snapshot, to_snapshot)`:

1. Fetch both graphs via Phase 44's own `read_snapshot_graph` — directly reusable, exactly as that
   function's own docstring anticipated.
2. **Node/edge additions/removals**: plain set-difference on `node_id`/`edge_id`. `NODE_ADDED`/
   `EDGE_ADDED` for ids only in `to`; `NODE_REMOVED`/`EDGE_REMOVED` for ids only in `from`.
3. **Attribute changes — edges only**: for edge ids present in *both* graphs, compare `confidence`
   and `protocols` on the matching `Edge` objects. One event per changed attribute (the schema
   allows exactly one `attribute_name` per event, so an edge changing both fields between two
   snapshots yields two events).
4. `occurred_at = to_snapshot.captured_at` for every event. `evidence` is a concrete sentence
   naming the specific node/edge id and (for attribute changes) the specific old/new values —
   never a bare label, satisfying `GraphChangeEvent.evidence`'s own requirement with genuine
   content from the start (mirroring how Phase 40 "unavoidably produce[d] real evidence" ahead of
   Phase 41 formally standardizing anomaly evidence).
5. Deterministically ordered by `(change_type, target_id, attribute_name or "")`; `event_id` built
   directly from that same content, unique by construction within one diff call.

## Why node attribute changes are never produced

A `Node`'s only non-identity field is `last_observed`, which trivially advances every time *any*
later traffic touches that IP at all — reporting that as a "change" would be pure noise with no
topological significance (every node would show a spurious attribute-change event on almost every
diff). Explicitly excluded, verified directly by
`test_diff_never_produces_node_attribute_changed_events` (which first confirms `last_observed`
genuinely advanced, then confirms no event was produced for it) — the same documented-scope-out
pattern as Phase 40 explicitly never producing `TOPOLOGY`.

## Known limitation: removals are structurally real but practically vacuous today

Under normal (chronologically increasing `captured_at`) usage, `NODE_REMOVED`/`EDGE_REMOVED` will
essentially never fire: this system has no notion of a node/edge "expiring" — Phase 29-32's
topology reconstruction is cumulative (once observed, always remembered), so a later snapshot's
node/edge set is always a superset of an earlier one's. The set-difference logic is fully general
and correctly produces removals when snapshots are compared out of chronological order
(`test_diff_reversed_order_produces_removed_events` proves this directly), but that isn't how this
phase expects normal usage to look. The master spec explicitly asks for the *capability*, which
this phase provides, even though today's upstream data model rarely exercises the removal branch.

## No persistence, no API wiring

No `GraphChangeEvent`-specific artifact path exists (`experiments/artifacts/paths.py` has no
`events_path`), and none is added — `diff_snapshots` is a pure computation over two
already-persisted snapshots, mirroring Phase 41's `format_anomaly_report` and Phase 42's
`evaluate_anomaly_detection` (both pure, unpersisted). `GET /history` is explicitly scoped to Phase
49; persisting/querying a change-event history is naturally Phase 47's ("Topology Event Timeline")
job once it exists to consume this.

## Worked example

The same two-episode capture used throughout Phases 43-45 (A↔B at `t=0`, C↔D at `t=100s`), diffed
between a snapshot at `t+50s` and one at `t+200s`:

```
3 change events:
- node_added: <node C>   evidence: node <id> (10.0.0.3) not present as of the earlier snapshot
- node_added: <node D>   evidence: node <id> (10.0.0.4) not present as of the earlier snapshot
- edge_added: <edge C-D> evidence: edge <id> (<C><->D>) not present as of the earlier snapshot
```

## Verification actually performed this phase

- `pytest backend/tests/test_archaeology_diff.py -v` — **10/10 passed**: the id-stability property
  holds directly (not just reasoned about); node and edge additions detected correctly; no changes
  between identical snapshots; an edge's `confidence` genuinely growing (more corroborating flows
  joining its bucket) produces one `ATTRIBUTE_CHANGED` event with `previous_value < new_value`; an
  edge gaining a new protocol produces an `ATTRIBUTE_CHANGED` event with `attribute_name=
  "protocols"`; no node-level attribute-change event is ever produced even when `last_observed`
  clearly advances; reversed comparison correctly produces `NODE_REMOVED`/`EDGE_REMOVED` events and
  zero additions; every emitted event carries real, non-empty evidence; identical repeated calls
  produce identical, identically-ordered output.
- Full repo suite (`pytest backend/tests experiments/tests simulator/tests`, run from repo root) —
  **367/367 passed** (up from 357/357), no regressions.
- `python -m scripts.validate_data_contracts` — 38/38 passed, no regression (`GraphChangeEvent`/
  `ChangeType` unchanged — first real use only).
- `python -m scripts.check_ground_truth_boundary` — clean.
- A real, manual end-to-end run (no Docker needed): built the same synthetic two-episode capture,
  created two snapshots via `create_snapshot`, diffed them via `diff_snapshots`, and confirmed the
  printed output (2 node additions, 1 edge addition, each with concrete evidence) exactly matched
  this doc's worked example.

## Status

The graph difference engine (spec Phase 45, FR-1.21's second half) is implemented and
unit-verified. `diff_snapshots` produces real, evidenced `GraphChangeEvent`s covering all five of
the master spec's named change types, built on a directly-verified id-stability property rather
than an assumed one. Node attribute changes are an explicit, documented scope-out; removals are a
structurally real but today practically-vacuous capability, also documented. No persistence or API
wiring exists yet — both are natural jobs for Phase 47 and beyond.
