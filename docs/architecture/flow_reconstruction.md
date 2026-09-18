# NETSCOPE-X — Five-Tuple Flow Reconstruction

Phase 23 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 23 — FIVE-TUPLE FLOW
RECONSTRUCTION"). FR-1.3 (`docs/requirements/system_requirements.md`): "The system shall
reconstruct bidirectional five-tuple flows for TCP and UDP." Code: `backend/nettrace/reconstruct.py`
(`reconstruct_flows`), wired live into `GET /flows` (`backend/app/api/routes/flows.py`). This is
the phase that finally resolves `Packet.direction` — Phase 22 (Packet Normalization) left every
packet `UNKNOWN` because direction is documented as relative to the flow a packet belongs to, and
flows didn't exist until now.

## Algorithm

`docs/architecture/algorithm_selection.md` §1 (Phase 05) already selected the approach: a
five-tuple hash table keyed by `(src_ip, src_port, dst_ip, dst_port, protocol)` normalized to a
canonical direction, O(1) amortized per packet. `reconstruct_flows(root, capture_id)`:

1. Reads `packets_path(root, capture_id)` (Phase 22's output) via the existing `read_jsonl`.
2. Filters to `protocol in {TCP, UDP}` — FR-1.3's literal scope. ICMP/OTHER packets are excluded
   from flow grouping entirely and keep `direction=UNKNOWN` in the rewritten file — a documented,
   spec-conformant limitation, not an oversight (there is no "flow" concept for ICMP in this spec).
3. Groups packets by a **symmetric** key — `tuple(sorted([(src_ip, src_port), (dst_ip, dst_port)]))
   + (protocol,)` — so `A→B` and `B→A` packets land in the same bucket regardless of which side
   sent the first observed packet.
4. Within each group, sorts by `timestamp`. **The first packet observed** defines the canonical
   direction: its `(src_ip, src_port, dst_ip, dst_port)` becomes the `Flow` record's own
   `src_ip`/`dst_ip`/ports, and every packet sharing that exact orientation is `FORWARD`; the
   opposite orientation is `REVERSE`. This matches the natural "initiator" semantic (the SYN-sender
   for TCP) without an arbitrary numeric tie-break like "lower IP wins," and it is equally
   well-defined for UDP, which has no handshake to anchor on.
5. `Packet` is frozen (`model_config = {"frozen": True}`), so direction resolution never mutates in
   place — it produces new instances via `.model_copy(update={"direction": ...})`. The full packet
   list (direction-resolved flow packets, plus untouched ICMP/OTHER passthrough packets) is
   rewritten to `packets_path`, in the **original capture order** — only `direction` changes, never
   packet ordering.
6. Persists the flow list to `flows_path(root, capture_id)` via `write_jsonl` (both path helpers
   already existed from Phase 10).

## What's real-computed now vs. deferred to later phases

`Flow.features: FlowFeatures` is a required, non-Optional field with 9 required sub-fields — but
several of them are explicitly later phases' jobs (FR-1.8, Phase 28), and this project's design
ethic (`fingerprinted_protocol`'s own docstring: "`None` means 'not confidently fingerprinted' --
never a guess dressed as certainty") means Phase 23 does not reach ahead and fabricate values for
work it doesn't own yet:

| Field | This phase | Why |
|---|---|---|
| `packet_count`, `byte_count` | Real: `len(group)`, `sum(size_bytes)` | Trivial, honest arithmetic over packets already grouped. |
| `duration_seconds` | Real: `last_seen - first_seen` | Same. |
| `mean_inter_arrival_seconds` | Real: mean of consecutive gaps | Same. |
| `burstiness` | Real: population stdev / mean of inter-arrival gaps (coefficient of variation), `0.0` when fewer than 2 gaps exist | A real statistical computation, not a placeholder — but honestly `0.0` (not a fabricated number) when there isn't enough data for a meaningful spread. |
| `forward_byte_ratio` | Real: forward bytes / total bytes | Same arithmetic category. |
| `destination_diversity`, `port_diversity` | `1`, always | A five-tuple flow has exactly *one* destination and *one* port pair by definition — this is not a placeholder, it's the correct value for what these fields mean at flow-record granularity. Their real "diversity across many flows" meaning is Phase 28's cross-flow aggregation job. |
| `is_persistent` | `False`, always | No cross-window recurrence signal exists within a single capture's flow packets — there's nothing here to compute honestly. Documented as Phase 28's real job (FR-1.8: "connection persistence"), not a guess. |
| `tcp_state` | Real: retransmission-safe TCP finite state machine over flags/direction/timestamp order | Phase 24 (FR-1.4). See `docs/architecture/tcp_state_tracking.md` for the full transition table. |
| `fingerprinted_protocol` | `None`, always | Explicitly Phase 26 (FR-1.6). Same reasoning. |

## `GET /flows` goes live

Unlike Phase 22 (which stayed a route-free internal module), `GET /flows`'s own docstring already
earmarked it for this phase. Given a `capture_id`, the route:
1. Checks `pcap_path(settings.artifact_root, capture_id).is_file()` — if not, raises a new
   `CaptureNotFoundError` (`backend/nettrace/capture/errors.py`, stdlib-only like its Phase 21
   siblings), mapped to 404 `capture_not_found` (`backend/app/api/errors.py`).
2. Runs `normalize_pcap` then `reconstruct_flows` **synchronously, fresh, on every request** — no
   job queue, no cache layer. This is a deliberate, documented simplification consistent with spec
   §6's "minimum necessary infrastructure" principle and the project's existing "known
   simplification" precedent (Phase 09's simulation/counterfactual DTO note), not a REST-purity
   claim. It also guarantees the response is never stale relative to whatever `raw.pcap` currently
   contains.
3. Paginates through the existing Phase 09 `PageParams`/`PaginatedResponse[Flow]` convention.

## Verification actually performed this phase

- `pytest backend/tests/test_nettrace_reconstruct.py` — 7/7 passed: bidirectional packets merge
  into one flow; direction correctly assigned (first-observed packet's orientation is `FORWARD`,
  opposite is `REVERSE`); `FlowFeatures` arithmetic verified against hand-computed expected values
  for a real 3-packet exchange (duration, mean inter-arrival, forward_byte_ratio all byte-exact);
  distinct five-tuples correctly produce separate flows; ICMP/OTHER packets excluded from flows and
  left `UNKNOWN`; full round-trip through `write_jsonl`/`read_jsonl` for `flows.jsonl`; original
  packet ordering preserved in the rewritten `packets.jsonl`.
- `pytest backend/tests/test_api.py` — the 10 still-unimplemented endpoint groups still return the
  structured 501 envelope (no regression); new `GET /flows` real-behavior tests: 404
  `capture_not_found` for an unknown capture_id, a real ingested 3-packet TCP exchange producing
  exactly 1 flow with `packet_count: 3`, and pagination (`limit`/`offset`) correctly slicing a
  2-flow result.
- Full combined suite (`pytest backend/tests experiments/tests simulator/tests`) — 168/168 passed
  (up from 159/159 after Phase 22), no regression.
- `python -m scripts.validate_data_contracts` — 38/38 passed, no regression.
- `python scripts/check_ground_truth_boundary.py` — clean, zero violations.
- **Real, manual end-to-end run** (no Docker needed — pure pcap-file parsing, like Phases 21-22):
  built a real 7-packet pcap with Scapy (a 5-packet TCP exchange — SYN, SYN-ACK, ACK, and a data
  packet each direction — plus a separate 2-packet UDP exchange), ingested it through the live
  FastAPI app's real `POST /capture`, then called the real `GET /flows?capture_id=...`. Confirmed:
  a 404 `capture_not_found` for an unrelated, never-ingested capture_id; exactly 2 real flows
  returned (one TCP, one UDP), each with `src_ip`/`src_port` correctly identifying the real
  initiator (`172.20.0.10:51000` for TCP, matching the SYN-sender); real `FlowFeatures` — TCP flow:
  `packet_count: 5`, `byte_count: 211`, real non-zero `burstiness` and `mean_inter_arrival_seconds`,
  `forward_byte_ratio: 0.592...` matching the actual forward/reverse byte split; UDP flow:
  `packet_count: 2`, `byte_count: 56`, `burstiness: 0.0` (correctly, with only one inter-arrival
  gap); both flows' `tcp_state`/`fingerprinted_protocol` correctly `None`. Read back the real
  `packets.jsonl` on disk afterward and confirmed every packet's `direction` was rewritten from
  Phase 22's `unknown` to a real, correct `forward`/`reverse`, in the original capture order.

## Status

Five-tuple flow reconstruction (spec Phase 23) is fully implemented and verified end-to-end for
real, for both TCP and UDP, including live wiring into `GET /flows`. `Packet.direction` is now
correctly resolved relative to real reconstructed flows rather than left `unknown`. `tcp_state` is
now also real, as of Phase 24 (`docs/architecture/tcp_state_tracking.md`). `fingerprinted_protocol`
and the cross-flow-aggregation-dependent parts of `FlowFeatures` (`is_persistent`, and the true
cross-flow meaning of `destination_diversity`/`port_diversity`) remain honestly
unset/placeholder pending Phases 26 and 28 respectively.
