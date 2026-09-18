# NETSCOPE-X — UDP Session Modeling

Phase 25 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 25 — UDP SESSION MODELING").
FR-1.5 (`docs/requirements/system_requirements.md`): "The system shall model UDP sessions using
endpoint, port, and timing-window heuristics." Code: `backend/nettrace/reconstruct.py`
(`_split_udp_sessions`), called from `reconstruct_flows` for every UDP five-tuple group before flows
are built. `GET /flows` (`backend/app/api/routes/flows.py`) needs no route changes — it already calls
`reconstruct_flows` on every request and now threads `Settings.udp_session_idle_timeout_seconds`
through explicitly.

## Algorithm

`docs/architecture/algorithm_selection.md` §1 (Phase 05) already selected the approach: the same
five-tuple hash table Phase 23 uses (the "endpoint, port" heuristic FR-1.5 names), plus a second,
UDP-only heuristic layered on top — a configurable idle-timeout (the "timing-window" heuristic).

`_split_udp_sessions(group, idle_timeout_seconds)` takes one UDP five-tuple's packets, sorts them by
timestamp, and walks them once: whenever the gap to the next packet strictly exceeds
`idle_timeout_seconds`, a new session starts. A gap exactly equal to the timeout does **not** split
(strict `>`), avoiding an off-by-one edge case at the boundary. Each resulting session is exactly the
same shape as a five-tuple group already was pre-Phase-25 — so `reconstruct_flows`'s existing
per-group logic (canonical direction resolution, `_compute_features`) needs zero changes; it simply
runs once per session instead of once per five-tuple.

Concretely, `reconstruct_flows` now builds a flat list of "units" before assigning flow indices:
every TCP five-tuple group stays one unit unchanged; every UDP five-tuple group is expanded into
`_split_udp_sessions`'s output, one unit per session. All units (TCP and UDP alike) are then sorted
by their own earliest packet's timestamp — the same "deterministic ordering" rule Phase 23 already
used for five-tuple groups, just applied one level lower, at unit granularity.

**Canonical orientation is resolved per session, not per five-tuple.** UDP has no persistent
"initiator" the way TCP's SYN-sender is — a five-tuple that goes quiet for a while and resumes later
could plausibly have either side speak first the second time (e.g. a retried DNS query, or a new
independent request reusing the same ephemeral port). So each session's own first-observed packet
defines its own forward direction, exactly matching Phase 23's original rule ("the first packet
observed defines canonical direction") applied at the new, finer session granularity rather than
inheriting the direction the five-tuple's very first packet (possibly minutes earlier, in an
unrelated session) happened to establish.

## Configuration (NFR-4)

**NFR-4**: "Configuration-driven behavior — no hardcoded paths, thresholds framed as magic numbers."
The idle-timeout is `Settings.udp_session_idle_timeout_seconds` (`backend/app/core/config.py`),
default `30.0` seconds — matching common conntrack-style UDP idle-timeout conventions (e.g. Linux
`nf_conntrack`'s default), a documented, justified default rather than an arbitrary number.
Env-overridable as `NETSCOPE_UDP_SESSION_IDLE_TIMEOUT_SECONDS`, validated `gt=0`. `GET /flows`
(`backend/app/api/routes/flows.py`) reads it from `get_settings()` and passes it explicitly to
`reconstruct_flows` — it is not threaded automatically, since `reconstruct_flows` is a pure function
that only receives what it's given. `reconstruct_flows` itself keeps a `30.0`-second default
parameter value so direct/test callers that don't care about the setting still get sensible behavior
without needing to import `Settings`.

## What's real vs. honestly deferred

`is_persistent` (`FlowFeatures`) stays `False` for every flow, UDP sessions included — this is a
deliberate scoping decision, not an oversight. FR-1.8's "connection persistence" / "recurs across
observation windows" describes a signal across multiple captures or long-running observation windows
(Phase 28's job, per Phase 23's own scoping), not "this five-tuple produced more than one session
within a single capture because of an idle gap." Session-splitting and persistence are different
concepts: a five-tuple correctly producing 2 UDP session-flows in one capture is not, by itself,
evidence of the kind of cross-window recurrence `is_persistent` is meant to represent.

## Verification actually performed this phase

- `pytest backend/tests/test_nettrace_reconstruct.py` — 22/22 passed (up from 16/16 after Phase 24):
  6 new tests — two close-together UDP packets stay one session; an idle gap exceeding a passed-in
  timeout splits a five-tuple into two sessions with correct per-session packet counts and
  orientation; a gap exactly equal to the timeout does not split (boundary case); a gap one
  millisecond over the timeout does split; a TCP flow with an equally large internal gap is
  unaffected (still exactly one flow, proving the heuristic is UDP-only); a mix of one TCP flow and
  one UDP five-tuple split into two sessions still orders all three resulting flows deterministically
  by each unit's own earliest packet timestamp.
- `pytest backend/tests/test_config.py` — 11/11 passed (up from 9/9): default value `30.0`; `gt=0`
  rejects `0` and negative values; `NETSCOPE_UDP_SESSION_IDLE_TIMEOUT_SECONDS` env override verified.
- Full combined suite (`pytest backend/tests experiments/tests simulator/tests`) — 185/185 passed (up
  from 177/177 after Phase 24), no regressions elsewhere.
- `python -m scripts.validate_data_contracts` — 38/38 passed, no regression.
- `python scripts/check_ground_truth_boundary.py` — clean, zero violations.
- **Real, manual end-to-end run** (no Docker needed — pure pcap-file parsing, like Phases 21-24):
  built a real Scapy pcap with explicit per-packet timestamps (the same `pkt.time` mechanism
  `normalize.py` already reads) — one UDP five-tuple with a 2-packet burst, a gap comfortably past
  the real configured `udp_session_idle_timeout_seconds` (30.0s default), then a second 2-packet
  burst on the *same* five-tuple; plus a TCP flow with an equally large internal gap. Ingested
  through the live FastAPI app's real `POST /capture`, then queried through the real `GET /flows`.
  Confirmed: the UDP five-tuple produced exactly 2 real flows (2 packets each), the TCP flow with the
  same-magnitude gap stayed exactly 1 real flow (4 packets, `tcp_state: "closing"`), proving the
  session-splitting heuristic is real, correctly gap-triggered, and correctly UDP-only.

## Status

UDP session modeling (spec Phase 25, FR-1.5) is fully implemented and verified end-to-end for real.
A UDP five-tuple's packets are now split into separate `Flow` records wherever a real, configurable
idle-timeout is exceeded, with correct per-session direction resolution and no `Flow`/`Packet`
schema changes needed. TCP flows are provably unaffected. `fingerprinted_protocol` and the
cross-flow-aggregation-dependent parts of `FlowFeatures` (`is_persistent`, and the true cross-flow
meaning of `destination_diversity`/`port_diversity`) remain honestly unset/placeholder pending
Phases 26 and 28 respectively.
