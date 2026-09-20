# NETSCOPE-X — Digital Twin Model

Phase 57 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 57 — DIGITAL TWIN MODEL"):
"Build a computational digital twin combining topology, behavior, history, dependencies, routing,
and state."

FR-1.31 (first half): *"The system shall build a computational digital twin combining topology,
behavior, history, dependencies, routing, and state (spec Phase 57), kept synchronized with new
observations... (spec Phase 58)."* This phase covers the first half only — the static assembly.
Synchronization from new observations is Phase 58's job.

Code: new `backend/digital_twin/twin.py` (`DigitalTwin`, `build_digital_twin`) — the first code in
a new spec section ("Digital Twin, Simulation, and Counterfactuals").

## An assembly phase, not new inference

Matching this project's consistent pattern whenever a phase says "combine X, Y, Z" (Phase 32's
`build_topology_graph`, Phase 47's `build_topology_event_timeline`), `build_digital_twin` computes
nothing new. Each of the six named dimensions already has a real, already-built source, reused
directly:

- **Topology** → Phase 32's `TopologyGraph`, fetched via Phase 44's `read_snapshot_graph` — the
  graph the anchoring snapshot already references, not recomputed.
- **Behavior** → Phase 35's `BehavioralFingerprint`s, caller-supplied. Mirrors Phase 46's own
  established precedent: no persisted, queryable fingerprint history exists anywhere in this repo
  (Phase 35's `fingerprints.jsonl` is overwrite-only), so there is nothing to auto-fetch from.
  Defaults to `[]` when omitted.
- **History** → Phase 47's `build_topology_event_timeline`, filtered to events at or before the
  anchoring snapshot's `captured_at` — a twin anchored at an earlier point never includes future
  events it couldn't have known about. Exact, because `GraphChangeEvent.occurred_at` is already
  defined as `to_snapshot.captured_at` (Phase 45).
- **Dependencies** → Phase 51-53's `estimate_dependency_strength`, called with
  `as_of=snapshot.captured_at` (Phase 43's own mechanism, already threaded through this function
  since Phase 51/52).
- **Routing** → no separate field or new computation. `algorithm_selection.md` §5 already selected
  Dijkstra/Yen's/BFS for real path analysis, explicitly Phase 60's job ("Dynamic Path Engine"). At
  this stage, routing is honestly represented by the topology graph's own edges (what can reach
  what) — a deliberate, documented simplification, not glossed over.
- **State** → the anchoring `NetworkSnapshot` itself, not a separate field. Confirmed, not assumed:
  `backend/app/models/simulation.py`'s `SimulationRun` (Phase 04, docstring-tagged "spec Phase
  57-58, 61") has `twin_snapshot_id: str` — "Digital twin state the simulation ran against" — the
  schema itself already encodes "the twin's state = a `NetworkSnapshot`."

No new Pydantic schema — nothing in `backend/app/models/` reserves one for "DigitalTwin" itself,
following the precedent already set by Phase 32/37/42/46/53/55's own evaluation/assembly-style
outputs (a plain frozen dataclass, `DigitalTwin`).

Never imports `simulator.ground_truth` (spec §4; `scripts/check_ground_truth_boundary.py` would
reject it if it did).

## `build_digital_twin(root, capture_id, snapshot, behavioral_fingerprints=None, ...)`

`snapshot` is not validated as genuinely belonging to `capture_id` — no `capture_id` field exists
on `NetworkSnapshot` itself, and a mismatched pair fails naturally via `read_snapshot_graph`'s own
file lookup, the same convention Phase 45's `diff_snapshots` already established.

A missing/unknown `capture_id` produces an empty-but-valid twin (empty topology, dependencies,
history, fingerprints), not an error — the archaeology layer's own established "missing means
empty" convention (Phase 44/47/49), not a special case added here.

Edge-confidence and dependency-scoring constants (`edge_confidence_packet_scale`,
`dependency_frequency_scale`, etc.) are accepted as keyword overrides with the same
provisional/uncalibrated defaults already established in Phase 30-31/51/52 — passed straight
through to `estimate_dependency_strength`, not re-declared or re-tuned here.

## No API wiring this phase

No route in the fixed Phase 09 12-endpoint surface names a twin resource. Consistent with the
"assembly phase, no route" precedent Phase 32/46/55 already set — a route only appears once a
later phase's spec explicitly calls for one (simulation-related routes are scoped to Phase 59-61).

## Worked example

The same two-episode fixture Phase 43-47's own tests use (A↔B at t=0, C↔D at t=100s):

```
twin = build_digital_twin(root, "cap-1", snapshot_at_t50)
# topology nodes: {10.0.0.1, 10.0.0.2}   (episode 2 hasn't happened yet)
# dependencies:   1                       (A<->B only)
# history:        events up to and including t=50s only

twin = build_digital_twin(root, "cap-1", snapshot_at_t200)
# topology nodes: {10.0.0.1, 10.0.0.2, 10.0.0.3, 10.0.0.4}
# dependencies:   2
# history:        events up to and including t=200s
```

`twin.topology == read_snapshot_graph(root, capture_id, snapshot)` exactly — the twin's topology
is not a separate recomputation, confirmed directly.

## Verification actually performed this phase

- `pytest backend/tests/test_digital_twin.py -v` — **9/9 passed**: an earlier-anchored twin shows
  only the first episode's topology/dependencies; a later-anchored twin shows both; history is
  correctly filtered to events at or before the anchoring snapshot, and strictly grows between two
  later anchors; `twin.topology` matches `read_snapshot_graph` called directly, byte for byte;
  caller-supplied fingerprints pass through unchanged (identity-preserved, not copied); a missing
  capture produces an empty, not erroring, twin; `generated_at` is a real, distinct wall-clock
  timestamp, not copied from `snapshot.captured_at`; two calls against identical inputs produce
  identical topology/dependencies/history (deterministic); a real end-to-end run through
  `discover_nodes` → `reconstruct_flows` → `assemble_node_fingerprint` → `build_digital_twin`
  confirms every dependency's endpoints are genuine topology node ids.
- Full repo suite (`pytest backend/tests experiments/tests simulator/tests`, run from repo root) —
  **476/476 passed** (up from 467/467), no regressions.
- `python -m scripts.validate_data_contracts` — 38/38 passed, no regression (no schema changes this
  phase).
- `python -m scripts.check_ground_truth_boundary` — clean.

## Status

The digital twin model (spec Phase 57, FR-1.31 first half) is implemented and unit-verified:
`build_digital_twin` assembles topology, behavior, history, and dependencies from already-real
Phase 32/35/44/45/47/51-53 machinery, with routing and state represented honestly by the topology
graph and anchoring snapshot rather than by new, unbuilt fields. No API route exists yet — nothing
in the fixed Phase 09 surface calls for one. Synchronization from new observations (Phase 58),
failure injection (Phase 59), the dynamic path engine (Phase 60), and counterfactuals (Phase 64-66)
remain ahead.
