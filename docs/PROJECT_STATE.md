# NETSCOPE-X — Project State

This file is the single source of truth for project progress across the 69-phase execution plan
defined in the master spec (`NETSCOPE (1).pdf`). Update it after every phase.

## Current phase

Phase 33 (Behavioral Feature Store) complete, unit-verified -- the first FLOWMIND-pipeline phase.
`compute_node_behavioral_features` (`backend/flowmind/features/node_features.py`) computes a real
per-node feature vector -- `distinct_ports`, `distinct_protocols`, `distinct_destinations`,
`mean_flow_duration_seconds`, `outbound_byte_ratio`, `is_persistent_talker` -- from any
caller-supplied `Flow` list, covering exactly the feature vocabulary `docs/architecture/
algorithm_selection.md` §2 already committed a future Naive-Bayes-style role classifier (Phase 36-37)
to (port set entropy, protocol mix, traffic directionality, persistence, destination diversity).
`distinct_ports` deliberately counts only ports where the node is the flow's destination (its own
"listening" ports), excluding a client's ephemeral source ports, which would otherwise dilute the
signal with no informational value. `distinct_destinations` counts only outbound (node-as-source)
flows' distinct destinations -- fan-out, not "how many clients contact me." The function is
deliberately window-agnostic (filters only by "does this flow touch this node," never by time) and
returns a plain `NodeBehavioralFeatures` dataclass, not a real `BehavioralFingerprint` --
`backend/app/models/behavior.py`'s schema needs `node_id`/`window`/`computed_at` identity fields that
belong to Phase 34 (deciding the three observation-window boundaries) and Phase 35 (assembling and
persisting the fingerprint), neither reached ahead of here. `NodeBehavioralFeatures`'s field names
deliberately match `BehavioralFingerprint`'s own feature fields so that future assembly is a plain
field copy. New package `backend/flowmind/` (nested under `backend/`, following the same
deployment-boundary convention already established for `backend/nettrace/`). See
`docs/architecture/behavioral_feature_store.md` for the full design, per-feature rationale, and
verification record. Phase 21 (High-Fidelity Packet Capture)'s one open item still stands: controlled
live capture is implemented and unit-verified but not yet verified against a real Docker lab (this
session's environment has no Docker installation — see `docs/architecture/packet_capture.md` "Known
limitations").

## Process note

Starting Phase 11, `README.md` (repo root) is created/updated after every completed phase, alongside
this file. `README.md` is the human-facing front door (what NETSCOPE-X is, current status, how to run
what exists); this file remains the detailed, continuously-updated machine-readable state.

## Completed phases

- Phase 0 — Setup (environment inspection + initial scaffolding)
- Phase 01 — Research Problem Formalization (`docs/research/problem_definition.md`)
- Phase 02 — Research Questions and Hypotheses (`docs/research/research_questions.md`)
- Phase 03 — System Requirements (`docs/requirements/system_requirements.md`)
- Phase 04 — Architecture and Data Contracts (`backend/app/models/`,
  `docs/architecture/data_contracts.md`, validated by `scripts/validate_data_contracts.py`)
- Phase 05 — Algorithm Selection (`docs/architecture/algorithm_selection.md`)
- Phase 06 — Reproducible Development Environment (`requirements.txt`, `requirements-dev.txt`,
  `frontend/`, `backend/Dockerfile`, `frontend/Dockerfile`, `docker-compose.yml`, `scripts/setup.sh`,
  `docs/development/environment.md`)
- Phase 07 — Observability Framework (`backend/app/core/{context,logging,timing}.py`, wired into
  `backend/app/main.py`, `docs/architecture/observability.md`)
- Phase 08 — Configuration and Secrets (`backend/app/core/config.py`, `.env.example`, `.env.test`,
  wired into `backend/app/main.py`, `docs/architecture/configuration.md`)
- Phase 09 — API Architecture (`backend/app/api/` — schemas, errors, 12 route modules, versioned
  `/api/v1` router — wired into `backend/app/main.py`, `docs/architecture/api_design.md`)
- Phase 10 — Research Artifact Architecture (`experiments/artifacts/{paths,io}.py`,
  `docs/architecture/research_artifacts.md`)
- Phase 11 — Multi-Tier Network Laboratory (`simulator/docker/` — 10-service Docker Compose lab,
  `docs/architecture/network_laboratory.md`); `README.md` created
- Phase 12 — Network Namespace Isolation (`simulator/docker/docker-compose.yml` modified in place:
  4 segmented networks — edge/app/data/external; boundaries verified positive+negative;
  `docs/architecture/network_laboratory.md` updated; `README.md` updated)
- Phase 13 — Routing Laboratory (added `load-balancer-2` + upstream pool in `gateway/nginx.conf`;
  live zero-downtime failover actually triggered and verified, then recovery confirmed;
  `docs/architecture/network_laboratory.md` updated; `README.md` updated)
- Phase 14 — Traffic Workload Generator (`simulator/traffic/{patterns,generate}.py`, all 6 required
  patterns; `simulator/tests/test_patterns.py`; real runs of normal/burst/concurrent against the live
  lab; `docs/architecture/traffic_generation.md`; `README.md` updated)
- Phase 15 — Protocol Workload Generator (`simulator/traffic/{protocols,generate_protocol}.py`, all 6
  required protocols with real wire-level exchanges; TLS-capable `external-service`;
  `simulator/tests/test_protocols.py`; real run of all 6 protocols against the live lab;
  `docs/architecture/protocol_generation.md`; `README.md` updated)
- Phase 16 — Ground-Truth Generator (`simulator/ground_truth/{topology,models,generate,cli}.py`;
  reuses Phase 04 schemas + Phase 10 hashed I/O; real run against the live lab with real container
  IPs, hash-verified read-back, tamper detection re-confirmed; `simulator/tests/test_ground_truth.py`;
  `docs/architecture/ground_truth.md`; `README.md` updated)
- Phase 17 — Ground-Truth Integrity (`experiments/artifacts/ground_truth_manifest.py`,
  `write_ground_truth_generation`/`read_ground_truth_generation` in
  `experiments/artifacts/io.py`, `scripts/check_ground_truth_boundary.py`; `cli.py` writes
  numbered generations instead of overwriting; real run against the live lab produced two
  independent, hash-verified generations for one capture_id; `simulator/tests/test_ground_truth_integrity.py`;
  `docs/architecture/ground_truth.md` updated; `README.md` updated)
- Phase 18 — Scenario Generator (`simulator/scenarios/{topologies,models,generate,compose,cli}.py`,
  `simulator/scenarios/generic_node/app.py`; all 6 required archetypes (simple chain, star,
  multi-tier, redundant, multi-path, dynamic service network) generated programmatically with a
  real NetworkX-verified structural property each; one new reusable generic container image;
  real `docker compose up` of a generated star-4 scenario with live reachability confirmed and
  ground truth captured; `simulator/tests/test_scenarios.py`;
  `docs/architecture/scenario_generation.md`; `docs/architecture/network_laboratory.md` updated;
  `README.md` updated)
- Phase 19 — Traffic Replay Engine (`simulator/traffic/replay.py`; deterministic schedule
  derivation from a recorded Phase 14/15 JSON-Lines log's `sent_at` timestamps, reusing Phase
  14/15's own request senders for real execution; real burst-pattern recording captured then
  replayed twice against the live lab, replay logs structurally identical excluding wall-clock
  fields; `simulator/tests/test_replay.py`; `docs/architecture/traffic_replay.md`; `README.md`
  updated)
- Phase 20 — Observatory Validation (`scripts/validate_observatory.py`; automates Phases 11-13/15's
  own manual verification procedures into one repeatable pass/fail gate covering expected
  services/connectivity/routes/traffic; real run against the live lab, all 5 checks passing, plus a
  deliberately induced failure (`load-balancer-2` stopped) proving the gate can actually detect a
  real problem; `simulator/tests/test_observatory_validation.py`;
  `docs/architecture/observatory_validation.md`; `README.md` updated)

- Phase 21 — High-Fidelity Packet Capture (`backend/nettrace/capture/{ingest,models,errors,
  authorized_interfaces}.py`, `simulator/capture/live.py`; the first NETTRACE phase — first real
  pipeline/inference code, as opposed to Phases 0-10's scaffolding and 11-20's lab-building).
  `POST /capture` (`backend/app/api/routes/capture.py`) is real for `source=pcap_upload`: validates
  a staged file as a genuine, non-empty pcap via Scapy's `PcapReader`, then ingests it into
  `experiments/artifacts`' canonical `captures/<capture_id>/raw.pcap` (Phase 10) plus a
  `CaptureManifest` (plain `write_json`, not ground truth). `source=live_interface` validates the
  requested interface against an allowlist (`backend/nettrace/capture/authorized_interfaces.py`,
  default `eth0`) and returns 202 documenting a real two-step lab-side workflow rather than
  pretending the backend itself opens a socket into a lab network namespace it has no access to
  (the backend and the lab run as two separate, unconnected Docker Compose projects — see
  `docs/architecture/packet_capture.md` for the full architecture decision). `simulator/capture/
  live.py` is the real Scapy `sniff()`/`wrpcap()` mechanics, meant to run inside the lab's `client`
  container (granted `cap_add: [NET_RAW, NET_ADMIN]` in `simulator/docker/docker-compose.yml`,
  plus a new `../../backend:/opt/netscope/backend:ro` mount so it can import
  `backend.nettrace.capture.{authorized_interfaces,errors}` -- both deliberately stdlib-only, no
  Pydantic, so `client`'s bare-Python image doesn't need the backend's full dependency stack).
  `scapy==2.6.1` added to `requirements.txt` (spec §6's first real use of its designated
  network-analysis library). Verified: `backend/tests/test_nettrace_capture.py` +
  `simulator/tests/test_capture.py` + updated `backend/tests/test_api.py` (153/153 combined, up
  from 136/136), plus a real, manual end-to-end run (no Docker needed for this half): a real
  Scapy-built pcap ingested through the live FastAPI app via `TestClient`, with the resulting
  `raw.pcap`/`manifest.json` confirmed on disk, alongside real 422/403 rejections for a missing
  file, an invalid pcap, and an unauthorized interface. **Not verified this phase**: an actual live
  capture against the real Docker lab -- this session's environment has no Docker installation at
  all (confirmed: `docker` not on PATH, no Docker Desktop install found), unlike the environment
  Phases 11-20 were verified in. Honestly reported as an open item rather than fabricated (spec
  Rule 2/3); see `docs/architecture/packet_capture.md` "Known limitations" and "Status".
- Phase 22 — Packet Normalization (`backend/nettrace/normalize.py`; `normalize_pcap(root,
  capture_id)`). Reads a real `raw.pcap` via Scapy's streaming `PcapReader` (same convention as
  Phase 21's `ingest.py`) and produces one frozen `Packet` (Phase 04 schema) per real captured
  frame that carries an IP layer: real timestamp, real src/dst IP, real ports, real protocol
  (TCP/UDP/ICMP/OTHER), real size (`wirelen`), and for TCP a real comma-separated flag string
  (e.g. `"SYN,ACK"`) built from Scapy's own flag representation. `direction` is always left
  `PacketDirection.UNKNOWN` -- it is documented as relative to a flow, and flows don't exist until
  Phase 23 groups packets by five-tuple; resolving it here would be a guess, not an observation.
  A frame without an IP layer (e.g. bare Ethernet/ARP) is skipped, not fabricated with a
  placeholder address. New `packets_path()` (`experiments/artifacts/paths.py`,
  `captures/<capture_id>/packets.jsonl`), written via the existing generic `write_jsonl` (not
  ground truth, no hash sidecar). No new API endpoint -- this is an internal pipeline step for
  Phase 23's future flow reconstruction, not one of the 12 fixed Phase 09 endpoint groups.
  Verified: `backend/tests/test_nettrace_normalize.py` (6/6: TCP/UDP/ICMP field extraction, real
  flag-string formatting, non-IP-frame skipping without breaking numbering, real capture-order
  `packet_id`s, full `write_jsonl`/`read_jsonl` round-trip); combined suite 159/159 (up from
  153/153), no regression; a real, manual end-to-end run (no Docker needed, same as Phase 21's
  `pcap_upload` half): a real 5-packet Scapy pcap (TCP handshake-style SYN/SYN-ACK/ACK, a UDP
  packet, an ICMP packet) ingested through the live FastAPI app's real `POST /capture`, then
  normalized -- every field confirmed exactly matching the synthetic input, both in memory and by
  reading back the real `packets.jsonl` written to disk. `docs/architecture/packet_normalization.md`
  has full detail.
- Phase 23 — Five-Tuple Flow Reconstruction (`backend/nettrace/reconstruct.py`;
  `reconstruct_flows(root, capture_id)`, per `docs/architecture/algorithm_selection.md` §1's
  selected five-tuple-hash-table algorithm). Groups TCP/UDP packets from Phase 22's `packets.jsonl`
  by a symmetric five-tuple key (so A->B and B->A packets land in the same bucket) and resolves
  each packet's `direction`: the first packet observed (earliest timestamp) in a group defines the
  canonical orientation (its tuple becomes `Flow.src_ip`/`src_port`/`dst_ip`/`dst_port`, matching
  every packet in that orientation gets `FORWARD`, the opposite gets `REVERSE`). Since `Packet` is
  frozen, direction resolution produces new instances via `model_copy`, rewritten to
  `packets_path()` in the original capture order (only `direction` changes). ICMP/OTHER packets are
  excluded from flow grouping (FR-1.3's literal TCP/UDP-only scope) and stay `UNKNOWN`. `Flow`
  objects get real-computed `FlowFeatures` for everything honestly computable now (packet/byte
  counts, duration, mean inter-arrival, forward_byte_ratio, and burstiness as a real
  coefficient-of-variation) while `destination_diversity`/`port_diversity` are correctly `1` (a
  flow has exactly one destination/port pair by definition) and `is_persistent` is a documented
  `False` (no cross-window recurrence signal exists within one capture -- real computation is
  Phase 28's job); `tcp_state`/`fingerprinted_protocol` stay `None`, explicitly Phase 24/26's jobs,
  matching the model's own "`None` means not yet determined" design. `GET /flows`
  (`backend/app/api/routes/flows.py`) is now real: 404 `capture_not_found`
  (`backend/nettrace/capture/errors.py`'s new `CaptureNotFoundError`) for an uningested capture_id,
  else runs `normalize_pcap` + `reconstruct_flows` fresh on every request (a documented
  recompute-on-read simplification, no job queue/cache) and paginates via the existing Phase 09
  `PageParams`/`PaginatedResponse`. Verified: `backend/tests/test_nettrace_reconstruct.py` (7/7:
  bidirectional merge, direction assignment, real feature arithmetic against hand-computed
  expected values, distinct-five-tuple separation, ICMP exclusion, `write_jsonl`/`read_jsonl`
  round-trip, original packet-order preservation); updated `backend/tests/test_api.py` (10
  still-501 groups unchanged, new real `/flows` tests: 404, a real 1-flow 3-packet result,
  pagination); combined suite 168/168 (up from 159/159), no regression; a real, manual end-to-end
  run (no Docker needed): a real 7-packet Scapy pcap (a 5-packet TCP exchange plus a 2-packet UDP
  exchange) ingested through the live FastAPI app's real `POST /capture`, then queried through the
  real `GET /flows` -- 2 real flows returned with byte-exact `FlowFeatures` (TCP:
  packet_count=5/byte_count=211/forward_byte_ratio=0.592...; UDP: packet_count=2/byte_count=56/
  burstiness=0.0), correct real initiator identified as canonical src/dst, and the real
  `packets.jsonl` on disk confirmed rewritten from Phase 22's `unknown` to correct `forward`/
  `reverse` directions in original order. `docs/architecture/flow_reconstruction.md` has full
  detail.

- Phase 24 — TCP State Tracking (`backend/nettrace/reconstruct.py`; `_compute_tcp_state`, per
  `docs/architecture/algorithm_selection.md` §1's selected TCP-finite-state-machine algorithm,
  FR-1.4). Called from `reconstruct_flows` for every TCP flow group (never for UDP, which stays
  structurally `None`, both by not calling the helper and via `Flow`'s existing
  `_tcp_state_only_for_tcp` validator), consuming the `PacketDirection` `reconstruct_flows` already
  resolves rather than re-deriving orientation. A single forward pass over each flow's
  timestamp-sorted packets tracks four booleans (`saw_syn`, `established`, `fwd_fin`, `rev_fin`) and
  derives one of `TCPState`'s 6 pre-declared values (Phase 04): any `RST` anywhere short-circuits to
  `RESET` immediately; a plain `ACK` after a `SYN`/`SYN,ACK` pair and before any `FIN` completes the
  handshake (`ESTABLISHED`); `FIN` from one direction only is `CLOSING`, from both is `CLOSED`; no
  `SYN` ever seen, or a `SYN` whose handshake never completes within the capture window, is honestly
  `PARTIAL` rather than a fabricated guess. Retransmission-safe by construction: every signal is a
  boolean, not a counter, so a retransmitted SYN/FIN in a direction already observed is a structural
  no-op, satisfying FR-1.4's "retransmissions" clause without needing a new schema field (none was
  reserved for one at Phase 04). Honest, explicitly documented limitation: real mid-stream TCP
  *data* retransmission detection (matching a resent sequence number) is not possible with the
  current schema, since `Packet` (Phase 22) carries no TCP sequence/ack field — only handshake/
  teardown-level retransmission safety (duplicate SYN/FIN) is real here, consistent with the
  project's metadata-only, non-payload-reassembly observability model. Verified:
  `backend/tests/test_nettrace_reconstruct.py` grew from 7/7 to 16/16 (the existing full-handshake
  test's `tcp_state` assertion corrected from Phase 23's honest `None` placeholder to the real
  `ESTABLISHED`; 9 new tests: `ESTABLISHED`/`CLOSING`/`CLOSED` from a real handshake+teardown
  sequence, `RESET` at three different points, `PARTIAL` for both "no SYN" and "incomplete
  handshake," duplicate-SYN and duplicate-FIN idempotency, UDP flows unaffected); one existing
  `backend/tests/test_api.py` assertion similarly corrected (its 3-packet real handshake now
  correctly asserts `tcp_state == "established"`); combined suite 177/177 (up from 168/168), no
  other regressions; `scripts.validate_data_contracts` and `check_ground_truth_boundary.py` both
  re-verified clean; a real, manual end-to-end run (no Docker needed): a real Scapy pcap with three
  distinct TCP exchanges (full handshake+data+FIN-both-sides, handshake+RST, bare mid-stream
  ACK-only with no SYN) ingested through the live FastAPI app's real `POST /capture`, then queried
  through the real `GET /flows` — all three real `tcp_state` outcomes confirmed exactly as expected
  (`"closed"`, `"reset"`, `"partial"`), and Phase 23's `packets.jsonl` direction resolution confirmed
  unaffected. `docs/architecture/tcp_state_tracking.md` has full detail.

- Phase 25 — UDP Session Modeling (`backend/nettrace/reconstruct.py`; `_split_udp_sessions`, per
  `docs/architecture/algorithm_selection.md` §1's selected timing-window-based UDP session grouping,
  FR-1.5). A UDP five-tuple's timestamp-sorted packets are now split into separate sessions wherever
  the gap to the next packet strictly exceeds a configurable idle-timeout — the "timing-window"
  heuristic layered on top of the five-tuple's own "endpoint, port" heuristic — with each session
  becoming its own `Flow` (no `Flow`/`Packet` schema changes needed; a session is represented exactly
  like a TCP flow already was, just with a UDP five-tuple now honestly able to produce more than
  one). `reconstruct_flows` restructured to build a flat list of units (one per TCP five-tuple, one
  per UDP session) before assigning flow indices, still ordered deterministically by each unit's own
  earliest packet timestamp. Canonical forward/reverse orientation is resolved per session, not per
  five-tuple, matching UDP's honest lack of a persistent "initiator" across an idle gap. The
  idle-timeout is configuration-driven per NFR-4: new `Settings.udp_session_idle_timeout_seconds`
  (`backend/app/core/config.py`), default `30.0`s (a documented, conntrack-convention-matching
  default, not a magic number), env-overridable as
  `NETSCOPE_UDP_SESSION_IDLE_TIMEOUT_SECONDS`, `gt=0`-validated, threaded explicitly from
  `GET /flows` (`backend/app/api/routes/flows.py`) into `reconstruct_flows`. `is_persistent` stays
  `False` for every flow including UDP sessions — a deliberate scoping decision, since FR-1.8's
  cross-observation-window recurrence (Phase 28's job) is a different concept from in-capture
  idle-gap session splitting. Verified: `backend/tests/test_nettrace_reconstruct.py` grew from 16/16
  to 22/22 (close-together UDP packets stay one session; an idle gap splits a five-tuple into two
  correctly-oriented sessions; boundary cases at exactly the timeout and one millisecond over; a TCP
  flow with an equally large gap stays unsplit; deterministic ordering across a mix of TCP and split
  UDP sessions); `backend/tests/test_config.py` grew from 9/9 to 11/11 (default value, `gt=0`
  rejection, env-var override); combined suite 185/185 (up from 177/177), no other regressions;
  `scripts.validate_data_contracts` and `check_ground_truth_boundary.py` both re-verified clean; a
  real, manual end-to-end run (no Docker needed): a real Scapy pcap with explicit per-packet
  timestamps — a UDP five-tuple with two 2-packet bursts separated by a gap comfortably past the real
  configured 30.0s default, plus a TCP flow with an equally large internal gap — ingested through the
  live FastAPI app's real `POST /capture`, then queried through the real `GET /flows`: the UDP
  five-tuple produced exactly 2 real flows (2 packets each), the TCP flow stayed exactly 1 real flow
  (4 packets, real `tcp_state: "closing"`), confirming the heuristic is real, correctly
  gap-triggered, and correctly UDP-only. `docs/architecture/udp_session_modeling.md` has full detail.

- Phase 26 — Protocol Fingerprinting (`backend/nettrace/fingerprint.py`; `fingerprint_protocol`,
  FR-1.6). Unlike Phases 23-25, `docs/architecture/algorithm_selection.md` (Phase 05) did not cover
  this area at all — an honest gap in the original planning, not silently worked around; the
  algorithm decision is made and justified in the new `docs/architecture/protocol_fingerprinting.md`
  instead. Since `Packet` carries no application-layer payload (metadata-only, consistent with the
  project's established non-payload-reassembly observability model), deep packet inspection is not
  possible, so the fingerprinter is a small, explicit `(transport, well-known port) -> protocol name`
  lookup table (`http`/TCP:80, `tls`/TCP:443, `postgresql`/TCP:5432, `redis`/TCP:6379, `dns`/UDP:53),
  scoped exactly to the protocols `simulator/traffic/protocols.py` (Phase 15) generates real traffic
  for, so every entry is independently end-to-end verifiable against known ground truth. Anything not
  in the table stays honestly `None`, never a guess — directly satisfying FR-1.6's "shall not claim
  protocol coverage it cannot support." Called from `reconstruct_flows` for every flow (TCP and UDP
  alike, unlike Phase 24's TCP-only `tcp_state`), using the flow's own canonical `dst_port` first,
  falling back to `src_port` for a reversed canonical orientation. No `Flow`/`Packet` schema changes
  needed (`Flow.fingerprinted_protocol` already existed from Phase 04). Verified: new
  `backend/tests/test_nettrace_fingerprint.py` (13/13: all 5 table entries, unrecognized port ->
  `None`, `dst_port`-then-`src_port` fallback priority, both ports `None` -> `None`, wrong transport
  for a well-known port -> `None`, plus 3 real `reconstruct_flows` integration cases); one existing
  `backend/tests/test_nettrace_reconstruct.py` assertion corrected from Phase 23's honest `None`
  placeholder (its fixture uses port 80) to the real `"http"`; combined suite 198/198 (up from
  185/185), no other regressions; `scripts.validate_data_contracts` and
  `check_ground_truth_boundary.py` both re-verified clean; a real, manual end-to-end run (no Docker
  needed): a real Scapy pcap with an HTTP-shaped exchange (TCP/80), a DNS-shaped exchange (UDP/53),
  and a generic TCP exchange on an unrecognized port (9999), ingested through the live FastAPI app's
  real `POST /capture`, then queried through the real `GET /flows` — all three real
  `fingerprinted_protocol` outcomes confirmed exactly as expected (`"http"`, `"dns"`, `None`).
  `docs/architecture/protocol_fingerprinting.md` has full detail, including an explicit "known
  limitations" section (non-standard-port services unrecognized; a different service squatting on a
  well-known port would be misidentified — both honest, documented heuristic limitations, not gaps).

- Phase 27 — Encrypted Traffic Metadata (`backend/nettrace/tls_metadata.py`; `extract_tls_versions`,
  FR-1.7). Four of FR-1.7's five named items (duration, sizes, timing, endpoint relationships) were
  already real via Phase 23/25's `Flow`/`FlowFeatures` fields; this phase supplies the fifth: real
  TLS version. Like Phase 26, `docs/architecture/algorithm_selection.md` (Phase 05) did not cover
  this area — another honest, noted planning gap, decided and documented in the new
  `docs/architecture/encrypted_traffic_metadata.md` instead. A TLS `ServerHello` handshake message is
  never encrypted in any TLS version, so parsing its cleartext header and (for TLS 1.3)
  `supported_versions` extension is genuine metadata extraction, not decryption — the legacy version
  field alone stays pinned to `0x0303` ("TLS 1.2") for compatibility even when 1.3 is actually
  negotiated, so the extension is checked first. `extract_tls_versions` independently re-reads
  `raw.pcap` directly via `PcapReader` (the same convention `normalize.py` already established),
  keeping the already-shipped, payload-free `Packet` schema (Phase 22) untouched; returns a
  `{(server_ip, server_port): version}` lookup that `reconstruct_flows` checks against both of a
  flow's canonical endpoints. `Flow` gained one new field, `tls_version: Optional[str]`, validated
  the same way `tcp_state` already is (`_tls_version_only_for_tcp`, mirroring
  `_tcp_state_only_for_tcp`); gracefully empty (not an error) when `raw.pcap` isn't present for a
  given `capture_id`, keeping every pre-existing test passing unchanged. Cross-checked against real
  lab ground truth: `simulator/traffic/protocols.py`'s `tls_handshake` (Phase 15) performs a genuine
  handshake whose real negotiated outcome (`docs/architecture/protocol_generation.md`) is
  `TLSv1.3`/`TLS_AES_256_GCM_SHA384` — this phase's manual verification constructs the exact TLS 1.3
  wire bytes to confirm the parser resolves that same real version via the extension path, not a
  simpler TLS ≤1.2 case. Honest, documented limitations: a `ServerHello` split across TCP segments
  isn't reassembled (stays `None`); only `ServerHello` is parsed, never `ClientHello` (which offers
  versions, not the negotiated one); TLS only, not other encrypted protocols. Verified: new
  `backend/tests/test_nettrace_tls_metadata.py` (9/9: TLS 1.0/1.1/1.2 via the legacy field, TLS 1.3
  via the `supported_versions` extension, non-Handshake/ClientHello/truncated/too-short →
  `None`, real pcap extraction); `backend/tests/test_nettrace_reconstruct.py` grew by 2 (a real
  crafted TLS 1.3 `ServerHello` alongside a seeded `raw.pcap` sets `tls_version == "TLS 1.3"`; no
  `raw.pcap` present keeps `tls_version` `None` with no exception); combined suite 209/209 (up from
  198/198), no other regressions; `scripts.validate_data_contracts` and
  `check_ground_truth_boundary.py` both re-verified clean; a real, manual end-to-end run (no Docker
  needed): a real pcap with a TCP/443 handshake, a real-shaped `ClientHello`, and a crafted
  `ServerHello` negotiating TLS 1.3 via its extension, ingested through the live FastAPI app's real
  `POST /capture`, then queried through the real `GET /flows` — confirmed both
  `fingerprinted_protocol == "tls"` (already real since Phase 26) and `tls_version == "TLS 1.3"`.
  `docs/architecture/encrypted_traffic_metadata.md` has full detail.

- Phase 28 — Flow Feature Completion (`backend/nettrace/reconstruct.py`; FR-1.8). Phase 23 left
  `destination_diversity`, `port_diversity`, and `is_persistent` as honest placeholders (`1`, `1`,
  `False`) because their real meaning needs information from other flows in the same capture, not just
  a single flow's own packets. `reconstruct_flows` is now a two-pass function: pass 1 resolves
  direction/TCP-state/fingerprint/TLS as before but defers `Flow` construction, accumulating three
  capture-wide aggregates (a `Counter` of how many units share each five-tuple key; per-canonical-`src_ip`
  sets of distinct destination IPs and ports seen); pass 2 builds every `Flow` using those now-complete
  aggregates. `destination_diversity`/`port_diversity` are the real distinct destination IP/port counts
  seen, within this capture, across every flow sharing a flow's own canonical `src_ip` (a source with no
  other flows still gets `1`/`1`, unchanged from before). `is_persistent` is `True` when a flow's own
  five-tuple recurs as more than one `Flow` within the capture — which, given how flows are
  structurally constructed, only ever fires for UDP (Phase 25's idle-timeout session splitting is the
  only mechanism that produces multiple `Flow`s from one five-tuple; TCP five-tuples never split). No
  new `Settings` field — this is a deterministic aggregation, not a tunable heuristic (NFR-4 doesn't
  apply). True cross-*capture* persistence (the same five-tuple recurring across separately-ingested
  captures) remains honestly out of scope: nothing correlates flows across different `capture_id`s.
  Verified: `backend/tests/test_nettrace_reconstruct.py` grew by 3 (real diversity counts across
  same-source/different-destination flows, same-destination/different-port flows, and unrelated
  sources not sharing aggregates), plus `is_persistent` assertions added to the existing UDP
  idle-gap-split test (`True` for both sessions) and single-session UDP test (`False`); combined suite
  212/212 (up from 209/209), no regressions; `scripts.validate_data_contracts` re-verified clean (no
  schema fields changed); a real, manual end-to-end run building a synthetic capture (two TCP flows
  from one source to two destinations, one UDP five-tuple idle-gap-split into two sessions) confirmed
  every aggregate matched hand-computed expected values exactly. `docs/architecture/flow_feature_completion.md`
  has full detail. This closes the last placeholder item from Phase 23's flow-reconstruction scope.

- Phase 29 — Node Discovery (`backend/nettrace/topology/{__init__,discovery}.py`; FR-1.9). The first
  topology-inference phase, and the first real use of the `Node` data contract since Phase 04.
  `discover_nodes(root, capture_id)` reads every packet in `packets.jsonl` (not `flows.jsonl`, so
  ICMP/OTHER-only hosts aren't missed the way flow reconstruction would miss them), tracks a running
  per-IP first/last-observed timestamp, and emits one deterministically-ordered/-ided `Node` per
  distinct IP address seen as a source or destination. No ground-truth access anywhere in the module
  (`scripts/check_ground_truth_boundary.py` confirms). Not yet wired into any API route or persisted
  to disk — both deferred to Phase 30 (edge discovery) and Phase 32 (combined `TopologyGraph`).
  Verified: new `backend/tests/test_nettrace_topology_discovery.py` (8/8: multiple distinct IPs each
  become their own node; first/last-observed correctly spans multiple packets for the same IP across
  both roles; two runs on identical input are byte-identical and a same-timestamp tie breaks
  lexicographically by IP; a missing `packets.jsonl` and an empty one both return `[]` without
  raising; an ICMP-only exchange's two endpoints are discovered as nodes even though the identical
  fixture produces zero flows via `reconstruct_flows`; a destination-only IP and a source-only IP are
  each still discovered); combined suite 220/220 (up from 212/212), no regressions;
  `scripts.validate_data_contracts` re-verified clean (38/38, `Node` unchanged since Phase 04);
  `scripts.check_ground_truth_boundary` re-verified clean. `docs/architecture/node_discovery.md` has
  full detail, including the packets-vs-flows algorithm justification.

- Phase 30 — Edge Discovery (`backend/nettrace/topology/edges.py`; FR-1.9/FR-1.10;
  `backend/app/core/config.py` gains `edge_confidence_packet_scale`). `discover_edges(root,
  capture_id, nodes, edge_confidence_packet_scale=20.0)` reads `flows_path` (not `packets_path` --
  the opposite of Phase 29), resolves each flow's `src_ip`/`dst_ip` against the caller-supplied
  `nodes` list, skips flows with an unresolved or self-referential endpoint (never raises), buckets
  the rest by canonical sorted node-pair, and aggregates each bucket into one `Edge`: `protocols`
  deduplicated/sorted, `first_observed`/`last_observed` spanning every contributing flow, `evidence`
  one descriptive line per flow ordered by `(first_seen, flow_id)`, `observation_count = len(flows)`,
  and `confidence = 1 - exp(-total_packet_count / edge_confidence_packet_scale)` where
  `total_packet_count` sums `Flow.features.packet_count` across the bucket -- monotonic and
  saturating by construction, explicitly flagged as provisional/uncalibrated pending Phase 31.
  Deterministic `edge_id = f"{capture_id}:edge:{index}"`, ordered by `(first_observed,
  source_node_id, target_node_id)`, mirroring Phase 29's own node-ordering convention. Verified: new
  `backend/tests/test_nettrace_topology_edges.py` (12/12: single and multiple distinct node-pair
  edges; multi-flow aggregation widening observation_count/evidence/timestamps; protocol
  dedup/growth across a TCP+UDP+TCP mix; deterministic ordering/ids across repeated runs; missing and
  empty `flows.jsonl` both returning `[]`; an ICMP-only capture producing nodes but zero edges;
  a self-referential flow producing no edge; confidence strictly higher for a heavily- vs.
  lightly-observed pair; confidence always in `[0, 1]` and never exactly `1.0` even for a 500-packet
  flow; a flow whose IP is absent from the supplied `nodes` contributing no edge); combined suite
  232/232 (up from 220/220), no regressions; `scripts.validate_data_contracts` re-verified clean
  (38/38, `Edge` unchanged since Phase 04); `scripts.check_ground_truth_boundary` re-verified clean.
  `docs/architecture/edge_discovery.md` has full detail, including the confidence-formula
  justification and the undirected-edge design decision.

- Phase 31 — Probabilistic Edge Confidence (`backend/nettrace/topology/edges.py`, same function
  modified, not a new one; FR-1.10; `backend/app/core/config.py` gains
  `edge_confidence_signal_strength`). Replaces Phase 30's single-signal `confidence` with a
  noisy-OR combination of Phase 30's packet-volume term and five new independent `Flow`-derived
  signals: `tcp_state == ESTABLISHED` (TCP only), `fingerprinted_protocol is not None`,
  `tls_version is not None` (TCP only), `features.is_persistent`, and a bidirectionality term
  (`2*min(forward_byte_ratio, 1-forward_byte_ratio)`, peaking at balanced traffic). All four boolean
  signals share one uniform `edge_confidence_signal_strength` (default `0.3`) rather than per-signal
  weights, since nothing yet justifies weighting one signal above another. `confidence =
  1 - (1-p_volume) * prod(1 - s*indicator)`: bounded to `[0,1)` and monotonic by construction (every
  term in `[0,1)`, so the product only shrinks as evidence grows), and a structurally-inapplicable
  signal (e.g. TCP-only signals on a UDP-only bucket) contributes a neutral identity factor, never a
  penalty. `evidence` gained per-flow signal facts plus one bucket-level summary line. Explicitly
  still provisional/uncalibrated -- RQ1 defers ground-truth-based calibration to Phase 32/68, and
  REPRO-4 forbids ground truth at inference time, so this phase mirrors `algorithm_selection.md`
  §6's "multi-signal, interpretable, evidence-backed" pattern (a different phase/field,
  `DependencyEdge.strength`) rather than attempting real statistical calibration. Verified: revised
  `backend/tests/test_nettrace_topology_edges.py` (20/20: the 12 Phase 30 tests, one updated for
  `evidence`'s new length, plus 8 new -- established-vs-partial, TLS-vs-none,
  fingerprinted-vs-not, and bidirectional-vs-one-way comparisons each isolating one signal at equal
  packet counts; a pure-math combined-signal monotonicity test; an all-positive-signals-exceeds-
  packet-volume-alone test; a UDP-only edge reaching high confidence via non-TCP signals with no
  penalty for inapplicable TCP-only signals; the evidence summary line's presence/content); combined
  suite 240/240 (up from 232/232), no regressions; `scripts.validate_data_contracts` re-verified
  clean (38/38, `Edge` unchanged since Phase 04); `scripts.check_ground_truth_boundary` re-verified
  clean. `docs/architecture/edge_discovery.md` (updated in place, not a new doc) has full detail,
  including three worked numeric examples.

- Phase 32 — Probabilistic Topology Reconstruction (`backend/nettrace/topology/graph.py`;
  `backend/app/api/routes/topology.py`, now real; `experiments/metrics/topology_comparison.py`;
  FR-1.11). `build_topology_graph` combines Phase 29's `discover_nodes` and Phase 30-31's
  `discover_edges` into one `TopologyGraph` -- pure assembly, no new inference logic. `GET /topology`
  mirrors `GET /flows` exactly (404 `capture_not_found`; `normalize_pcap` + `reconstruct_flows` run
  inline; recomputed fresh every call) and persists the result via `write_json(topology_path(...),
  graph)` -- a write-through research artifact, not a cache; the route never reads it back.
  `graph_id = capture_id`: a stable, non-timestamped, non-content-hashed identity label (rejected a
  timestamp for breaking NFR-3 determinism, and a content hash for making identity unstable across
  mere `Settings` tuning), mirroring ground truth's own constant `graph_id="lab-ground-truth"`.
  Separately, `compare_topology_to_ground_truth` (new `experiments/metrics/` package -- the first real
  population of that spec-named-but-previously-empty directory) compares an inferred `TopologyGraph`
  against a ground-truth one: since the two sides' `node_id`/`edge_id` schemes are independently
  generated and not comparable (lab service names vs. positional inference ids), matching goes through
  resolved `Node.ip_addresses` -- exact set equality for nodes, unordered IP-pair for edges
  (deliberately ignoring declared direction, since ground truth is directed-by-declaration while
  inference is undirected-by-design per Phase 30). Reports real node/edge precision/recall/F1 plus
  `graph_similarity = (node_f1 + edge_f1) / 2` (equal weighting, no basis yet to prefer one over the
  other -- the same reasoning already used for Phase 31's noisy-OR signals), returned as a plain
  `TopologyComparisonResult` dataclass rather than a `MetricResult` (whose required `experiment_id`
  has no real experiment registry to anchor to yet -- fabricating one would violate spec §21 "No Fake
  Metrics"). Never imported by anything under `backend/` -- verified by
  `scripts.check_ground_truth_boundary`. Verified: `backend/tests/test_api.py`'s new
  `# --- Phase 32: GET /topology real behavior ---` section (4/4: 404 on unknown capture; a real
  `POST /capture` -> `GET /topology` producing a real graph with every edge's confidence/evidence/
  protocols populated; deterministic `graph_id`/nodes/edges across repeated calls; persistence
  round-tripping via `read_json`); new `experiments/tests/test_topology_comparison.py` (5/5: perfect
  match gives all metrics 1.0; ground-truth-only extra node/edge drops recall not precision;
  inferred-only extra node/edge drops precision not recall; empty-vs-empty/empty-vs-nonempty handled
  per documented convention; edge matching ignores declared direction); combined suite 248/248 (up
  from 240/240), no regressions; `scripts.validate_data_contracts` re-verified clean (38/38, no schema
  changes); `scripts.check_ground_truth_boundary` re-verified clean. `docs/architecture/
  topology_reconstruction.md` has full detail, including a worked directed-vs-undirected edge-matching
  example. No Docker in this session's environment, so no end-to-end run against real lab ground truth
  was performed -- comparison verified against synthetic `TopologyGraph` fixtures only, consistent with
  every other Docker-dependent phase's own limitation note.

- Phase 33 — Behavioral Feature Store (`backend/flowmind/features/node_features.py`, new
  `backend/flowmind/` package; FR-1.12). `compute_node_behavioral_features(flows, node) ->
  NodeBehavioralFeatures` computes six real, evidence-derived features per node from a
  caller-supplied `Flow` list: `distinct_ports` (destination-side ports only -- a node's own
  listening-port set, deliberately excluding a client's ephemeral source ports, which would dilute
  the signal); `distinct_protocols` (both directions); `distinct_destinations` (outbound/node-as-source
  flows only -- fan-out, not inbound popularity); `mean_flow_duration_seconds`; `outbound_byte_ratio`
  (real per-flow `forward_byte_ratio` reused, flipped when the node is the canonical destination);
  `is_persistent_talker` (any-flow-exhibits-it existence semantics, the same convention already
  established for Phase 31's noisy-OR signal indicators). Covers exactly the feature vocabulary
  `docs/architecture/algorithm_selection.md` §2 already committed Phase 36-37's future role classifier
  to (port set entropy, protocol mix, traffic directionality, persistence, destination diversity) --
  no new feature invented. Deliberately window-agnostic (filters only by node-IP membership, never by
  time) and returns a plain `NodeBehavioralFeatures` dataclass, not a `BehavioralFingerprint` --
  window-boundary decisions (Phase 34) and fingerprint assembly/persistence (Phase 35) are explicitly
  out of scope, consistent with every prior phase's narrow spec-line scoping. Verified: new
  `backend/tests/test_flowmind_node_features.py` (9/9: destination-only port counting; cross-direction
  protocol aggregation; outbound-only destination counting; correct duration averaging; a
  hand-computed `outbound_byte_ratio` of 0.7; persistent-talker detection; honest zero values for a
  zero-flow node; unrelated flows contributing nothing; a real end-to-end run through
  `reconstruct_flows`/`discover_nodes`); combined suite 257/257 (up from 248/248), no regressions;
  `scripts.validate_data_contracts` re-verified clean (38/38, no schema changes -- this phase
  populates no Pydantic model); `scripts.check_ground_truth_boundary` re-verified clean.
  `docs/architecture/behavioral_feature_store.md` has full detail, including the Phase 33/34/35
  scope-boundary argument.

## Blocked phases

None.

## Known bugs

None yet — no code written.

## Architecture decisions

- Project interpreter will be pinned to Python 3.12.10 (system also has 3.14.7 available, but 3.12
  is the safer target for the pinned scientific stack: NumPy, SciPy, NetworkX, Scapy).
- Local dev virtual environment created at `.venv/` (Python 3.12.10), with `pydantic==2.9.2` pinned
  in `requirements.txt` — first real dependency of the project.
- `backend/app/models/` is the single shared location for all cross-module data contracts (Pydantic
  v2). NETTRACE, FLOWMIND, Archaeology, Causal, PathForge, Counterfactual, Experiments, and the API
  layer all import schemas from here rather than redefining their own. Rationale and full schema
  reference: `docs/architecture/data_contracts.md`.
- Data contracts encode several spec non-negotiable rules structurally (via required fields / model
  validators) rather than by convention alone — e.g., `Edge` cannot exist without `evidence`,
  `Anomaly.evidence` cannot be empty, `CounterfactualScenario.isolated_graph_id` cannot equal
  `baseline_graph_id`, `MetricResult` cannot exist without an `experiment_id`. See
  `docs/architecture/data_contracts.md` "Design principle" section for the full list.
- Remainder of the full 25-section project tree (`nettrace/`, `flowmind/`, `archaeology/`, `causal/`,
  `pathforge/`, `counterfactual/`, `simulator/`, `experiments/`) still intentionally NOT created —
  those directories are justified once the phases that populate them (07+) are reached.
- Backend dependencies pinned in `requirements.txt` (FastAPI 0.115.5, Uvicorn 0.32.1, Pydantic 2.9.2,
  NetworkX 3.4.2, NumPy 2.1.3, Pandas 2.2.3, SciPy 1.14.1) and `requirements-dev.txt` (pytest 8.3.3,
  httpx 0.27.2) — the full spec §6 preferred backend baseline.
- `frontend/` scaffolded with React 18.3.1 + TypeScript 5.6.3 + Vite 5.4.21 + Tailwind CSS 3.4.14 +
  Cytoscape.js 3.30.2 (pinned exact versions, per spec §6; explicitly not Streamlit). Only a
  placeholder page exists; real UI areas start Phase 12.
- `backend/app/main.py` is a Phase 06 placeholder FastAPI app (`/health` only) that exists solely to
  give the Docker image something real to run — it is not the Phase 09 API and will be replaced, not
  extended, when Phase 09 starts.
- Dev-only Docker setup: `backend/Dockerfile`, `frontend/Dockerfile`, `docker-compose.yml` (backend +
  frontend containers). This is separate from and not a substitute for the multi-tier network
  laboratory built in Phase 11 (`simulator/docker/`).
- Known accepted risk: `npm audit` reports a moderate esbuild/Vite dev-server advisory
  (GHSA-67mh-4wv8-2f99) with no fix available short of a Vite 8 major upgrade; not applied this phase.
  Documented in `docs/development/environment.md`.
- Observability (`backend/app/core/`, Phase 07): structured JSON logging via a single `JsonFormatter`
  (every module logs the same format); `contextvars`-based `request_id`/`experiment_id` propagation
  (`context.py`) so any log call in the current async task automatically carries the current IDs
  without explicit passing; `get_logger(__name__)` as the standard module-logger entry point;
  `log_exception()` for structured error reporting; `Timer`/`@timed` (`timing.py`) for performance
  timing, feeding the future PERF-1..7 measurements. Wired into `backend/app/main.py` via ASGI
  middleware that assigns a request ID, times the request, and echoes the ID back as an
  `X-Request-ID` header. Known constraint: contextvars do not auto-propagate across manually spawned
  threads/processes — not yet relevant since no such code exists.
- Configuration (`backend/app/core/config.py`, Phase 08): `pydantic-settings`-based `Settings`, all
  variables read with an `NETSCOPE_` prefix; `environment` (development/test/production) selects
  `.env.{environment}` (falling back to `.env`) via `get_settings()`. `secret_key` is a `SecretStr`
  and a model validator refuses to construct `Settings` with `environment="production"` while it
  still holds the documented insecure placeholder — a hard startup failure, not a silent gap.
  `.env.example` and `.env.test` are committed (no secrets in them); `.env`/`.env.production` are
  gitignored and were never created. `backend/app/main.py` now derives its log level from
  `get_settings()`.
- API architecture (`backend/app/api/`, Phase 09): all 12 spec-required endpoint groups
  (capture/flows/topology/behaviors/anomalies/history/dependencies/causal/simulation/counterfactual/
  experiments/metrics) mounted under versioned `/api/v1`. Every handler currently raises
  `NotYetImplemented` (real 501, not fake data) since the pipeline stages that would serve real
  results (Phase 21+) don't exist yet. One shared `ErrorResponse` envelope for 501/422/500. Pagination
  via shared `PageParams`/`PaginatedResponse[T]`. Request/response schemas reuse Phase 04
  `backend.app.models` types where they fit. Known simplification: `/simulation` and
  `/counterfactual` currently accept the full domain object as the request body rather than a
  dedicated slim "create" DTO — flagged for revisit alongside their real implementation.
- Research artifact architecture (`experiments/artifacts/`, Phase 10): file-based (JSON / JSON Lines),
  not a database, per spec §6's minimum-necessary-infrastructure principle. `paths.py` fixes the
  on-disk layout (`captures/<id>/{raw.pcap,flows.jsonl,topology/*.json,snapshots/*.json}`,
  `ground_truth/<id>/topology.json(+.sha256)`, `experiments/<id>/{experiment.json,metrics.jsonl}`),
  always parameterized by an explicit `root` (never hardcoded). `io.py` provides generic
  `write_json`/`read_json`, `write_jsonl`/`read_jsonl`, and `write_ground_truth`/`read_ground_truth`
  (the latter pair writes/verifies a SHA-256 sidecar on every read, raising
  `GroundTruthIntegrityError` on tamper or a missing sidecar — the concrete Phase 17 ground-truth
  integrity mechanism, built now for phases 16+ to use). No PCAP I/O or dataset registry exists yet
  (Phase 21 and Phase 19 respectively) — only the path convention and generic JSON/JSONL layer are
  established this phase.
- Multi-tier network laboratory (`simulator/docker/`, Phase 11): 10-service Docker Compose lab
  (client, gateway, load-balancer, api-1, api-2, redis, database, worker, dns, external-service) on
  one network (`netscope-x-lab`), separate from Phase 06's dev-only root `docker-compose.yml`. `api-1`/
  `api-2` perform real TCP/HTTP reachability checks (redis/database/external-service) and report them
  as JSON, making the dependency structure genuinely observable end-to-end, not just declared.
  Verified: full client→gateway→load-balancer→api→{redis,database,external} request chain (twice,
  confirming real round-robin between api-1/api-2); DNS resolution via dnsmasq; worker heartbeat log.
  Network-namespace isolation and routing are explicitly Phase 12/13, not duplicated here.
- Network namespace isolation (`simulator/docker/docker-compose.yml`, Phase 12): the Phase 11 lab's
  single flat network replaced in place with 4 tiered networks (edge/app/data/external); only
  boundary-crossing containers (gateway, api-1, api-2, worker) are multi-homed. Verified both that
  intended paths still work (client→gateway→LB→api→{redis,db,external} unchanged) and that
  boundaries are actually enforced: client/gateway/load-balancer all fail (DNS resolution timeout,
  not just TCP block) when attempting to reach services outside their assigned networks.
  `docker network inspect` membership and `ip addr` interface counts (client: 1 interface;
  api-1: 3 interfaces) confirmed as real routing evidence, not just declared compose intent.
- Routing laboratory (`simulator/docker/`, Phase 13): added `load-balancer-2` (same nginx image/config
  as `load-balancer`); `gateway/nginx.conf`'s single `proxy_pass` became an `upstream` pool of both,
  with short connect/read timeouts and an `X-Gateway-Upstream` response header exposing the actual
  route chosen. Verified real alternation across both routes; stopped `load-balancer-2` without
  restarting `gateway` (live topology change) and confirmed 6/6 requests still succeeded — one
  showing the explicit failover trail in its header, the rest landing directly on the surviving
  route; confirmed recovery after restart. Found and documented a real gotcha: restarting `gateway`
  while a peer container is stopped is fatal (`nginx: host not found in upstream`) because Docker
  removes a stopped container's DNS entry and nginx resolves upstream hostnames once at config-load
  time — the proxy must stay running through a peer failure, not be restarted.
- Traffic workload generator (`simulator/traffic/`, Phase 14): `patterns.py` provides a pure,
  seed-reproducible `generate_schedule(pattern, seed, duration)` for all 6 required patterns (normal,
  burst, periodic, concurrent, idle, degraded); `generate.py` executes a schedule in real time via
  stdlib `urllib` against a real target, writing JSONL logs. Reproducibility is explicitly scoped to
  the *schedule*, not real execution timing/network variance (documented, not overclaimed). `client`
  (Phase 11) gained `python3` + a read-only mount of `simulator/` to run the generator in-lab. Verified:
  19/19 unit tests (determinism, per-pattern shape) plus a real run of 3 patterns against the live lab
  (48 real HTTP 200s total across normal/burst/concurrent, with burst/concurrent's clustering visibly
  confirmed in captured timestamps).
- Protocol workload generator (`simulator/traffic/`, Phase 15): `protocols.py` provides real
  wire-level senders for HTTP, generic TCP, UDP/DNS (hand-built RFC 1035 query), cache (raw RESP
  PING/PONG), database (real Postgres SSLRequest handshake), and TLS (real handshake, reports
  negotiated version/cipher). `external-service` gained a self-signed-cert HTTPS listener (port 443,
  lab-only). Key finding: protocol reachability is topology-dependent post-Phase-12 segmentation --
  `client` reaches HTTP/DNS/TCP (edge), `api-1` reaches cache/database/TLS (data+external); no single
  container reaches all 6, documented as a realistic finding, not a gap. Verified: 8/8 pure unit tests
  (DNS wire-format, Postgres magic-number correctness) plus a real run of all 6 protocols against the
  live lab (real DNS rcode=0, real Redis +PONG, real Postgres 'N' response, real negotiated
  TLSv1.3/TLS_AES_256_GCM_SHA384).
- Ground-truth generator (`simulator/ground_truth/`, Phase 16): lives outside `backend/` deliberately
  (spec §4 -- no importable path from future inference code into ground truth). `topology.py`
  declares the lab's true roles/edges (reviewable, hardcoded, cross-checked against
  `docker-compose.yml`'s real service list on every run); `generate.py` builds a `TopologyGraph`
  (Phase 04 schema, confidence=1.0 throughout), `GroundTruthRoles`, and `GroundTruthPaths` (real
  NetworkX/Dijkstra shortest paths -- Phase 05's selected algorithm's first real use); `cli.py`
  resolves real container IPs via `docker ps`/`docker inspect` (not a naming-convention guess) and
  persists all three through Phase 10's hashed `write_ground_truth`. `PyYAML` promoted from a
  transitive to an explicit pin (`requirements.txt`) since ground-truth generation now directly
  parses `docker-compose.yml`. Verified: 9/9 pure unit tests plus a real run against the live 11-
  container lab (real distinct IPs matching Phase 12's subnets, e.g. redis/database on
  172.22.0.0/16; hash-verified read-back of all 3 files; tamper detection re-confirmed on a real
  generated artifact, then restored). `experiments_data/` (generated output) added to `.gitignore`.
- Ground-truth integrity (`experiments/artifacts/{ground_truth_manifest,io,paths}.py`,
  `scripts/check_ground_truth_boundary.py`, Phase 17): closes the two gaps Phase 16 left open.
  (1) Versioning: `write_ground_truth_generation`/`read_ground_truth_generation` add a
  hash-protected `manifest.json` recording every generation for a `capture_id`, each written to
  its own `ground_truth/<capture_id>/v<N>/` directory that earlier generations never overwrite;
  reading cross-checks the manifest's recorded hash against each artifact's own sidecar hash (a
  manifest edited out of sync with its artifact is now also detected, not just a single tampered
  file). `simulator/ground_truth/cli.py` now writes one generation per run instead of overwriting
  three flat files. (2) Structural safeguard: `scripts/check_ground_truth_boundary.py` statically
  walks every `.py` file via `ast` and fails if anything outside the spec-sanctioned allowlist
  (`simulator/`, `experiments/`, `scripts/`, any `tests/` dir) imports `simulator.ground_truth` —
  inference code doesn't exist yet (Phase 21+), so this currently passes trivially, but is a real,
  exercised guardrail (proven against both the real repo and a synthetic violation) rather than an
  assumption. Verified: 11/11 new unit tests; real run against the live lab generating v1 then v2
  for the same capture_id (v1 confirmed byte-for-byte unchanged after v2 was written); tamper
  detection re-confirmed on the real versioned artifact; lab torn down after.
- Scenario generator (`simulator/scenarios/`, Phase 18): 6 pure, parameterized generators
  (`simulator/scenarios/topologies.py`) produce `(roles, edges)` for simple_chain/star/multi_tier/
  redundant/multi_path/dynamic_service_network, generalizing `simulator/ground_truth/topology.py`'s
  hand-declared-constants pattern into callable-with-parameters. Persisted as `ScenarioDeclaration`
  (roles+edges, Pydantic/JSON) rather than a `TopologyGraph` -- a not-yet-deployed scenario has no
  real observed IP to put in `Node.ip_addresses`, and inventing one would be fake data disguised as
  real output (spec Rule 3); `build_topology_graph` (real `TopologyGraph`) is only called once a
  scenario is actually deployed, reusing `simulator.ground_truth.cli.docker_ip_lookup` unchanged.
  One new reusable building block, `simulator/scenarios/generic_node/app.py` (data-driven
  `NODE_ROLE`/`UPSTREAM_HOSTS` env vars, live JSON reachability report), fills the gap that no
  service in the fixed Phase 11 lab is generic/reusable -- every one hardcodes its specific peers.
  `simulator/scenarios/compose.py` generates a real, deployable `docker-compose.yml` per scenario
  from this image, following the fixed lab's own convention (off-the-shelf image + mounted script,
  no bespoke Dockerfile); absolute host paths in the generated compose file, same assumption every
  other `experiments_data/` artifact already makes (only portable on the generating machine).
  Verified: 15/15 unit tests (real NetworkX structural property per archetype -- star hub degree,
  multi_path node-connectivity, redundant bridge-freeness, multi_tier tier-crossing, simple_chain
  path simplicity, dynamic_service_network determinism); real `generate-all` run producing all 6
  scenarios; real `docker compose up` of the generated star-4 scenario (5 containers), live
  reachability confirmed from inside the hub container (`reachability: {leaf-1..4: true}`), ground
  truth captured with 5 distinct real container IPs, torn down after.
- Traffic replay engine (`simulator/traffic/replay.py`, Phase 19): reads back a Phase 14 pattern
  log or Phase 15 protocol log (auto-detected by record shape) and re-derives a replay schedule
  from each record's `sent_at` timestamp (not `scheduled_offset_seconds`, which only exists in
  Phase 14 logs and represents the pre-execution plan rather than what was actually observed) --
  `load_recording` is pure arithmetic, so it is provably deterministic across repeated loads of
  the same file. `run()` reuses Phase 14's `generate._send_request` and Phase 15's
  `generate_protocol._send` rather than reimplementing request logic. Does not introduce a new
  Pydantic schema or `experiments/artifacts/` path convention -- replay logs stay outside that
  scheme, consistent with how Phase 14/15's own generator logs are written directly to an
  arbitrary `--out` path. Verified: 10/10 unit tests (offset derivation for both log shapes,
  load-twice determinism, malformed/missing-field/unknown-protocol rejection, blank-line
  skipping); real run against the live lab -- a real burst-pattern recording (14 real requests,
  all HTTP 200) replayed twice from `client`, the two replay logs structurally identical
  excluding wall-clock-only fields (proving determinism concretely, not just asserting it), and
  real observed inter-arrival jitter of roughly 2-18ms against the original recording (honestly
  reported, not hidden); lab torn down after.
- Observatory validation (`scripts/validate_observatory.py`, Phase 20): a standalone,
  argument-free script (same convention as `validate_data_contracts.py`/
  `check_ground_truth_boundary.py`) that automates Phases 11-13/15's own one-off manual lab
  verification into one repeatable gate: expected services (reuses Phase 16's
  `check_services_match_compose` unchanged), expected connectivity positive+negative (reruns Phase
  11/12's `curl` chain and boundary checks), expected routes (reruns Phase 13's
  `X-Gateway-Upstream` alternation check), expected traffic (reruns Phase 15's
  `generate_protocol.py` as a one-shot smoke test per reachability-correct container/protocol
  pair). Kept as a standalone script rather than a pytest addition -- there is no existing
  precedent in this project for a Docker-dependent pytest fixture, so the Docker-touching parts
  stay in the script and only the pure parsing/decision logic each check reduces to
  (`_evaluate_reachability_payload`, `_parse_upstream_header`, `_summarize_protocol_attempt`) is
  unit-tested. Scoped to the fixed Phase 11-13 lab only, not Phase 18's independently-deployed
  generated scenarios (already explicitly out of scope per `network_laboratory.md`'s "Explicitly
  deferred" section). Verified: 16/16 unit tests; a real run against the live lab with all 5
  checks passing (real JSON reachability report, real DNS-resolution-failure boundary
  enforcement, real observed upstream alternation, real DNS/HTTP/cache/database/TLS traffic
  attempts); a deliberately induced failure (`load-balancer-2` stopped) confirmed the routes
  check's output honestly reflects nginx's own failover-trail behavior (a degraded-but-succeeding
  header, matching Phase 13's own documented finding) rather than being smoothed over, then
  recovery was confirmed after restarting the container; lab torn down after.
- Algorithm selections (`docs/architecture/algorithm_selection.md`, Phase 05): five-tuple hash table +
  TCP FSM for flow reconstruction; Naive-Bayes-style probabilistic classifier for role inference;
  per-dimension robust statistical baseline + set-difference novelty detection for anomaly detection;
  exact NetworkX degree/betweenness/articulation-points for graph criticality; Dijkstra + Yen's
  algorithm + BFS/union-find for path analysis; weighted multi-signal scoring (frequency, persistence,
  directionality, time-lagged cross-correlation) for dependency inference. Heavier alternatives
  (Random Forest, Isolation Forest/autoencoders, Granger causality/PC algorithm) are documented as
  deferred options pending Phase 68 evidence, not adopted or dismissed without justification.

## Environment inspection (Phase 0 findings)

- OS: Windows 11 Home Single Language, build 10.0.26200
- Docker: 29.7.2 (installed, Docker Desktop)
- Python: 3.12.10 and 3.14.7 both on PATH
- Node.js: v22.14.0
- npm: 10.9.2
- git: 2.55.0.windows.5
- Chrome: installed at `C:\Program Files\Google\Chrome\Application\chrome.exe` (not on PATH; usable
  via Playwright / claude-in-chrome for later frontend testing phases)
- Repository: `D:\Netscope-X`, git-initialized, previously empty aside from the master spec PDF
  (`NETSCOPE (1).pdf`)

## Current test status

- `scripts/validate_data_contracts.py` — 38/38 checks passed (re-verified against a freshly recreated
  `.venv`, Phase 06).
- `pytest backend/tests experiments/tests` — 48/48 passed: 3 environment smoke tests (Phase 06) + 10
  observability tests (Phase 07) + 9 configuration/secrets tests (Phase 08) + 18 API architecture
  tests (Phase 09) + 8 research artifact tests (Phase 10: round-trip I/O for flows/graphs/snapshots/
  experiments/metrics, plus ground-truth tamper and missing-sidecar detection).
- `frontend`: `npm run build` (tsc type-check + Tailwind + Vite production bundle) succeeds.
- `docker compose build` succeeds for both `backend` and `frontend` images; `docker compose up`
  verified both containers actually serve traffic (`/health` returns `{"status":"ok"}`, frontend
  preview returns HTTP 200), then torn down.
- `scripts/setup.sh` run standalone from a clean state (`.venv` and `frontend/node_modules` deleted
  first) and completed successfully — the "fresh installation must work" acceptance bar for Phase 06.
- `pytest simulator/tests` — 88/88 passed: 19 traffic-pattern tests (Phase 14) + 8 protocol
  wire-format tests (Phase 15) + 9 ground-truth tests (Phase 16) + 11 ground-truth integrity tests
  (Phase 17: versioning round-trips, manifest/artifact hash cross-check, boundary-checker real-repo
  scan + synthetic-violation detection) + 15 scenario generator tests (Phase 18: real NetworkX
  structural property per archetype, declaration/role builders, topology-graph construction) +
  10 traffic replay tests (Phase 19: offset derivation from `sent_at` deltas for both pattern-log
  and protocol-log shapes, load-twice determinism, malformed/missing-field/unknown-protocol
  rejection with line numbers, blank-line skipping, frozen dataclass equality) + 16 observatory
  validation tests (Phase 20: reachability-payload evaluation, upstream-header parsing,
  protocol-attempt summarization), all pure/no-Docker.
  Plus real Docker-based runs: 3 traffic patterns (Phase 14), all 6 protocols
  (Phase 15), a full ground-truth generation (Phase 16, with hash-verified read-back and
  tamper-detection re-confirmed), two successive ground-truth generations for one capture_id
  (Phase 17, v1 confirmed unchanged after v2 was written, tamper detection re-confirmed on the
  versioned layout), a full `generate-all` + real deploy of the generated star-4 scenario
  (Phase 18, live reachability confirmed, ground truth captured with 5 real container IPs, torn
  down), a real burst-pattern recording replayed twice against the live lab (Phase 19, 14/14
  real requests both times, replay-1 and replay-2 logs structurally identical excluding
  wall-clock-only fields, real observed inter-arrival jitter of roughly 2-18ms against the
  original recording), and a full observatory-validation run (Phase 20, all 5 checks passing
  against the live lab, plus a deliberately induced `load-balancer-2` outage confirming the
  script can actually detect a real problem, then recovery confirmed) — not part of the pytest
  suite, manual integration verification like Phases 11-13.
- `python scripts/check_ground_truth_boundary.py` (Phase 17) — run standalone, zero violations found
  in the real repository (including the new `simulator/scenarios/` package, correctly inside the
  allowlist).
- `python -m scripts.validate_observatory` (Phase 20) — run standalone against the live lab,
  5/5 checks passed (see Phase 20 note above for detail).
- `pytest backend/tests experiments/tests simulator/tests` (combined) — 209/209 passed, no
  regression (up from 136/136 after Phase 20: +9 `backend/tests/test_nettrace_capture.py`,
  +2 `simulator/tests/test_capture.py`, +7 net new/changed `backend/tests/test_api.py` capture
  cases minus the 1 removed generic-501 case, Phase 21; +6 `backend/tests/test_nettrace_normalize.py`,
  Phase 22; +7 `backend/tests/test_nettrace_reconstruct.py`, +2 net new `/flows` cases in
  `backend/tests/test_api.py` minus the 1 removed generic-501 case, Phase 23; +9
  `backend/tests/test_nettrace_reconstruct.py` TCP state cases, Phase 24, with one Phase 23 test's
  `tcp_state` assertion in that file and one in `backend/tests/test_api.py` corrected from Phase
  23's honest `None` placeholder to the real computed value; +6
  `backend/tests/test_nettrace_reconstruct.py` UDP session-splitting cases and +2
  `backend/tests/test_config.py` idle-timeout config cases, Phase 25; +13 new
  `backend/tests/test_nettrace_fingerprint.py`, Phase 26, with one Phase 23
  `fingerprinted_protocol` assertion corrected from `None` to the real `"http"`; +9 new
  `backend/tests/test_nettrace_tls_metadata.py` and +2 new
  `backend/tests/test_nettrace_reconstruct.py` TLS-version integration cases, Phase 27).
- `python -m scripts.validate_data_contracts` — 38/38 passed, no regression (Phase 21, re-verified
  Phase 22-27).
- `python scripts/check_ground_truth_boundary.py` — clean, zero violations; `backend/nettrace/`
  (including `normalize.py`, `reconstruct.py`, `fingerprint.py`, and the new `tls_metadata.py`) and
  `simulator/capture/` packages correctly do not import `simulator.ground_truth` (Phase 21,
  re-verified Phase 22-27).
- Multi-tier lab (`simulator/docker/`): verified through Phase 13 (11 containers, 4 segmented
  networks, load-balancer failover) and exercised again in Phase 14 with real generated traffic; torn
  down after each verification run — nothing left running between sessions.

## Current datasets

None yet — datasets are introduced starting Phase 14/16/19.

## Current metrics

None yet — no experiments have been run.

## Pending work

- Verify `simulator/capture/live.py`'s controlled live capture against a real Docker lab (bring up
  `simulator/docker/docker-compose.yml`, confirm `client`'s real interface name, run a real capture
  while Phase 14's traffic generator runs, verify the pcap's packets against real container IPs)
  once Docker is available in the working environment — see `docs/architecture/packet_capture.md`
  "Known limitations". Not blocking Phase 22, since Phase 22 (Normalization) consumes any real
  `captures/<capture_id>/raw.pcap`, regardless of whether it arrived via `pcap_upload` or a
  completed live-capture-then-upload workflow.
- Real mid-stream TCP data-retransmission detection (by duplicate sequence number) remains out of
  scope: `Packet` carries no TCP sequence/ack field. Documented as an honest limitation in
  `docs/architecture/tcp_state_tracking.md`, not a gap; would require extending `Packet`'s schema
  and `normalize.py` if a later phase's requirements actually need it.
- Protocol fingerprinting is a small, explicit port/transport heuristic table, honestly limited to 5
  protocols verifiable against the lab's real Phase 15 traffic generator (`http`, `tls`,
  `postgresql`, `redis`, `dns`); a service on a non-standard port, or a different service reusing a
  well-known port, is out of scope by design — documented in
  `docs/architecture/protocol_fingerprinting.md`, not a gap.
- Encrypted traffic metadata's TLS version extraction is honestly limited: a `ServerHello` split
  across TCP segments isn't reassembled (stays `None`), and only `ServerHello` is parsed, never
  `ClientHello` (which offers versions, not the negotiated one) — documented in
  `docs/architecture/encrypted_traffic_metadata.md`, not a gap.
- Flow feature completion's `is_persistent` only ever fires for UDP, and true cross-*capture*
  persistence (the same five-tuple recurring across separately-ingested captures) remains out of
  scope — documented in `docs/architecture/flow_feature_completion.md`, not a gap.
- Node discovery (Phase 29) treats one observed IP as exactly one node; NAT/multi-homed-host
  correlation is out of scope pending additional evidence a future phase's requirements would need to
  justify — documented in `docs/architecture/node_discovery.md`, not a gap.
- Edge discovery (Phase 30) reports edges as undirected (no initiator claim) — documented in
  `docs/architecture/edge_discovery.md`, not a gap.
- Edge confidence (Phase 31) combines six real signals via noisy-OR with one uniform strength
  constant (`edge_confidence_signal_strength`, default `0.3`) rather than empirically-justified
  per-signal weights, and `is_persistent`'s contribution is structurally UDP-only (Phase 28's own
  scope) — both documented in `docs/architecture/edge_discovery.md` as explicitly provisional, real
  calibration deferred to Phase 32/68's ground-truth-backed evaluation, not a gap.
- Topology comparison (Phase 32) measures only structural node/edge presence, not attribute agreement
  (protocol correctness, confidence accuracy) — a natural Phase 68 extension, not a gap. Its
  `graph_similarity` equal-weighting formula is a documented, provisional choice pending empirical
  validation, and no end-to-end run against real Docker-lab ground truth was performed this phase (no
  Docker in this session's environment) — documented in `docs/architecture/topology_reconstruction.md`.
- Behavioral features (Phase 33) don't yet account for a node with multiple correlated IP addresses
  (Phase 29's "one IP → one Node" simplification still applies) — inherited, not introduced, by this
  phase; documented in `docs/architecture/behavioral_feature_store.md`.
- Next: Phase 34 (Multi-Window Behavior Modeling). Expected to decide the three
  `ObservationWindow` (short/medium/long) boundaries and invoke Phase 33's
  `compute_node_behavioral_features` once per window per node — not yet scoped beyond FR-1.12's
  parenthetical mention. Not started; awaiting explicit request.
