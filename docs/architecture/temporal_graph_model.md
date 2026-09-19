# NETSCOPE-X — Temporal Graph Model

Phase 43 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 43 — TEMPORAL GRAPH MODEL"):
"Represent network as: G(t) instead of only a static graph."

FR-1.20: *"The system shall represent the network as a time-indexed graph G(t), not only a static
snapshot (spec Phase 43)."* This is the first phase of a new spec section, "Temporal Intelligence
(Network Archaeology)" (FR-1.20-1.24, Phases 43-49).

Code: `backend/nettrace/topology/{discovery,edges,graph}.py` (Phase 29-32's own files, extended in
place with a new `as_of` parameter — not new functions, not a new module).

## Scope boundary against Phase 44/45 (the real design decision)

`backend/app/models/snapshot.py`'s own docstring already attributes `NetworkSnapshot` specifically
to *"(spec Phase 44)"* — "Generate versioned network snapshots" — and `GraphChangeEvent` to
*"(spec Phase 45, 47-48)"*. Neither is this phase's deliverable. RQ4
(`docs/research/research_questions.md`) confirms the same split: "time between snapshots" and a
"ground-truth topology-event timeline" are Phase 44/45/47 concerns. So Phase 43 is narrowly about
the *representation/query capability* — making topology reconstruction a genuine function of time —
not about persisting numbered/versioned snapshots (Phase 44) or diffing between them (Phase 45).
Building either of those now would be doing a later phase's job early, which this project
consistently avoids (Phase 30 didn't attempt Phase 31's confidence calibration; Phase 33 didn't
attempt Phase 34's windowing).

## Why no new `archaeology/` package this phase

`docs/PROJECT_STATE.md`'s architecture-decisions log lists `backend/archaeology/` as intentionally
not-yet-created, "justified once the phases that populate them are reached." Phase 43's real,
honestly-scoped deliverable — making topology reconstruction time-aware — fits as a direct, minimal
extension of `backend/nettrace/topology/{discovery,edges,graph}.py`, the same "add a new optional,
backward-compatible parameter" pattern already used repeatedly in this project (Phase 25's
`udp_session_idle_timeout_seconds`, Phase 31's confidence signals, Phase 40's `total_byte_count`).
`backend/archaeology/` will be justified for real starting Phase 44, when `NetworkSnapshot`
persistence needs a genuine new home with no natural fit in `nettrace/`. This is an intentional,
explained departure from the "first phase of a section gets its own package" pattern (Phase 21's
`nettrace/`, Phase 33's `flowmind/`), not a silent inconsistency.

## Design: recompute, not filter

An alternative, cheaper design would take an already-built (whole-capture) `TopologyGraph` and
filter its `nodes`/`edges` lists down to `first_observed <= as_of`. Rejected: an edge's
`confidence`/`evidence`/`observation_count` are themselves computed from *all* its contributing
flows — filtering the edge list without re-aggregating would report full-capture confidence for
the trimmed graph, silently overstating certainty at time `t`. Since `discover_edges`'s confidence
formula (Phase 31) is monotonic in evidence by construction, genuinely recomputing from
time-bounded flows means confidence can legitimately *grow* between two `as_of` values — a real,
meaningful signal a future snapshot-diffing phase will want, not available from post-hoc filtering.

## Implementation

All three functions gained an optional `as_of: Optional[datetime] = None` parameter; `None`
preserves the exact prior behavior (every pre-existing test passes unmodified):

- **`discover_nodes(root, capture_id, as_of=None)`**: filters `packets` to `timestamp <= as_of`
  before the existing first/last-observed aggregation loop. A node whose only evidence is later
  than `as_of` is simply never produced.
- **`discover_edges(root, capture_id, nodes, ..., as_of=None)`**: filters `flows` to
  `first_seen <= as_of` before bucketing — the identical inclusion rule `discover_nodes` applies to
  packets, so a node and an edge agree on what "existed as of `as_of`" means. `nodes` remains
  caller-supplied; a caller passes the *same* `as_of`-filtered node list from `discover_nodes` so
  both stay evidence-consistent.
- **`build_topology_graph(root, capture_id, graph_id, ..., as_of=None)`**: threads `as_of` into
  both calls above. `generated_at` stays `datetime.now(timezone.utc)` — "when this computation
  ran," unchanged meaning. `TopologyGraph` (Phase 04) carries no "this represents time t" field of
  its own by design; that label is `NetworkSnapshot.captured_at`'s job (Phase 44).

`build_topology_graph(root, capture_id, graph_id, as_of=t)` is, literally, `G(t)`.

## No API/persistence wiring this phase

`GET /topology` (`backend/app/api/routes/topology.py`) is untouched — no new `as_of` query
parameter. That route's `graph_id = capture_id` identity/persistence scheme has no way to represent
multiple distinct `as_of` values for one capture without collision, and giving each time-bounded
graph a stable identity is precisely `NetworkSnapshot`'s job (Phase 44). Wiring an API parameter now
would mean improvising part of Phase 44's job with the wrong tool. This mirrors FLOWMIND's own
precedent (Phases 33-42 built substantial real capability with zero API wiring, deferred until a
persistence layer existed).

## Worked example

A capture with two time-separated communication episodes — A↔B at `t=0`, C↔D at `t=100s`:

```
as_of = t-1s   (before both):  nodes=[],                          edges=0
as_of = t+50s  (between):      nodes=[A, B],                      edges=1
as_of = t+200s (after both):   nodes=[A, B, C, D],                 edges=2
as_of = None   (unbounded):    nodes=[A, B, C, D],                 edges=2  (identical to "after both")
```

## Known limitations

- **Confidence is recomputed, not tracked incrementally** — each `as_of` call re-reads and
  re-aggregates from scratch; there is no incremental/streaming update path (not needed yet at this
  data scale, and no requirement asks for one).
- **No versioned identity or persistence** — a time-bounded `TopologyGraph` has no stable id
  distinguishing it from another `as_of` value for the same capture; that's explicitly Phase 44's
  "versioned network snapshots" job.
- **No diffing** — comparing two `as_of` results structurally (what changed between them) is
  explicitly Phase 45's job (`GraphChangeEvent`, already reserved since Phase 04).
- **`as_of` inclusion is `<=`, not a window** — this answers "what existed by time t," not "what
  was active during interval [t1, t2)"; a windowed variant is a plausible future enhancement, not
  attempted here (NFR-9).

## Verification actually performed this phase

- `pytest backend/tests/test_nettrace_topology_discovery.py -v` — grew from 8/8 to 12/12 (4 new: a
  node whose only packet is after `as_of` is excluded; `as_of` exactly equal to a packet's
  timestamp includes it; `last_observed` correctly narrows to the latest packet at or before
  `as_of`; `as_of=None` matches the unbounded call byte-for-byte).
- `pytest backend/tests/test_nettrace_topology_edges.py -v` — grew from 20/20 to 23/23 (3 new: a
  flow starting after `as_of` is excluded from its bucket, changing edge count/protocols; a
  bucket's confidence at an earlier `as_of` is `<=` its confidence once later flows are also
  visible, and matches the fully-unbounded call exactly once all flows are included — the direct
  demonstration of why this phase recomputes rather than filters; `as_of=None` matches the
  unbounded call).
- New `backend/tests/test_nettrace_topology_graph.py` (6/6, the first dedicated unit-test file for
  `build_topology_graph` itself): before/between/after a two-episode synthetic capture produce
  correctly-scoped graphs; node/edge counts grow monotonically across three `as_of` points; omitting
  `as_of`, passing `as_of=None` explicitly, and passing a far-future `as_of` all agree exactly;
  a missing capture returns an empty graph regardless of `as_of`.
- Full repo suite (`pytest backend/tests experiments/tests simulator/tests`, run from repo root) —
  **348/348 passed** (up from 335/335), no regressions.
- `python -m scripts.validate_data_contracts` — 38/38 passed, no regression (no schema changes this
  phase).
- `python -m scripts.check_ground_truth_boundary` — clean.
- A real, manual end-to-end run (no Docker needed): built a synthetic capture with two
  time-separated episodes (A↔B at `t=0`, C↔D at `t=100s`), called `build_topology_graph` at four
  `as_of` points, and confirmed the printed node/edge/confidence output exactly matched this doc's
  worked example — the topology genuinely grows over time and the unbounded case is reproduced
  exactly when `as_of` is omitted.

## Status

The temporal graph model (spec Phase 43, FR-1.20) is implemented and unit-verified:
`build_topology_graph`/`discover_nodes`/`discover_edges` are now genuinely time-indexed functions,
`G(t)`, via a backward-compatible `as_of` parameter — no existing behavior changed when it's
omitted. No versioned snapshot persistence or structural diffing exists yet; both are explicitly
Phase 44/45's job. No new package was created — `backend/archaeology/` remains justified for a
later phase, per this doc's own explanation above.
