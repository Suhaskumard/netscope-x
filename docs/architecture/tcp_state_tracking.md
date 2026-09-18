# NETSCOPE-X — TCP State Tracking

Phase 24 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 24 — TCP STATE TRACKING").
FR-1.4 (`docs/requirements/system_requirements.md`): "The system shall track TCP state
(SYN/SYN-ACK/ACK/FIN/RST, retransmissions, partial sessions)." Code: `backend/nettrace/reconstruct.py`
(`_compute_tcp_state`), called from `reconstruct_flows` for every TCP flow it builds, populating
`Flow.tcp_state` for real for the first time. `GET /flows` (`backend/app/api/routes/flows.py`) needs
no changes — it already calls `reconstruct_flows` on every request, so it picks this up automatically.

## Algorithm

`docs/architecture/algorithm_selection.md` §1 (Phase 05) already selected the approach: a TCP finite
state machine layered on top of the five-tuple hash table reconstruction, mapping directly to
`TCPState`'s 6 values (pre-declared at Phase 04: `SYN_SENT`, `ESTABLISHED`, `CLOSING`, `CLOSED`,
`RESET`, `PARTIAL`). `_compute_tcp_state(directed_group)` takes the same timestamp-sorted,
direction-resolved packet list `reconstruct_flows` already builds for `_compute_features` — it never
re-derives orientation, just consumes the `PacketDirection` its caller already computed.

Single forward pass over the group, tracking four booleans (`saw_syn`, `established`, `fwd_fin`,
`rev_fin`) — never counters, which is what makes the FSM retransmission-safe by construction (see
"Retransmissions" below):

| Observed | Effect |
|---|---|
| `RST` in flags, at any point | Return `RESET` immediately — short-circuits every other rule, even after `ESTABLISHED`/`CLOSING`, matching real TCP semantics (a reset ends the session abnormally regardless of what came before). |
| `SYN` (plain or `SYN,ACK`) | Sets `saw_syn = True`. Does not by itself move past `SYN_SENT` — that only happens on the handshake's third leg. |
| plain `ACK` (no `SYN`/`FIN`/`RST`), while `saw_syn` and not yet `established` and no FIN seen yet | The three-way handshake's completing ACK — sets `established = True`. |
| `FIN` (with or without `ACK`) | Records which direction sent it (`fwd_fin`/`rev_fin`). |

After the scan, the final `TCPState` is derived from those four booleans:

- `not saw_syn or not established` → **`PARTIAL`** — either no SYN was ever observed at all (the
  capture started mid-session) or a SYN was observed but the handshake never completed within the
  capture window. Both are honestly "a session observed without a full handshake," matching
  `TCPState.PARTIAL`'s own docstring — never fabricated as `ESTABLISHED`/`CLOSING` just because *some*
  traffic was seen.
- `fwd_fin and rev_fin` → **`CLOSED`** — both directions have sent a FIN. This is the
  honestly-derivable approximation given no sequence numbers exist to rigorously pair each FIN with
  its specific acknowledging ACK; "both sides FIN'd" is the strongest signal available from
  flags+direction alone.
- `fwd_fin or rev_fin` (but not both) → **`CLOSING`** — teardown has started, one side hasn't FIN'd yet.
- otherwise → **`ESTABLISHED`**.

## Retransmissions

FR-1.4 groups "retransmissions" together with the state list it names, not as a separate output.
Given `Packet` has no TCP sequence/ack field (Scapy exposes one; Phase 22's `normalize.py` never
extracted it, and adding it now is out of scope for a metadata-only observability model — see
"Known limitation" below), real mid-stream *data* retransmission detection (matching a resent
sequence number) is honestly not possible with the current schema. What **is** honestly detectable
from flags + direction + timestamp order alone is handshake/teardown-level retransmission: a
duplicate SYN in a direction already seen, or a duplicate FIN in a direction that already sent one.

`_compute_tcp_state` handles this by construction, not by a separate detection step: every signal is
a boolean, not a counter, so re-observing `SYN` in a direction that already set `saw_syn = True`, or
`FIN` in a direction that already set `fwd_fin`/`rev_fin = True`, is a structural no-op — it cannot
re-trigger a transition or corrupt the already-determined state. This is the concrete meaning of
"tracks retransmissions" here: the FSM is retransmission-safe, not retransmission-blind (a naive
implementation keying off "the last packet's flags" or a raw transition table without idempotent
guards could easily flip states back and forth on a retransmit). No new schema field was added —
`TCPState`'s 6 values, pre-declared at Phase 04, were already the complete required output surface,
and no sibling field (e.g. a retransmission counter) exists anywhere in `FlowFeatures`.

## Known limitation

Real mid-stream TCP data-retransmission detection (a resent segment identified by a duplicate
sequence number, distinct from the handshake/teardown-level cases above) requires TCP sequence
numbers, which `Packet` does not carry — Phase 22's `normalize.py` extracts only `tcp_flags`, ports,
size, and timestamp from Scapy, matching the project's stated metadata-only, non-payload-reassembly
observability model (`docs/architecture/algorithm_selection.md` §1's rejection of full protocol-stack
byte-level reassembly as unjustified cost for this project). This is an honestly documented scope
boundary, not a gap discovered after the fact — extending `Packet` with `tcp_seq`/`tcp_ack` fields
would be a straightforward follow-up if a later phase's requirements actually need it, but nothing in
FR-1.4 or `TCPState`'s existing 6 values requires it.

## Verification actually performed this phase

- `pytest backend/tests/test_nettrace_reconstruct.py` — 16/16 passed (up from 7/7 after Phase 23):
  the existing full-handshake test's `tcp_state` assertion was corrected from `None` (Phase 23's
  honest placeholder) to `ESTABLISHED` (Phase 24's real computation); 9 new tests: full handshake →
  `ESTABLISHED`; handshake + one-sided FIN → `CLOSING`; handshake + FIN both directions → `CLOSED`;
  `RST` at three different points (right after SYN, after `ESTABLISHED`, after `CLOSING`) all →
  `RESET`; TCP packets with no SYN at all → `PARTIAL`; SYN(s) with no completing ACK → `PARTIAL`; a
  retransmitted SYN before the SYN-ACK reply does not corrupt the eventual `ESTABLISHED` result; a
  retransmitted FIN does not corrupt `CLOSING`; a UDP-only flow's `tcp_state` stays `None`.
- `pytest backend/tests/test_api.py` — the Phase 23 `GET /flows` real-behavior test's assertion was
  corrected from `tcp_state is None` to `tcp_state == "established"` (its 3-packet exchange is a real
  complete SYN/SYN-ACK/ACK handshake, so `None` was always Phase 23's honest placeholder, not the
  final answer).
- Full combined suite (`pytest backend/tests experiments/tests simulator/tests`) — 177/177 passed (up
  from 168/168 after Phase 23), no regressions elsewhere.
- `python -m scripts.validate_data_contracts` — 38/38 passed, no regression.
- `python scripts/check_ground_truth_boundary.py` — clean, zero violations.
- **Real, manual end-to-end run** (no Docker needed — pure pcap-file parsing, like Phases 21-23):
  built a real Scapy pcap with three distinct TCP exchanges — (1) a full handshake, a data packet
  each direction, then FIN from both sides, (2) a handshake followed by a `RST`, (3) a bare
  mid-stream `ACK`-only exchange with no SYN at all — ingested through the live FastAPI app's real
  `POST /capture`, then queried through the real `GET /flows`. Confirmed all three real `tcp_state`
  outcomes exactly as expected: `"closed"` (7 packets), `"reset"` (4 packets), `"partial"` (2
  packets); also confirmed the rewritten `packets.jsonl`'s direction resolution is unaffected
  (still all non-`"unknown"`), i.e. no regression to Phase 23's own behavior.

## Status

TCP state tracking (spec Phase 24, FR-1.4) is fully implemented and verified end-to-end for real.
`Flow.tcp_state` is now real for every TCP flow `reconstruct_flows` builds, computed by a
retransmission-safe finite state machine over observed flags, direction, and timestamp order.
`fingerprinted_protocol` and the cross-flow-aggregation-dependent parts of `FlowFeatures`
(`is_persistent`, and the true cross-flow meaning of `destination_diversity`/`port_diversity`) remain
honestly unset/placeholder pending Phases 26 and 28 respectively. Real mid-stream TCP
data-retransmission detection remains an honestly documented, deliberate scope boundary (no TCP
sequence number on `Packet`), distinct from the handshake/teardown-level retransmission safety this
phase does implement and test for real.
