# NETSCOPE-X — Dependency Strength

Phase 51 deliverable. FR-1.26: *"The system shall estimate dependency strength from frequency,
persistence, directionality, temporal relationships, and traffic characteristics (spec Phase 51)."*

Code: new `backend/dependency/strength.py` (`estimate_dependency_strength`), wiring
`GET /dependencies` (`backend/app/api/routes/dependencies.py`) for real; a small, behavior-preserving
refactor of `backend/nettrace/topology/edges.py` (`bucket_flows_by_node_pair`, extracted from
`discover_edges`); three new `Settings` fields (`backend/app/core/config.py`).

## Scope boundary: four of five signals, not all five

FR-1.26 names five signals. `docs/architecture/algorithm_selection.md` section 6 already draws the
line for which phase owns which, parenthesizing temporal relationships as "spec Phase 52" in the
very sentence describing the combined scoring function. `DependencyEdge.temporal_precedence_score`
(`backend/app/models/dependency.py`) already has `default=0.0`, docstring-tagged "spec Phase 52" —
this phase constructs every `DependencyEdge` without ever setting it. The remaining four —
frequency, persistence, directionality, traffic characteristics — are this phase's job.

## No new evidence — every signal reuses something already real

- **Frequency, persistence**: Phase 50's `derive_communication_relationships`
  (`backend/dependency/communication.py`), called unmodified. Its documented zero-duration
  `frequency` fallback (raw `observation_count` when `persistence_seconds == 0`) flows straight
  through.
- **Directionality**: `_bidirectionality(forward_byte_ratio)` (Phase 30-31, `edges.py`) measures
  "genuine two-way traffic" (1.0 = balanced, 0.0 = one-way) — the *inverse* of what
  `DependencyEdge.directionality_score` means ("1.0 = fully one-way," per its own docstring).
  `directionality_score = 1 - _bidirectionality(mean_ratio)`, where `mean_ratio` is the mean
  `forward_byte_ratio` across a node pair's bucketed flows — reusing the exact helper, inverted, not
  a new formula.
- **Traffic characteristics**: `Edge.confidence` (Phase 31) is already a real, evidence-backed
  combination of exactly this signal family (TCP handshake completion, protocol fingerprinting, TLS
  negotiation, five-tuple persistence, bidirectionality). Reused directly as the traffic-
  characteristics input to strength, rather than re-deriving the same signals under a new name.

## The one refactor: extracting `bucket_flows_by_node_pair`

Computing directionality needs the same per-node-pair flow buckets `discover_edges` already builds
internally, but had no way to return. Following the "extend an earlier phase's function in place
once a later phase's requirement needs it" precedent (Phase 40 extending schemas, Phase 48 extending
`diff_snapshots`), the bucketing loop was extracted into its own function,
`bucket_flows_by_node_pair(root, capture_id, nodes, as_of=None)`, in `edges.py`.  `discover_edges`
now calls it internally; its own signature, return type, and behavior are completely unchanged —
verified by re-running the full edge/topology/API suite unchanged before writing any new code.

## The combination formula: mirrors Phase 31's noisy-OR exactly

```
p_frequency   = 1 - exp(-frequency / dependency_frequency_scale)
p_persistence = 1 - exp(-persistence_seconds / dependency_persistence_scale)

survival = (1 - p_frequency)
         * (1 - dependency_signal_strength * p_persistence)
         * (1 - dependency_signal_strength * directionality_score)
         * (1 - dependency_signal_strength * edge.confidence)   # traffic characteristics

strength = 1 - survival
```

One primary saturating term (frequency) at full weight, three secondary signals (persistence,
directionality, traffic characteristics) each scaled by one shared, uniformly-applied
`dependency_signal_strength` constant — the identical shape `_confidence` (Phase 31) already uses
for `Edge.confidence`, for the identical reason: no empirical basis yet justifies weighting one
signal above another (that's Phase 68's job, not invented here). Three new `Settings` fields
(`dependency_frequency_scale=1.0`, `dependency_persistence_scale=60.0`,
`dependency_signal_strength=0.3`) carry the same "provisional default pending real calibration,
spec Phase 68, not a claimed-accurate value" language as `edge_confidence_packet_scale`/
`edge_confidence_signal_strength` already do.

Like `Edge.confidence`, `strength` is bounded in `[0, 1]` by construction (each survival factor is
non-negative), asymptotically approaching but not exceeding `1.0` as evidence accumulates —
floating-point underflow in `exp()` for very large `frequency`/`persistence_seconds` relative to
their scales can compute exactly `1.0` (the schema's `le=1` already allows this, and `Edge.confidence`
carries the identical asymptotic caveat), not a bug.

## Reordering invariant: `edges[i]` and `relationships[i]` are the same pair

`estimate_dependency_strength` calls `discover_nodes`, `discover_edges`,
`derive_communication_relationships`, and `bucket_flows_by_node_pair` over the identical
`(root, capture_id, as_of, edge_confidence_packet_scale, edge_confidence_signal_strength)` inputs.
Since `discover_edges` and `derive_communication_relationships` (which itself calls `discover_edges`
with the same inputs) are pure, deterministic functions of the same underlying flow data, their
outputs are index-aligned — `edges[i]` and `relationships[i]` always refer to the same node pair in
the same order. This is relied on directly (`zip(edges, relationships)`), documented as an explicit
invariant rather than re-matched through a separate lookup.

## `GET /dependencies` is now real

Unlike Phase 50 (which deliberately left this route untouched), this route's own docstring already
named itself *"Backing implementation: spec Phase 51"*. It now calls `estimate_dependency_strength`
with every scale/strength constant pulled from `Settings`, then paginates with the existing
`PageParams`/`PaginatedResponse` machinery (`GET /flows`'s pattern). Same "missing means empty"
convention as `GET /history`/Phase 50: an unrecognized `capture_id` returns an empty, still-200
paginated result, not a 404 — there's no per-request pcap-existence check here, consistent with the
rest of this dependency-inference layer.

## Known, honest limitation (inherited from `algorithm_selection.md` §6, not new)

A high-frequency, persistent, one-directional but coincidental communication pattern (e.g. a
health-check poller) can score a falsely high `strength` — the expected failure mode RQ5's Phase 68
evaluation (precision/recall against ground-truth dependency edges) is designed to measure, not
eliminate by construction.

## Verification actually performed this phase

- `pytest backend/tests -k "edges or topology"` — full pass, confirming `bucket_flows_by_node_pair`'s
  extraction changed nothing observable in `discover_edges`.
- `pytest backend/tests/test_dependency_strength.py -v` — **7/7 passed**: empty capture returns
  `[]`; a single exchange's `DependencyEdge` matches hand-computed `frequency`/`persistence_seconds`/
  `directionality_score`/`strength` exactly, with `temporal_precedence_score` always `0.0`; two
  independent episodes produce two distinct dependency edges; `as_of` bounding excludes later
  communication; one-way traffic scores near-maximal directionality, balanced traffic scores
  near-minimal directionality; a missing capture never raises.
- `pytest backend/tests/test_api.py -v` — full pass, including 3 new `GET /dependencies` tests
  (unknown capture returns `200`/empty, not `404`; a real ingested two-flow capture returns 2 real
  `DependencyEdge`s with valid bounded fields; pagination `limit`/`offset` honored).
- Full repo suite (`pytest backend/tests experiments/tests simulator/tests`) — **419/419 passed**
  (up from 410/410), no regressions.
- `python -m scripts.validate_data_contracts` — **38/38 passed**, no regression (no schema changes
  this phase; `DependencyEdge` was already validated there since Phase 04).
- `python -m scripts.check_ground_truth_boundary` — clean.

## Status

Dependency strength estimation (spec Phase 51, FR-1.26) is implemented and tested. `GET
/dependencies` is now real, producing `DependencyEdge`s whose `strength`/`directionality_score` are
computed from frequency, persistence, directionality, and traffic characteristics over Phase 50's
`CommunicationRelationship`s and Phase 31's already-inferred `Edge` evidence — no new signal
invented, no temporal-precedence claim made. **Update (Phase 52):** temporal precedence is no
longer unimplemented — `estimate_dependency_strength` now also calls Phase 52's
`estimate_temporal_precedence` (`backend/dependency/temporal_precedence.py`) and folds it into the
noisy-OR formula as a fourth secondary term, so `strength`/`temporal_precedence_score` together now
reflect all five of FR-1.26's named signals. See `docs/architecture/temporal_precedence_analysis.md`
for the full design.
