# NETSCOPE-X — Change Attribution

Phase 48 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 48 — CHANGE ATTRIBUTION"):
"Associate changes with: observation evidence, timestamps, affected flows, affected nodes. Do not
claim a causal explanation without sufficient evidence."

FR-1.23: *"The system shall attribute detected changes to observation evidence, timestamps, and
affected flows/nodes, and shall not claim a causal explanation without sufficient evidence (spec
Phase 48)."*

Code: `backend/archaeology/diff.py` (Phase 45's `diff_snapshots`, extended in place) + new
`backend/archaeology/attribution.py` (`format_change_attribution`, `format_timeline_attribution`).

## Three of the four named items were already real — the real gap was "affected flows"

`GraphChangeEvent` (`backend/app/models/snapshot.py`, Phase 04/45) already carried `occurred_at`
(timestamp), `affected_node_id`/`affected_edge_id`, and `evidence: List[str]` — and its `evidence`
field's own description already said *"Evidence tying this change to observations (spec Phase
48)"*, confirming this was always the intended extension point. What genuinely didn't exist
anywhere: a structured link from a change event to the concrete `Flow`s that support it. `Edge`
(`backend/app/models/topology.py`) has `evidence` too, but it's plain human-readable text
(`"flow <id>: TCP ..."`), not a queryable list of flow ids — no code anywhere could answer "which
flows caused this event" before this phase.

## Schema: extend `GraphChangeEvent`, don't invent a parallel one

Following the same precedent **Phase 40** already set (adding `total_byte_count` to
`NodeBehavioralFeatures`/`BehavioralFingerprint`/`NodeBehavioralBaseline` — a backward-compatible,
default-valued field on an earlier phase's schema once a later phase's requirement needed it),
`GraphChangeEvent` gains:

```python
affected_flow_ids: List[str] = Field(
    default_factory=list,
    description="Flow ids observationally supporting this change (spec Phase 48). Empty when no "
    "directly-attributable flow evidence exists, e.g. an ICMP-only node.",
)
```

A separate `ChangeAttribution` dataclass was considered and rejected: it would just duplicate
`event_id`/`occurred_at`/`affected_node_id`/`affected_edge_id` that already exist on
`GraphChangeEvent`. Extending the existing schema means `affected_flow_ids` flows through
Phase 47's already-persisted `topology_events.jsonl` automatically — no new artifact, no new I/O
path.

## Population: extend `diff_snapshots` in place, matched by node/edge IP set, bounded by `as_of`

`diff_snapshots` already builds `from_nodes`/`to_nodes` dicts by `node_id` for its set-comparison
logic. This phase adds one more read — `flows_path(root, capture_id)`, filtered to
`flow.first_seen <= to_snapshot.captured_at` (the same `as_of` bound Phase 43/44 already establish;
`captured_at` doubles as `as_of`, so attribution stays evidence-consistent with what the later
snapshot actually saw) — and two small matching helpers:

- **Node events**: `affected_flow_ids` = every flow whose `src_ip`/`dst_ip` is in the node's IP
  set (looked up in `to_nodes` for `NODE_ADDED`, `from_nodes` for `NODE_REMOVED`, since the node
  only definitely exists in one side for those change types).
- **Edge events** (added/removed/attribute-changed): `affected_flow_ids` = every flow connecting
  the edge's two nodes' IP sets, either direction.

Both are genuine recomputation from typed `Flow` objects, not string-parsing of `Edge.evidence`'s
human-readable text — consistent with this project's general preference for recomputing from
structured evidence over parsing another layer's presentation strings.

## Known, honest scope limitation: `ATTRIBUTE_CHANGED` attributes to the whole edge, not the delta

For an `ATTRIBUTE_CHANGED` event (e.g. an edge's `confidence` growing), `affected_flow_ids` lists
*every* flow supporting the edge as of the later snapshot — not only the specific new flow(s) that
drove that one attribute's change. Isolating that subset would require diffing flow-level
contributions between the two snapshots (which flows are in the `to` bucket but not the `from`
bucket), not attempted here. This mirrors Phase 30's own precedent: `Edge.evidence` was always
"every flow in the bucket," never "only the new ones" — Phase 48 keeps that same granularity for
consistency rather than quietly introducing a finer-grained (and more complex) semantic for this
one field alone.

## The causal-claim guard is structural, not a threshold

FR-1.23's second clause — "shall not claim a causal explanation without sufficient evidence" — has
no reusable mechanism anywhere in this system yet. `CausalEvidenceReport`
(`backend/app/models/dependency.py`) looks superficially similar (mandatory non-empty `evidence`/
`limitations`) but its own docstring scopes it to Phase 56, a genuinely different, much later
concern: dependency/causal claims between nodes ("A depends on B"), not attribution of a structural
topology change to its observations.

There is no causal-inference mechanism anywhere in this codebase yet (that begins at Phase 50-56).
So the only honest way to satisfy "do not claim a causal explanation" today is structural, not a
confidence threshold: `format_change_attribution` renders a **fixed, unconditional** disclaimer
sentence on every single report, with no code path that omits it and no evidence-sufficiency check
gating it on or off — because there is no causal claim anywhere for a threshold to gate. This
guarantees the clause holds by construction: not "we checked and decided this claim was
sufficiently supported," but "no such claim exists, and every report says so."

## Worked example

The same two-episode capture used throughout Phases 43-47, diffed between snapshots at `t+50s` and
`t+200s`, rendering the resulting `edge_added` event:

```
Change: edge_added (cap-1-snapshot-2:edge_added:cap-1:edge:1)
Occurred at: 2026-01-01T00:03:20+00:00
Affected edge: cap-1:edge:1
Observation evidence:
  - edge cap-1:edge:1 (cap-1:node:2<->cap-1:node:3) not present as of the earlier snapshot
Affected flows: cap-1:flow:1
This report attributes the change to concrete observations (evidence, timestamp, affected
flows/nodes) only. It is not, and does not claim to be, a causal explanation for why the
underlying traffic pattern changed.
```

## No API wiring, no new persistence

Same precedent as Phase 41/42/45/47: `format_change_attribution`/`format_timeline_attribution` are
pure, unpersisted rendering functions. `GET /history` remains Phase 49's untouched 501 stub.
`affected_flow_ids` reaches disk automatically via Phase 47's existing `topology_events.jsonl`
write path — no new artifact file was added this phase.

## Verification actually performed this phase

- `pytest backend/tests/test_archaeology_diff.py -v` — **14/14 passed** (10 existing + 4 new): a
  `NODE_ADDED` event's `affected_flow_ids` matches the real flows touching that node; an
  `EDGE_ADDED` event's matches the real flows connecting its two nodes; an `ATTRIBUTE_CHANGED`
  (confidence) event's matches every flow supporting the edge (the documented whole-edge
  granularity); an ICMP-only node's added event correctly gets `[]`, not a fabricated value.
- `pytest backend/tests/test_archaeology_attribution.py -v` — **9/9 passed**: change type/timestamp/
  affected node/edge/attribute/evidence/flow-ids all render correctly; an event with no
  attributable flows renders an honest "none directly attributable" line, never a fabricated flow
  id; the causal disclaimer is present in every report across all five `ChangeType` values, with no
  exceptions; a multi-event timeline renders in order with one disclaimer per event; an empty
  timeline renders an empty string, never an error.
- Full repo suite (`pytest backend/tests experiments/tests simulator/tests`, run from repo root) —
  **400/400 passed** (up from 387/387), no regressions.
- `python -m scripts.validate_data_contracts` — 38/38 passed, no regression (the new
  `affected_flow_ids` field is optional/default-valued; existing valid/invalid `GraphChangeEvent`
  fixtures in the script were unaffected).
- `python -m scripts.check_ground_truth_boundary` — clean.
- A real, manual end-to-end run (no Docker needed): rebuilt the same two-episode capture, created
  two snapshots, diffed them, and confirmed the printed `edge_added` event's `affected_flow_ids`
  and its rendered report exactly matched this doc's worked example.

## Status

Change attribution (spec Phase 48, FR-1.23) is implemented and unit-verified.
`GraphChangeEvent.affected_flow_ids` closes the one real gap in FR-1.23's four named attribution
items; `format_change_attribution`/`format_timeline_attribution` render every change with its full
observation evidence, timestamp, affected node/edge, and affected flows, always paired with a
structural, unconditional non-causal disclaimer. No API wiring or new persistence exists yet — `GET
/history` (Phase 49) will be the natural consumer of exactly this data.
