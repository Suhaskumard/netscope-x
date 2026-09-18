# NETSCOPE-X — Protocol Fingerprinting

Phase 26 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 26 — PROTOCOL
FINGERPRINTING"). FR-1.6 (`docs/requirements/system_requirements.md`): "The system shall perform
protocol fingerprinting from observable evidence only, and shall not claim protocol coverage it
cannot support." Code: `backend/nettrace/fingerprint.py` (`fingerprint_protocol`), called from
`backend/nettrace/reconstruct.py`'s `reconstruct_flows` for every flow it builds, populating
`Flow.fingerprinted_protocol` for real for the first time. `GET /flows`
(`backend/app/api/routes/flows.py`) needs no changes — it already calls `reconstruct_flows` on every
request, so it picks this up automatically.

## Algorithm decision (made this phase)

Unlike Phases 23-25, `docs/architecture/algorithm_selection.md` (Phase 05) does not cover protocol
fingerprinting — that doc's 6 sections are flow reconstruction, role inference, anomaly detection,
graph criticality, path analysis, and dependency inference. This is an honest gap in the original
Phase 05 planning, not silently papered over here; the algorithm decision is made and justified in
this document instead.

**Available evidence is strictly metadata.** `Packet` (`backend/app/models/packet.py`) carries only
`timestamp, src_ip, dst_ip, src_port, dst_port, protocol, size_bytes, direction, tcp_flags` — no
application-layer payload field exists anywhere, consistent with the project's already-established
non-payload-reassembly observability model (`docs/architecture/algorithm_selection.md` §1's rejection
of full protocol-stack byte-level reassembly as unjustified cost). Deep packet inspection is
therefore not possible, and this is the honest reason the fingerprinter is a **port/transport-based
heuristic**, not a payload signature matcher.

`fingerprint_protocol(protocol, src_port, dst_port)`: looks up `(protocol, dst_port)` against a
small, explicit table of well-known `(transport, port) -> protocol name` pairs; if that misses, falls
back to `(protocol, src_port)` (covering the case where the canonical flow orientation happens to put
the well-known port on the source side — e.g. the server was the first-observed packet's sender).
Anything not in the table returns `None`, never a guess. This directly satisfies FR-1.6: the system
only ever names a protocol it has an explicit, documented rule for.

## The table

| Transport | Port | Name |
|---|---|---|
| TCP | 80 | `http` |
| TCP | 443 | `tls` |
| TCP | 5432 | `postgresql` |
| TCP | 6379 | `redis` |
| UDP | 53 | `dns` |

Scoped deliberately to the protocols `simulator/traffic/protocols.py` (Phase 15) generates real
wire-level traffic for — HTTP, generic TCP, DNS, Redis/RESP, PostgreSQL, TLS — so every table entry is
independently, end-to-end verifiable against known ground truth (the lab can actually produce traffic
on each of these ports for real), not just asserted in isolation. Generic/raw TCP has no
distinguishing port and stays `None` — there is no real signal to name it by.

## Known limitations

This is a heuristic, not certainty, and the limitations are real, not hypothetical:

- **A service on a non-standard port is not recognized.** An HTTP server on port 8080, for instance,
  fingerprints as `None`, correctly reflecting that nothing here has evidence of what it is — not a
  gap to silently work around, since doing so (e.g. payload sniffing) is out of scope given the
  metadata-only `Packet` schema.
- **A different service reusing a well-known port would be misidentified.** Port 80 is *evidence*
  consistent with HTTP, not proof — this is the nature of a port-based heuristic and is why FR-1.6's
  "shall not claim protocol coverage it cannot support" matters: the system names a *plausible*
  protocol from the evidence available, not a certain one, and the field's own docstring already
  states this ("`None` means 'not confidently fingerprinted' -- never a guess dressed as certainty").
- Real deep packet inspection (e.g. distinguishing HTTP from another TCP/80 service by payload) would
  require `Packet` to carry payload bytes, which it deliberately does not (spec's metadata-only
  observability model). Extending it would be a real, documented schema change for a future phase to
  consider if requirements actually need it — not something quietly assumed here.

## Verification actually performed this phase

- `pytest backend/tests/test_nettrace_fingerprint.py` — 13/13 passed: all 5 table entries resolve
  correctly (`http`, `tls`, `postgresql`, `redis`, `dns`); an unrecognized TCP port returns `None`;
  `dst_port` is checked before `src_port`, but a reversed orientation (well-known port only on
  `src_port`) still resolves correctly via fallback; both ports `None` returns `None`; the wrong
  transport for a well-known port (TCP instead of UDP for port 53) correctly returns `None`, not
  `dns`; plus 3 integration-level tests via `reconstruct_flows` confirming a real HTTP flow, a real
  DNS session, and a real unrecognized-port flow all fingerprint correctly end-to-end.
- `pytest backend/tests/test_nettrace_reconstruct.py` — the existing Phase 23 test's
  `fingerprinted_protocol` assertion was corrected from `None` (Phase 23's honest placeholder) to
  `"http"` (its fixture uses port 80, which the real fingerprinter now correctly recognizes).
- Full combined suite (`pytest backend/tests experiments/tests simulator/tests`) — 198/198 passed (up
  from 185/185 after Phase 25), no regressions elsewhere.
- `python -m scripts.validate_data_contracts` — 38/38 passed, no regression.
- `python scripts/check_ground_truth_boundary.py` — clean, zero violations.
- **Real, manual end-to-end run** (no Docker needed — pure pcap-file parsing, like Phases 21-25):
  built a real Scapy pcap with three exchanges — HTTP-shaped (TCP/80), DNS-shaped (UDP/53), and
  generic TCP on an unrecognized port (9999) — ingested through the live FastAPI app's real
  `POST /capture`, then queried through the real `GET /flows`. Confirmed all three real
  `fingerprinted_protocol` outcomes exactly as expected: `"http"`, `"dns"`, and `None`.

## Status

Protocol fingerprinting (spec Phase 26, FR-1.6) is fully implemented and verified end-to-end for
real. `Flow.fingerprinted_protocol` is now real for every flow `reconstruct_flows` builds (TCP and
UDP alike), computed by an explicit, honestly-scoped port/transport heuristic table. The
cross-flow-aggregation-dependent parts of `FlowFeatures` (`is_persistent`, and the true cross-flow
meaning of `destination_diversity`/`port_diversity`) remain honestly unset/placeholder pending
Phase 28.
