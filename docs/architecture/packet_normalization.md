# NETSCOPE-X — Packet Normalization

Phase 22 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 22 — PACKET
NORMALIZATION"): "Normalize: timestamps, IPs, ports, protocol, packet size, direction, transport
information." FR-1.2 (`docs/requirements/system_requirements.md`): "The system shall normalize
packets to a consistent schema: timestamp, source/destination IP, ports, protocol, size,
direction, transport info." Code: `backend/nettrace/normalize.py`. This phase is the first to
actually populate the `Packet` model (`backend/app/models/packet.py`), which has existed since
Phase 04 but was never written to until now.

## Design: pure per-packet extraction, direction deferred to Phase 23

`normalize_pcap(root, capture_id)` reads the real `captures/<capture_id>/raw.pcap` written by
Phase 21's `ingest_pcap` via Scapy's streaming `PcapReader` (the same convention
`backend/nettrace/capture/ingest.py` already uses — not `rdpcap`, which loads everything into
memory), and produces one frozen `Packet` per real captured frame that carries an IP (v4 or v6)
layer:

| Spec field | Extraction |
|---|---|
| `timestamp` | `pkt.time` (Scapy's `EDecimal`) cast to `float`, converted to UTC. |
| `src_ip`/`dst_ip` | The `IP` layer's `src`/`dst`, or `IPv6`'s if no `IP` layer is present. |
| `src_port`/`dst_port` | The `TCP`/`UDP` layer's `sport`/`dport`; `None` for ICMP/OTHER. |
| `protocol` | `TCP`/`UDP`/`ICMP` via `pkt.haslayer(...)`, else `OTHER`. |
| `packet size` | `pkt.wirelen` (Scapy's real original captured length), falling back to `len(bytes(pkt))`. |
| `transport information` | `tcp_flags` — a comma-separated, human-readable string (e.g. `"SYN,ACK"`), built from Scapy's own letter-code flag representation (`str(pkt[TCP].flags)`, confirmed real output during implementation) mapped through a fixed letter→name table; only set when `protocol == TCP`. |
| `direction` | Always `PacketDirection.UNKNOWN`. |

**Why direction stays `UNKNOWN` at this phase**: `PacketDirection`'s own docstring
(`backend/app/models/packet.py`) says direction is "relative to the flow this packet was assigned
to." A single packet has no well-defined forward/reverse in isolation — that requires knowing
which five-tuple flow it belongs to and which endpoint is that flow's initiator, and flows don't
exist until Phase 23 reconstructs them. Populating anything other than `UNKNOWN` here would be a
guess dressed as certainty, which the project's evidence-based design principle
(`docs/architecture/data_contracts.md`) explicitly rejects.

**Frames without an IP layer are skipped, not fabricated.** `Packet.src_ip`/`dst_ip` are required,
non-optional fields; a bare Ethernet/ARP frame has no IP addresses to normalize into this schema,
so it is skipped entirely rather than assigned a placeholder address. `packet_id` (`f"{capture_id}:
{index}"`, matching the field's own docstring example) still reflects each surviving packet's real
position in the capture, so a skip is visible as a gap in the numbering rather than hidden.

## Persistence

New path helper `packets_path(root, capture_id)` (`experiments/artifacts/paths.py`), following the
exact same pattern as `pcap_path`/`capture_manifest_path`: `captures/<capture_id>/packets.jsonl`.
Written via the existing generic `write_jsonl` helper (`experiments/artifacts/io.py`) — no new I/O
primitive needed, and no hash sidecar, since normalized packets are not ground truth.

## No new API endpoint

The 12 fixed endpoint groups from Phase 09 have no "normalize" group. `normalize_pcap` is an
internal library function; `GET /flows` (`backend/app/api/routes/flows.py`, still
`NotYetImplemented("flow reconstruction (spec Phase 23)")`) is its natural future caller —
normalization is a step flow reconstruction performs before grouping packets into five-tuple
flows, not something exposed directly to API callers.

## Verification actually performed this phase

- `pytest backend/tests/test_nettrace_normalize.py` — 6/6 passed: correct field extraction for
  TCP (with real flag-string formatting, `"SYN,ACK"`), UDP, and ICMP; a bare `Ether()` frame (no IP
  layer) correctly skipped while a real packet elsewhere in the same capture still survives with
  its real capture-order `packet_id`; `packet_id` numbering matches real position across a 4-packet
  capture; a full round-trip through `write_jsonl`/`read_jsonl` returns byte-identical `Packet`
  objects.
- Full combined suite (`pytest backend/tests experiments/tests simulator/tests`) — 159/159 passed
  (up from 153/153 after Phase 21), no regression.
- `python -m scripts.validate_data_contracts` — 38/38 passed, no regression.
- `python scripts/check_ground_truth_boundary.py` — clean, zero violations.
- **Real, manual end-to-end run** (no Docker needed — this is pure pcap-file parsing, like Phase
  21's `pcap_upload` half): built a real 5-packet pcap with Scapy (a TCP three-way-handshake-style
  exchange with real SYN/SYN-ACK/ACK flags between two addresses, a UDP packet, and an ICMP
  packet), ingested it through the real, live FastAPI app's `POST /capture` (Phase 21), then ran
  `normalize_pcap` against the real ingested `raw.pcap`. All 5 packets were normalized with every
  field matching exactly what was put into the synthetic capture (real IPs, real ports, real
  protocols, real sizes of 40/40/40/28/28 bytes, real flag strings `SYN`/`SYN,ACK`/`ACK`, and
  `direction: unknown` throughout) — confirmed both from the in-memory `Packet` objects and by
  reading back the real `captures/<capture_id>/packets.jsonl` file written to disk.

## Status

Packet normalization (spec Phase 22) is fully implemented and verified end-to-end for real: every
required field (timestamps, IPs, ports, protocol, packet size, transport information) is populated
from genuine Scapy-parsed packet data, with `direction` correctly deferred to Phase 23 rather than
guessed. This does not depend on the Docker-lab live-capture verification still pending from Phase
21 — normalization consumes any real `raw.pcap`, regardless of how it was ingested.
