# NETSCOPE-X — Network Snapshot Engine

Phase 44 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 44 — NETWORK SNAPSHOT
ENGINE"): "Generate versioned network snapshots."

FR-1.21: *"The system shall generate versioned network snapshots (spec Phase 44) and compute
structural diffs between them (spec Phase 45)."* Only the first half is this phase's job.

Code: new `backend/archaeology/snapshots.py` (`create_snapshot`, `list_snapshots`,
`read_snapshot_graph`) — the first real code in a new `backend/archaeology/` package.

## Why this is the first `backend/archaeology/` code

`docs/architecture/temporal_graph_model.md` (Phase 43) explicitly deferred creating this package:
*"`backend/archaeology/` will be justified for real starting Phase 44, when `NetworkSnapshot`
persistence needs a genuine new home."* That moment is now. Three pieces existed, each already
designed for this, but never connected until this phase:

- `backend/app/models/snapshot.py`'s `NetworkSnapshot` (Phase 04): `snapshot_id`, `graph_id`,
  `captured_at`, `version` — never constructed for real anywhere.
- `experiments/artifacts/paths.py`'s `snapshot_path` — reserved since Phase 10's original artifact
  layout (`captures/<id>/snapshots/<snapshot_id>.json`), never called anywhere.
- Phase 43's `build_topology_graph(..., as_of=t)` — the mechanism that lets a snapshot's claimed
  `captured_at` genuinely match the evidence its graph contains.

## Design

### `captured_at` doubles as the `as_of` bound

`create_snapshot(root, capture_id, captured_at=None, ...)`: `captured_at` (default
`datetime.now(timezone.utc)`) is passed straight into `build_topology_graph` as `as_of`, as well as
being stored on the resulting `NetworkSnapshot`. This was a deliberate choice over the alternative
of always building the full, unbounded graph and merely *labeling* it with a timestamp: a label
decoupled from content would let two snapshots claim different capture times while carrying
identical evidence, defeating the point of "versioned" snapshots representing genuinely different
moments. Tying the two together means a later snapshot's graph can only ever contain as much or
more evidence than an earlier one for the same capture — a real, meaningful signal Phase 45's
diffing will build on.

### Versioning: per-`capture_id`, by generation order

`list_snapshots(root, capture_id)` reads every persisted snapshot back and sorts by `version`;
`create_snapshot` uses `1` if none exist yet, else `max(existing versions) + 1`. This is generation
order, not `captured_at` order — if a caller creates snapshots out of chronological order (unusual,
not prevented), `version` still reflects call order, not timestamp order. Documented, not silently
assumed away.

### IDs: `-`-separated, not `:`-separated

`snapshot_id = graph_id = f"{capture_id}-snapshot-{version}"`. This project's existing
`<capture_id>:<type>:<index>` convention (`Node`/`Edge`/`Flow` ids) uses `:` — but those ids are
only ever JSON field *values*, never a path component. `graph_id`/`snapshot_id` here are used
directly to build a filename (`topology_path`/`snapshot_path`), and `:` is invalid in a Windows
path — confirmed the hard way: an initial `:`-separated id crashed `write_json` with `OSError:
[Errno 22] Invalid argument` on Windows. `-` avoids the collision while staying readable.

### `read_snapshot_graph`: a small, reusable helper

`read_json(topology_path(root, capture_id, snapshot.graph_id), TopologyGraph)` in one line —
avoids repeated boilerplate at call sites and is directly reusable by Phase 45 (which will need to
fetch both graphs being diffed).

## Explicit non-goals this phase

- **No deduplication.** Every `create_snapshot` call creates a genuinely new version, even if
  nothing changed since the last one. The spec says "generate," not "generate only on change";
  detecting *whether* something changed is Phase 45's job (structural diffing) — building
  change-detection into the generator now would pre-empt it.
- **No API wiring.** There is no `/snapshots` route among Phase 09's 12 fixed endpoint groups at
  all (capture/flows/topology/behaviors/anomalies/history/dependencies/causal/simulation/
  counterfactual/experiments/metrics). `GET /history` is explicitly scoped to Phase 49 and returns
  `GraphChangeEvent` (Phase 45's schema), not raw snapshots. Mirrors FLOWMIND's long-established
  precedent (Phases 33-42) of real backend capability with no API wiring until a phase's own job is
  to add it.
- **Never raises for a missing/empty capture** — mirrors `build_topology_graph`'s own "empty graph,
  never an error" stance; produces a valid, empty-graph version-1 snapshot instead.

## Worked example

A capture with two time-separated episodes (A↔B at `t=0`, C↔D at `t=100s`), three snapshots taken
at increasing `captured_at`:

```
version=1 snapshot_id=cap-1-snapshot-1 captured_at=t-1s   nodes=0 edges=0
version=2 snapshot_id=cap-1-snapshot-2 captured_at=t+50s  nodes=2 edges=1
version=3 snapshot_id=cap-1-snapshot-3 captured_at=t+200s nodes=4 edges=2
```

## Verification actually performed this phase

- `pytest backend/tests/test_archaeology_snapshots.py -v` — **9/9 passed**: first snapshot for a
  fresh capture gets `version=1`, a second call gets `version=2`; the persisted graph and snapshot
  both round-trip byte-for-byte through `read_json`; `captured_at` genuinely bounds the graph
  (fewer nodes/edges at an earlier `captured_at`, using Phase 43's own two-episode fixture
  pattern); `list_snapshots` returns `[]` for no snapshots and orders existing ones by version;
  `read_snapshot_graph` returns the exact referenced graph; omitting `captured_at` defaults it to
  (approximately) "now"; two different `capture_id`s version independently, each starting at 1; a
  missing capture produces a valid empty-graph version-1 snapshot, never an error.
- Full repo suite (`pytest backend/tests experiments/tests simulator/tests`, run from repo root) —
  **357/357 passed** (up from 348/348), no regressions.
- `python -m scripts.validate_data_contracts` — 38/38 passed, no regression (no schema changes this
  phase — `NetworkSnapshot`/`TopologyGraph` untouched).
- `python -m scripts.check_ground_truth_boundary` — clean (the new `backend/archaeology/` package
  imports no `simulator.ground_truth`).
- A real, manual end-to-end run (no Docker needed): built the same synthetic two-episode capture,
  called `create_snapshot` three times at increasing `captured_at` values, and confirmed the
  printed version/node/edge output exactly matched this doc's worked example, plus `list_snapshots`
  correctly returning all three in order.

## Status

The network snapshot engine (spec Phase 44, FR-1.21's first half) is implemented and
unit-verified. `create_snapshot` produces real, versioned, persisted `NetworkSnapshot` records
whose graphs are genuinely bounded by their claimed capture time, reusing Phase 43's `as_of`
mechanism rather than duplicating any topology-reconstruction logic. No deduplication and no API
wiring exist yet — both explicitly out of this phase's scope, as detailed above. Structural diffing
between snapshots is explicitly Phase 45's job.
