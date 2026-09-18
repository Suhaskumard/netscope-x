# NETSCOPE-X — Node Behavioral Fingerprints

Phase 35 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 35 — NODE BEHAVIORAL
FINGERPRINTS"): "Generate fingerprints from: traffic, ports, protocols, timing, destinations,
directionality, persistence." FR-1.13 (`docs/requirements/system_requirements.md`): "The system shall
generate per-node behavioral fingerprints from traffic, ports, protocols, timing, destinations,
directionality, and persistence (spec Phase 35)." No persistence requirement, window-count, or
API-exposure language appears in the FR text itself — all of that is this phase's own design latitude.

Code: `backend/flowmind/fingerprints/node_fingerprint.py`
(`assemble_node_fingerprint`/`assemble_all_node_fingerprints`) — the first code to populate
`backend/app/models/behavior.py`'s `BehavioralFingerprint` schema with real data.

## Why `GET /behaviors/{node_id}` stays unwired this phase — a structural constraint, not a preference

`backend/app/api/routes/behaviors.py`'s route contract was fixed back in Phase 09:
```python
class NodeBehavior(BaseModel):
    fingerprint: BehavioralFingerprint
    role: RoleClassification

@router.get("/{node_id}", response_model=NodeBehavior)
```
Both fields are required. `role: RoleClassification` is explicitly Phase 36-37's job (service role
inference) — nothing computes a real `RoleClassification` yet. Wiring this route now would mean either
fabricating a role (a hardcoded/fake classification dressed as real output, forbidden by this
project's own "no fake metrics" and "no premature completion" rules) or changing the Phase-09-fixed
response schema without a documented reason. Neither is acceptable, so `GET /behaviors/{node_id}`
remains a 501 stub, same status as before this phase. This is a structural fact about the route's own
contract, not a scope judgment call — the same reasoning that kept `GET /topology` a stub through
Phases 29-31 until Phase 32 could actually assemble a complete `TopologyGraph`.

## Design

### Field-copy assembly

`assemble_node_fingerprint(flows, node, window, window_seconds=None, computed_at=None)` calls Phase
34's `compute_node_features_for_window`, then constructs a real `BehavioralFingerprint` by copying its
six feature fields verbatim (`**asdict(features)`) alongside the three identity fields
(`node_id`/`window`/`computed_at`) the intermediate `NodeBehavioralFeatures` dataclass deliberately
lacked. This is the "trivial field copy" both Phase 33 and Phase 34's own docs already promised — no
new feature computation happens in this module, confirmed directly by
`test_assemble_node_fingerprint_matches_computed_features_exactly` asserting byte-for-byte equality
against `compute_node_features_for_window`'s own output.

### All three windows, not one

`assemble_all_node_fingerprints(flows, nodes, window_seconds=None, computed_at=None)` produces one
`BehavioralFingerprint` per node **per window** — all three `ObservationWindow` values, not a single
default. Phase 34's own deliverable was explicitly "per-window results" (plural); nothing in FR-1.13
or `algorithm_selection.md` §2 ("infer a probability distribution over service roles... from **its**
behavioral fingerprint") forecloses keeping all three, and narrowing to one window now would discard
real, already-computed data for no stated reason. Later phases (39's concept-drift detection
comparing recent vs. longer-term behavior; 36-37's classifier, which may eventually want more than
one window) can reasonably use more than a single window's fingerprint — keeping all three preserves
that option rather than foreclosing it.

### Shared `computed_at` per batch

Every fingerprint produced by one `assemble_all_node_fingerprints` call shares a single `computed_at`
timestamp — real batch-generation semantics (all output from the same assembly run is stamped as of
the same moment), not per-fingerprint clock skew that would make otherwise-simultaneous fingerprints
look artificially staggered. Verified: `test_assemble_all_node_fingerprints_shares_one_computed_at`.

### Persistence

New `experiments/artifacts/paths.py::fingerprints_path(root, capture_id) -> Path`
(`captures/<capture_id>/fingerprints.jsonl`), using the existing generic `write_jsonl`/`read_jsonl`
(Phase 10 primitives) — no new I/O code. A JSON-Lines collection fits "many fingerprints in one file"
better than `TopologyGraph`'s single-object `write_json` shape (Phase 32 precedent). Round-trip
verified: `test_fingerprints_round_trip_through_jsonl`.

## Algorithm / complexity

O(N·3·F) for N nodes, F flows touching each node on average — three window computations per node,
each O(F) per Phase 34's own complexity note. Dominated by the flow scan, same shape as every prior
FLOWMIND function.

## Failure cases

Zero nodes: `assemble_all_node_fingerprints` returns `[]`, never raises. A node with no touching flows
in a given window: the underlying `NodeBehavioralFeatures` is the honest all-zero result Phase 33
already defines — still a valid, schema-passing `BehavioralFingerprint`, not an error.

## Known limitations

- No role inference — `RoleClassification` remains Phase 36-37's job.
- No API exposure — `GET /behaviors/{node_id}` stays a 501 stub until Phase 37 can fill in `role`.
- Inherits every upstream limitation already documented in `node_discovery.md`,
  `behavioral_feature_store.md`, and `multi_window_behavior_modeling.md` (one-IP-per-node,
  destination-only port/diversity conventions, the unvalidated `long` window duration).

## Verification actually performed this phase

- `pytest backend/tests/test_flowmind_fingerprints.py -v` — **7/7 passed**: assembled fingerprint
  fields match `compute_node_features_for_window`'s own output exactly; identity fields
  (`node_id`/`window`/`computed_at`) set correctly, with `computed_at` bounded by real
  before/after timestamps; a 2-node batch produces exactly 6 fingerprints (2 nodes × 3 windows) with
  every node covering all three windows; every fingerprint in one batch call shares one `computed_at`;
  zero nodes returns `[]`; fingerprints round-trip through `write_jsonl`/`read_jsonl` byte-for-byte
  equal; a real end-to-end run through `reconstruct_flows`/`discover_nodes` producing
  `len(nodes) * 3` valid `BehavioralFingerprint` instances, each with `outbound_byte_ratio` confirmed
  in `[0, 1]`.
- Full repo suite (`pytest`, run from repo root) — **272/272 passed** (up from 265/265), no
  regressions.
- `python -m scripts.validate_data_contracts` — 38/38 passed, no regression (`BehavioralFingerprint`
  schema unchanged since Phase 04; this phase populates it, doesn't modify it).
- `python -m scripts.check_ground_truth_boundary` — clean.

## Status

Node behavioral fingerprint assembly (spec Phase 35, FR-1.13) is implemented and unit-verified: real
`BehavioralFingerprint` instances, for every node and every observation window, assembled from
Phase 33-34's already-real feature computations with zero new feature math and a documented,
tested persistence shape. `GET /behaviors/{node_id}` remains a 501 stub — a structural consequence of
its Phase-09-fixed contract needing `RoleClassification`, not a scope choice this phase made.
