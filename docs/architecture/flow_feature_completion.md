# NETSCOPE-X — Flow Feature Completion

Phase 28 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 28 — FLOW FEATURE COMPLETION").
FR-1.8 (`docs/requirements/system_requirements.md`): "The system shall compute per-flow features:
packet/byte statistics, duration, burstiness, directionality, destination/port diversity, connection
persistence." Phase 23 (`docs/architecture/flow_reconstruction.md`) computed every statistic that a
single flow's own packets are sufficient for (packet/byte counts, duration, mean inter-arrival,
`forward_byte_ratio`, burstiness) and left `destination_diversity`, `port_diversity`, and
`is_persistent` as honest, documented placeholders (`1`, `1`, `False`) because their real meaning
requires information from *other* flows in the same capture. Code: `backend/nettrace/reconstruct.py`
(`reconstruct_flows`, `_compute_features`). `GET /flows` needs no route changes — it already
recomputes flows fresh from `reconstruct_flows` on every request.

## Algorithm

`reconstruct_flows` was a single pass over each unit (a TCP five-tuple group, or one of Phase 25's
UDP idle-timeout sessions): resolve direction, compute TCP state/fingerprint/TLS version, compute
features, build the `Flow`. That single-pass structure could never support Phase 28's fields, because
they depend on *other* units elsewhere in the same capture — you can't know how many distinct
destinations a source IP talked to, or whether a five-tuple recurred, until every unit has been seen.

The function is now two passes over `ordered_groups`:

- **Pass 1** does everything the single pass used to do (direction resolution, TCP state,
  fingerprinting, TLS lookup), but defers `Flow` construction. While doing so it accumulates three
  aggregates across the whole capture:
  - `key_counts: Counter[_FlowKey]` — how many units share each five-tuple key (the same symmetric key
    `_flow_key` already uses for grouping).
  - `dest_by_src: Dict[str, Set[str]]` — the set of distinct canonical `dst_ip` values seen, keyed by
    canonical `src_ip`.
  - `port_by_src: Dict[str, Set[int]]` — the set of distinct canonical `dst_port` values seen, keyed by
    canonical `src_ip`.
- **Pass 2** builds every `Flow`, now that the aggregates are complete for the whole capture:
  - `destination_diversity = len(dest_by_src[src_ip])`, `port_diversity = len(port_by_src[src_ip])` —
    the count of distinct destination IPs/ports seen, within this capture, across every flow sharing
    this flow's own canonical `src_ip`. A flow whose source talks to nobody else in the capture still
    gets `1`/`1`, unchanged from Phase 23's placeholder value for that case.
  - `is_persistent = key_counts[key] > 1` — `True` when this flow's own five-tuple recurs as more than
    one `Flow` within the capture.

No new `Settings` field or threshold is introduced (NFR-4 doesn't apply — this is a deterministic
aggregation over what's already in the capture, not a tunable heuristic).

### Why `is_persistent` only ever fires for UDP

TCP five-tuples structurally never split: Phase 23 merges every packet sharing a five-tuple into one
`Flow` regardless of how many SYN/FIN cycles occur inside it, so a TCP five-tuple always maps to
exactly one unit and `key_counts[key]` is always `1`. UDP is the only protocol where one five-tuple can
produce more than one unit — Phase 25's idle-timeout session splitting (`_split_udp_sessions`) — so a
UDP five-tuple recurring as two or more sessions is genuine, real persistence evidence. This isn't an
oversight; it's the correct scope for what real recurrence looks like given how flows are constructed.

## What's real vs. honestly deferred

True cross-*capture* persistence — the same five-tuple recurring across separately-ingested captures —
remains out of scope. Nothing correlates flows across different `capture_id`s; `is_persistent` only
ever looks within the single capture `reconstruct_flows` was called for. Extending this would need a
store that indexes flows by five-tuple across captures, which isn't part of this pipeline's current
data model.

## Verification actually performed this phase

- `pytest backend/tests/test_nettrace_reconstruct.py` — 27/27 passed (up from 24/24 after Phase 27): 3
  new tests for diversity aggregation (two flows from the same source to different destination/port
  pairs both report the real distinct count; two flows to the same destination IP but different ports
  report `destination_diversity=1`/`port_diversity=2`; flows from different sources don't share
  aggregates), plus `is_persistent` assertions added to the existing UDP idle-gap-split test (`True` for
  both resulting sessions) and the existing single-session UDP test (`False`).
- Full combined suite (`pytest backend/tests experiments/tests simulator/tests`) — 212/212 passed (up
  from 209/209 after Phase 27), no regressions elsewhere.
- `python -m scripts.validate_data_contracts` — 38/38 passed, no regression (no schema fields changed).
- **Real, manual end-to-end run**: built a synthetic capture with two TCP flows from the same source IP
  to two different destinations, plus one UDP five-tuple idle-gap-split into two sessions. Ran
  `reconstruct_flows` directly and printed the resulting `FlowFeatures`: both TCP flows correctly
  reported `destination_diversity=2`, `port_diversity=2`, `is_persistent=False`; both UDP sessions
  correctly reported `destination_diversity=1`, `port_diversity=1`, `is_persistent=True` — matching
  hand-computed expected values exactly.

## Status

Flow feature completion (spec Phase 28, FR-1.8) is fully implemented and verified end-to-end for real.
Every `FlowFeatures` field is now computed from real evidence: no field is a hardcoded placeholder.
`destination_diversity`/`port_diversity` are real cross-flow aggregates scoped per capture and per
canonical source IP; `is_persistent` is real five-tuple recurrence detection, which in practice only
fires for UDP given how flows are structurally constructed. This closes the last item on the Phase 23
flow-reconstruction placeholder list (`docs/architecture/flow_reconstruction.md`).
