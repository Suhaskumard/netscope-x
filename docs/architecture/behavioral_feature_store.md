# NETSCOPE-X — Behavioral Feature Store

Phase 33 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 33 — BEHAVIORAL FEATURE
STORE"): "Create reusable behavioral feature representations." FR-1.12
(`docs/requirements/system_requirements.md`): "The system shall build reusable behavioral feature
representations per node (spec Phase 33) across short/medium/long observation windows (Phase 34)."

Code: `backend/flowmind/features/node_features.py`
(`compute_node_behavioral_features`/`NodeBehavioralFeatures`) — the first code in the new FLOWMIND
pipeline (`backend/flowmind/`, nested under `backend/` following the same deployment-boundary
convention already established for `backend/nettrace/` — see `docs/architecture/packet_capture.md`).
Populates no API route and persists nothing; this phase is a pure, tested computation library.

## Explicit non-scope: the Phase 33/34/35 boundary

FR-1.12's own phrasing splits three adjacent, easily-conflated phases:
- **Phase 33 (this phase)**: the generic, window-agnostic feature-*computation* function.
- **Phase 34** ("across short/medium/long observation windows", FR-1.12's own parenthetical, a
  separate phase): decides the three `ObservationWindow` boundaries and invokes this phase's function
  once per window.
- **Phase 35** (FR-1.13, "per-node behavioral fingerprints... spec Phase 35"): assembles Phase 34's
  per-window outputs into real `BehavioralFingerprint` instances (`backend/app/models/behavior.py`,
  Phase 04 — `node_id`, `window`, `computed_at` identity plus the feature fields) and persists them.

Phase 33 deliberately stops before any window-size decision or `BehavioralFingerprint` construction —
consistent with how every phase since Phase 29 has stayed narrowly scoped to its own spec-line wording
(Phase 29 nodes-only, Phase 30 edges-only, Phase 31 confidence-only, Phase 32 graph-assembly-only)
rather than reaching ahead into a later phase's job.

## Algorithm decision: the committed feature vocabulary

`docs/architecture/algorithm_selection.md` §2 (Role inference, Phase 05) already commits, ahead of
this phase, to the exact feature vocabulary a future Naive-Bayes-style role classifier (Phase 36-37)
will consume: "engineered behavioral features (port set entropy, protocol mix, traffic
directionality, persistence, destination diversity)." `NodeBehavioralFeatures`'s fields are chosen to
compute exactly these five families — no feature invented beyond what §2 already named:

| §2's vocabulary | `NodeBehavioralFeatures` field |
|---|---|
| Port set entropy | `distinct_ports` |
| Protocol mix | `distinct_protocols` |
| Traffic directionality | `outbound_byte_ratio` |
| Persistence | `is_persistent_talker` |
| Destination diversity | `distinct_destinations` |

(`mean_flow_duration_seconds` is an additional field already present on `BehavioralFingerprint` since
Phase 04 — computed here too, for the same reason: Phase 35's assembly should be a plain field copy,
not a translation. Field names were chosen to match `BehavioralFingerprint`'s own feature field names
exactly, a deliberate design choice for that reason.)

## Per-feature computation and rationale

- **`distinct_ports`** — sorted `dst_port` values from flows where the node is the *destination*
  only. A server's own listening-port set is real role signal (e.g. a database consistently contacted
  on 5432); a client's ephemeral source ports carry no role signal and would only inflate this set
  arbitrarily for any busy client, diluting exactly the "port set entropy" signal §2 names. Verified:
  `test_distinct_ports_only_counts_ports_where_node_is_destination`.
- **`distinct_protocols`** — the set of `Flow.protocol.value` across every touching flow, either
  direction — protocol mix is not a directional concept. Verified:
  `test_distinct_protocols_aggregates_across_both_directions`.
- **`distinct_destinations`** — count of distinct `dst_ip` values across flows where the node is the
  *source* — outbound fan-out. Inbound flows (this node as destination) aren't counted here — "how
  many distinct clients contact this node" is a different signal §2 doesn't name, and conflating the
  two would blur a client's fan-out behavior with a server's popularity. Verified:
  `test_distinct_destinations_only_counts_outbound_flows`.
- **`mean_flow_duration_seconds`** — mean of `Flow.features.duration_seconds` across every touching
  flow, either direction. Verified: `test_mean_flow_duration_seconds_averages_across_touching_flows`.
- **`outbound_byte_ratio`** — fraction of total bytes (summed across every touching flow) the node
  itself sent: `forward_byte_ratio * byte_count` when the node is the canonical source, or
  `(1 - forward_byte_ratio) * byte_count` when it's the canonical destination — real per-flow
  directionality data (Phase 23/28) reused, not re-derived. Verified with a hand-computed value
  (two flows, node as source in one and destination in the other):
  `test_outbound_byte_ratio_hand_computed`.
- **`is_persistent_talker`** — `True` if *any* touching flow has `features.is_persistent == True` —
  existence semantics, the same "any flow exhibits X" aggregation convention already established for
  Phase 31's noisy-OR edge-confidence signal indicators, and for the same reason: a fraction would
  dilute as unrelated (non-persistent) flows accumulate, which is the wrong direction for a signal
  that should only ever strengthen with more evidence. Verified:
  `test_is_persistent_talker_true_when_any_touching_flow_is_persistent`.
- **No touching flows** — every field returns its honest "no evidence" zero value (`[]`/`0`/`0.0`/
  `False`), never a fabricated default and never an exception. Verified:
  `test_node_with_no_touching_flows_returns_honest_zero_values`.

## Reusability across windows (Phase 34's future job)

The function filters `flows` only by "does this flow touch this node's IP addresses" — never by
time. `compute_node_behavioral_features(flows, node)` will be reusable, unmodified, once Phase 34
pre-filters a capture's flows to a short/medium/long window and calls this function once per window;
this phase does not decide or hardcode any window boundary.

## Complexity

O(F) for a single pass over F flows touching the node (the initial full-flows-list filter is O(N) over
the whole capture's N flows) — dominated by the flow scan, same shape as `discover_nodes`/
`discover_edges`.

## Failure cases

A node with zero touching flows: returns all-zero/empty values, never raises. Flows touching neither
of the node's addresses: silently excluded from every computed feature — verified directly:
`test_unrelated_flows_are_excluded_from_every_feature`.

## Known limitations

- No time-window logic — every feature is computed over whatever flows the caller passes in, with no
  window-boundary decision made here. That is explicitly Phase 34's job.
- No `BehavioralFingerprint` assembly or persistence — `NodeBehavioralFeatures` is an intermediate
  computation result, not the Phase 04 schema itself. That is explicitly Phase 35's job.
- `distinct_destinations`/`distinct_ports` don't yet account for a node with multiple IP addresses
  correlated together (Phase 29's "one IP → one Node" simplification still applies) — inherited, not
  introduced, by this phase.

## Verification actually performed this phase

- `pytest backend/tests/test_flowmind_node_features.py -v` — **9/9 passed**: `distinct_ports` only
  counting destination-side ports; `distinct_protocols` aggregating across both directions;
  `distinct_destinations` only counting outbound flows; `mean_flow_duration_seconds` correctly
  averaged; `outbound_byte_ratio` matching a hand-computed value (0.7) exactly; `is_persistent_talker`
  correctly false-then-true as persistent evidence is added; a zero-touching-flow node returning
  honest zero values; unrelated flows contributing nothing to any feature; a real end-to-end run
  seeding packets, running `reconstruct_flows` and `discover_nodes` for real, then computing features
  for a real discovered node with two real outbound flows (TCP and UDP), confirming
  `distinct_protocols`/`distinct_destinations` match the real reconstructed data.
- Full repo suite (`pytest`, run from repo root) — **257/257 passed** (up from 248/248), no
  regressions.
- `python -m scripts.validate_data_contracts` — 38/38 passed, no regression (`behavior.py`'s schemas
  unchanged; this phase populates no Pydantic model, only a plain dataclass).
- `python -m scripts.check_ground_truth_boundary` — clean: no import of `simulator.ground_truth`
  anywhere in `backend/flowmind/`.

## Status

The behavioral feature store (spec Phase 33, FR-1.12) is implemented and unit-verified:
`compute_node_behavioral_features` computes real, evidence-derived features for any node from any
caller-supplied flow list, covering exactly the feature vocabulary `algorithm_selection.md` §2 already
committed a future role classifier to. It is deliberately window-agnostic and produces no
`BehavioralFingerprint` — both are explicitly Phase 34 and Phase 35's jobs, not reached ahead of here.
