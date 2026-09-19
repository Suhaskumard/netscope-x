# NETSCOPE-X — Historical Investigation Engine

Phase 49 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 49 — HISTORICAL
INVESTIGATION ENGINE"): "Support historical investigation queries (e.g., 'what changed between
time A and time B?'), returning structured results."

FR-1.24: *"The system shall support historical investigation queries (e.g., 'what changed between
time A and time B?') returning structured results (spec Phase 49)."*

Code: `backend/app/api/routes/history.py` (`GET /history`), wiring Phase 47's
`backend/archaeology/timeline.py::build_topology_event_timeline` to a real, paginated route. No new
module, no new schema.

## No new schema, no new query engine — this is a filter over Phase 47's existing stream

`GraphChangeEvent` (`backend/app/models/snapshot.py`, Phase 04/45/47/48) already carries everything
FR-1.24 asks a "structured result" to carry: `occurred_at`, `change_type`, `affected_node_id`/
`affected_edge_id`, `evidence`, and `affected_flow_ids`. `docs/architecture/topology_event_timeline.md`
(Phase 47) said it outright: *"No API wiring — that's explicitly Phase 49's job... this phase builds
the capability Phase 49 will later query (arbitrary `start`/`end` window filtering over exactly this
event stream)."* Phase 49 does exactly that and nothing more: no new inference, no new persistence
format, no new comparison logic.

## The route

```
GET /api/v1/history?capture_id=<id>&start=<datetime>&end=<datetime>&limit=<n>&offset=<n>
```

1. `settings = get_settings()`; `events = build_topology_event_timeline(settings.artifact_root, capture_id)`
   — same "recompute fresh and persist every call, not a cache" convention `GET /topology`/`GET
   /flows` already established, so a `/history` query always reflects the current snapshot set, not a
   stale read.
2. Filter to `start <= event.occurred_at <= end` — inclusive both ends, matching the spec's own
   phrasing ("between time A and time B").
3. Paginate with the existing `PageParams`/`PaginatedResponse`/`get_page_params` machinery
   (`backend/app/api/schemas.py`), the same slicing pattern `GET /flows` uses.

## Deliberate convention: unknown `capture_id` returns an empty 200, not a 404

`GET /flows` and `GET /topology` both 404 (`CaptureNotFoundError`) when `capture_id` has no ingested
`raw.pcap` — they do real per-request pcap processing, so a missing capture is a real error
condition. `GET /history` does not carry that check, for a specific reason: its backing call chain
(`build_topology_event_timeline` → `list_snapshots`) already belongs to the archaeology layer's
established "missing means empty" convention (`list_snapshots`'s own docstring: *"Returns `[]` for a
capture with no snapshots yet -- never an error"*). A `capture_id` with no snapshots yet and a
`capture_id` that was never ingested at all are indistinguishable at this layer, and both correctly
mean "nothing to report yet," not "malformed request." Adding a `pcap_path` existence check here
would mean re-introducing a distinction the layer underneath deliberately doesn't make — this route
stays consistent with what it's built on top of instead.

## No new tests for filtering logic itself — that's Phase 47's job, already covered

Whether `build_topology_event_timeline` computes the right events for a given snapshot set is
Phase 47's own concern, verified by `test_archaeology_timeline.py`'s 8 tests. Phase 49's own tests
(`backend/tests/test_api.py`) verify only the route's own added behavior: the empty-not-404
convention, `start`/`end` window inclusion/exclusion, and pagination — the same division of
responsibility Phase 32's `GET /topology` tests already used (route-level tests don't re-verify
`build_topology_graph`'s own node/edge discovery correctness).

## Worked example

Reusing the same two-episode capture (A↔B at `t=0`, C↔D at `t=100s`) and three-snapshot fixture from
Phase 47's own doc (snapshots at `t+10s`, `t+100s`, `t+200s`):

```
GET /api/v1/history?capture_id=cap-1&start=2026-01-01T00:00:00Z&end=2026-01-01T00:05:00Z

{
  "items": [
    {"change_type": "node_added", ...},
    {"change_type": "node_added", ...},
    {"change_type": "edge_added", ...}
  ],
  "limit": 50,
  "offset": 0,
  "total": 3
}
```

Narrowing `end` to before `t+100s` (before the second episode's snapshot pair) excludes all three
events — `total: 0`, `items: []` — confirming the window genuinely filters by `occurred_at`, not just
passing the full timeline through.

## Known limitations (inherited, not new)

- Same generation-order-vs-`captured_at`-order caveat Phase 47 already documented: under normal
  usage (snapshots created in capture order) these coincide; out-of-sequence snapshot generation is
  an existing, documented edge case this phase does not change.
- `NODE_REMOVED`/`EDGE_REMOVED` events remain practically vacuous under this system's cumulative,
  no-expiry topology reconstruction (Phase 45's own documented limitation) — a `/history` query over
  any window will essentially never surface one, not because of a bug in this phase.
- No causal or dependency reasoning is layered on top of the returned events — they are the same
  structural, evidence-only `GraphChangeEvent`s Phase 45/47/48 already produce; causal/dependency
  reasoning begins at Phase 50-56.

## Verification actually performed this phase

- `pytest backend/tests/test_api.py -v` — **32/32 passed**, including four new `GET /history` tests:
  an unknown `capture_id` returns `200` with `total: 0`/`items: []` (not a 404); a full window
  returns the real events a directly-called `build_topology_event_timeline` would produce; a narrow
  window before any snapshot pair correctly excludes every event; pagination (`limit`/`offset`) is
  honored and `total` reflects the pre-pagination window count. (The old generic 501 parametrization
  entry for `/history` was removed, so the raw count moved from the previous phase's tally by
  +4 tests -1 removed entry.)
- Full repo suite (`pytest backend/tests experiments/tests simulator/tests`, run from repo root) —
  **403/403 passed** (up from 400/400), no regressions.
- `python -m scripts.validate_data_contracts` — **38/38 passed**, no regression (no schema changes
  this phase).
- `python -m scripts.check_ground_truth_boundary` — clean.

## Status

The historical investigation engine (spec Phase 49, FR-1.24) is implemented and tested. `GET
/history` is now a real, routed endpoint filtering Phase 47's persisted `GraphChangeEvent` stream to
an arbitrary `[start, end]` window and paginating the result — no new schema, no new inference, pure
wiring over already-real, already-evidenced data. Dependency and causal reasoning (Phase 50-56) is
the next unimplemented layer.
