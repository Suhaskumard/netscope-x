# NETSCOPE-X — Project State

This file is the single source of truth for project progress across the 69-phase execution plan
defined in the master spec (`NETSCOPE (1).pdf`). Update it after every phase.

## Current phase

Phase 54 (Failure Propagation Graph) complete, tested. New `backend/dependency/
failure_propagation.py` (`propagate_failure`) is the first real use of
`backend/app/models/failure.py`'s `PropagationImpact`/`ImpactOrder` (Phase 04, docstring-tagged
"spec Phase 54, 61", never constructed anywhere before this). A real, previously-undocumented
design decision: propagates over Phase 53's `List[CausalCandidate]`, not raw
`List[DependencyEdge]` -- `Edge`/`DependencyEdge.source_node_id`/`target_node_id` are undirected
(`discover_edges` assigns them by alphabetically sorting the node-id pair, not by any real
dependency direction), so following a raw `DependencyEdge`'s `source -> target` would often mean
propagating in a direction with zero supporting evidence (`temporal_precedence_score == 0.0`) --
an artifact of alphabetical sorting, not a causal claim. `CausalCandidate`s are exactly the subset
where `source -> target` carries genuine, positive temporal-precedence evidence, making this the
only edge set in the codebase where "if source fails, target is impacted" is actually justified.
Algorithm: primary impact is the failed node itself; secondary/tertiary are a breadth-first
traversal over `source_node_id -> target_node_id`, exactly two hops deep (matching the spec's
literal three-order list, no further cascading); each node visited at most once (first
order/candidate wins, so cycles never loop and diamond patterns never double-count); fully
deterministic processing order (frontier sorted by node id, each node's outgoing candidates sorted
by `dependency_id`). Every non-primary impact's evidence cites the specific candidate's real
strength/temporal-precedence values. Returns `[PRIMARY only]` for no outgoing candidates or empty
input, never an error. No new `Settings` field -- governed entirely by Phase 53's own threshold. No
persistence, no API wiring -- `POST /simulation` stays untouched, explicitly scoped to "spec Phase
59-61" in its own docstring. See `docs/architecture/failure_propagation_graph.md` for the full
design, the undirected-edge argument, worked example, and verification record. Phase 21
(High-Fidelity Packet Capture)'s one open item still stands: controlled live capture is implemented
and unit-verified but not yet verified against a real Docker lab (this session's environment has no
Docker installation — see `docs/architecture/packet_capture.md` "Known limitations").

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

- Phase 34 — Multi-Window Behavior Modeling (`backend/flowmind/features/windows.py`;
  `backend/app/core/config.py` gains `behavior_window_{short,medium,long}_seconds`; FR-1.12).
  `compute_node_features_for_window`/`compute_node_features_all_windows` invoke Phase 33's
  `compute_node_behavioral_features` once per `ObservationWindow`, using a trailing window anchored
  on the node's own latest observed activity (not capture-wide, not calendar time) -- making
  `long ⊇ medium ⊇ short` by construction. Default durations 10s/60s/300s: short/medium
  evidence-graded against this repo's own real capture/test timescales
  (`simulator/capture/live.py`, `simulator/tests/test_patterns.py`); long is an explicit,
  documented extrapolation with no direct repo evidence. A new `Settings.model_validator` enforces
  strictly increasing order across the three durations. `flows_touching_node` extracted from Phase
  33's `node_features.py` (behavior-preserving refactor) for reuse by the windowing code. Still
  produces `Dict[ObservationWindow, NodeBehavioralFeatures]`, not a `BehavioralFingerprint` --
  fingerprint assembly/persistence remains Phase 35's job. Verified: new
  `backend/tests/test_flowmind_windows.py` (8/8: trailing short window excludes an older flow;
  anchor confirmed to be the node's own activity, not unrelated later traffic elsewhere in the flow
  list; the three windows confirmed strictly nested via a hand-constructed timestamp spread;
  `compute_node_features_all_windows` returns exactly three keys; a zero-flow node returns honest
  zeros for all windows; a custom `window_seconds` override changes the windowing; defaults match
  `Settings`; a real end-to-end run through `reconstruct_flows`/`discover_nodes` with a
  deliberately-45s-later second flow, confirmed excluded from short but included in medium/long);
  Phase 33's own `test_flowmind_node_features.py` re-run (9/9) confirming the `flows_touching_node`
  extraction didn't change established behavior; combined suite 265/265 (up from 257/257), no
  regressions; `scripts.validate_data_contracts` re-verified clean (38/38, no schema changes);
  `scripts.check_ground_truth_boundary` re-verified clean. `docs/architecture/
  multi_window_behavior_modeling.md` has full detail, including the nesting-vs-partitioning design
  argument.

- Phase 35 — Node Behavioral Fingerprints (`backend/flowmind/fingerprints/node_fingerprint.py`, new
  `backend/flowmind/fingerprints/` package; `experiments/artifacts/paths.py` gains
  `fingerprints_path`; FR-1.13). `assemble_node_fingerprint(flows, node, window, window_seconds=None,
  computed_at=None) -> BehavioralFingerprint` calls Phase 34's `compute_node_features_for_window` and
  wraps its output verbatim into a real `BehavioralFingerprint` (`node_id`/`window`/`computed_at`
  added, six feature fields copied unchanged via `**asdict(features)`). `assemble_all_node_
  fingerprints(flows, nodes, ...)` produces one fingerprint per node per window (all three, not a
  single default -- Phase 34's own output was explicitly per-window), sharing one `computed_at` per
  batch call. Persisted via a new `fingerprints_path` (`captures/<capture_id>/fingerprints.jsonl`)
  and the existing generic `write_jsonl`/`read_jsonl` -- no new I/O primitives. `GET
  /behaviors/{node_id}` stays a 501 stub: its `NodeBehavior { fingerprint, role }` response, fixed at
  Phase 09, also requires a `RoleClassification` that doesn't exist until Phase 36-37 -- a structural
  blocker on the route's own contract, not a scope decision this phase made; wiring it now would mean
  fabricating a role. Verified: new `backend/tests/test_flowmind_fingerprints.py` (7/7: assembled
  fingerprint fields exactly match `compute_node_features_for_window`'s own output; identity fields
  set correctly with `computed_at` bounded by real before/after timestamps; a 2-node batch produces
  exactly 6 fingerprints covering all three windows per node; one shared `computed_at` per batch; zero
  nodes returns `[]`; fingerprints round-trip through `write_jsonl`/`read_jsonl` byte-for-byte equal;
  a real end-to-end run through `reconstruct_flows`/`discover_nodes` producing `len(nodes)*3` valid
  fingerprints); combined suite 272/272 (up from 265/265), no regressions; `scripts.
  validate_data_contracts` re-verified clean (38/38, `BehavioralFingerprint` schema unchanged);
  `scripts.check_ground_truth_boundary` re-verified clean. `docs/architecture/
  node_behavioral_fingerprints.md` has full detail, including the structural argument for why the API
  route stays unwired.

- Phase 36 — Service Role Inference (`backend/flowmind/classification/role_classifier.py`, new
  `backend/flowmind/classification/` package; FR-1.14). Implements `algorithm_selection.md` §2's
  already-selected Naive-Bayes-style classifier: `fit_role_model(labeled, variance_floor=1e-6,
  laplace_smoothing=1.0) -> RoleModel` fits per-role Gaussian likelihoods (4 continuous features --
  `distinct_destinations`, `mean_flow_duration_seconds`, `outbound_byte_ratio`, `port_count`) and
  Laplace-smoothed Bernoulli likelihoods (7 binary features -- `is_persistent_talker`, 4
  protocol-presence flags, 5 well-known-port-presence flags reusing Phase 26's exact
  `fingerprint.py` table) plus frequency-based priors, from labeled `(BehavioralFingerprint,
  ServiceRole)` pairs; raises `ValueError` on empty input (a classifier cannot be fit from nothing).
  `classify_node_role(model, fingerprint, computed_at=None) -> RoleClassification` computes real
  Bayes-rule log-posteriors and normalizes via a numerically-stable softmax into a genuine
  `RoleClassification` (its own Phase 04 validator is the real acceptance test). §2's own selection
  requires training on "a held-out labeled split of lab-generated data" -- no Docker this session
  means no real lab traffic exists to label, so `fit_role_model` (which takes labels as a plain
  parameter, never reading `simulator.ground_truth` itself) is verified only against synthetic
  labeled fixtures this session, the same convention every phase's tests already use. No model
  trained on real data is shipped; `GET /behaviors/{node_id}` stays a 501 stub. FR-1.14's
  "calibrated" requirement is only partially satisfied -- the posterior is real, not fabricated, but
  not yet validated as calibrated against ground truth, explicitly Phase 37's job (mirrors the Phase
  30->31->32/68 edge-confidence precedent). Verified: new
  `backend/tests/test_flowmind_role_classifier.py` (7/7: empty-input `ValueError`; two
  clearly-separated synthetic profiles -- DNS-like and Database-like -- each classify correctly on
  held-out data; `role_probabilities` always valid; a single-training-example role still classifies
  via the variance floor; two profiles differing *only* in protocol correctly isolate the
  protocol-mix signal; deterministic output across repeated calls; a real pipeline-types
  end-to-end test via `assemble_node_fingerprint` from constructed `Flow`/`Node` data); combined
  suite 279/279 (up from 272/272), no regressions; `scripts.validate_data_contracts` re-verified
  clean (38/38, `RoleClassification` schema unchanged); `scripts.check_ground_truth_boundary`
  re-verified clean. `docs/architecture/service_role_inference.md` has full detail, including the
  feature-engineering mapping and the Phase 36 vs. 37 calibration-boundary argument.

- Phase 37 — Uncertainty-Aware Classification (`backend/flowmind/classification/role_classifier.py`,
  extended; new `experiments/metrics/role_calibration.py`; FR-1.14). Half A (inference-side):
  `fit_temperature` fits a single scalar temperature via a self-contained two-pass log-spaced grid
  search minimizing NLL on held-out labeled data (no new `scipy` dependency); `classify_node_role`
  gained an optional `temperature=1.0` parameter, default unchanged from Phase 36. `_log_posteriors`/
  `_softmax` extracted from the prior inline implementation (behavior-preserving -- Phase 36's 7
  original tests re-verified unchanged). Half B (evaluation-only): `evaluate_role_calibration`
  computes real accuracy/Brier score/expected calibration error from `RoleClassification` vs.
  true-role labels, returned as a plain `RoleCalibrationEvaluation` dataclass -- not `MetricResult`,
  mirroring Phase 32's precedent (`MetricResult.experiment_id` still has no registry;
  `MetricResult.calibration_error`'s own docstring already scopes it to Phase 68). Never reachable
  from any API route. No Docker this session means no real temperature was fit or real calibration
  measured against real lab data -- both verified only against synthetic labeled fixtures. `GET
  /behaviors/{node_id}` remains a 501 stub, unchanged. Verified: `backend/tests/
  test_flowmind_role_classifier.py` grew to 12/12 (7 original + 5 new: empty-input `ValueError` for
  `fit_temperature`; fitting never worse than unscaled NLL; temperature scaling's flatten/sharpen
  property verified directly against `_softmax` with hand-picked log-posteriors, since real
  classifier output on cleanly-separated synthetic classes saturates to exact 1.0/0.0 at float
  precision; non-default-temperature output still schema-valid; log-posteriors finite and covering
  all roles); new `experiments/tests/test_role_calibration.py` (5/5: confident-correct predictions
  score well; confident-but-wrong predictions score strictly worse on all three metrics; empty input
  and mismatched lengths both raise `ValueError`; a hand-computed 4-sample accuracy/Brier score match
  exactly); combined suite 289/289 (up from 279/279), no regressions; `scripts.
  validate_data_contracts` re-verified clean (38/38, no schema changes); `scripts.
  check_ground_truth_boundary` re-verified clean. `docs/architecture/
  uncertainty_aware_classification.md` has full detail.

- Phase 38 — Behavioral Baseline (`backend/flowmind/baseline/node_baseline.py`, new
  `backend/flowmind/baseline/` package; FR-1.15). `build_node_baseline(fingerprint_history,
  min_observations=5) -> NodeBehavioralBaseline` implements `algorithm_selection.md` §3's
  already-selected robust median/MAD baseline + historical-set novelty tracking, covering all 6
  `BehavioralFingerprint` fields (4 continuous via median/MAD including `port_count` as Phase 36's
  entropy proxy reused; 2 set-valued via historical union for novelty checks; 1 boolean via historical
  frequency). Raises `ValueError` on empty input or a history mixing more than one `node_id`/`window`.
  `mad` reported honestly un-floored; cold-start exposed via `observation_count`/`is_sufficient`. Pure
  function over caller-supplied history -- no cross-capture fingerprint store exists yet, building one
  is out of scope. EWMA-based drift-vs-transient logic explicitly deferred to Phase 39. No persistence,
  plain dataclass output (no Phase 04 schema reserved for this). Verified: new `backend/tests/
  test_flowmind_baseline.py` (8/8: empty/mixed-node/mixed-window `ValueError`s; median/MAD exactly
  matching a hand-computed value; historical ports/protocols union correctly accumulated; persistent-
  talker frequency exact; cold-start `is_sufficient` threshold behavior; a real end-to-end-shaped test
  via `assemble_node_fingerprint`); combined suite 297/297 (up from 289/289), no regressions;
  `scripts.validate_data_contracts` re-verified clean (38/38, no schema changes); `scripts.
  check_ground_truth_boundary` re-verified clean. `docs/architecture/behavioral_baseline.md` has full
  detail, including the Phase 38 vs. 39 scope-boundary argument.

- Phase 39 — Concept Drift Detection (`backend/flowmind/drift/node_drift.py`, new
  `backend/flowmind/drift/` package; FR-1.16). `track_feature_drift(baseline, feature_name,
  observed_values, alpha=0.05, drift_threshold_mads=2.0, mad_floor=1e-6) -> DriftTrackingResult` runs
  an incremental EWMA seeded at a Phase 38 `RobustFeatureBaseline`'s median over a new observation
  sequence, classifying `CONCEPT_DRIFT` if the final EWMA ends up `>= drift_threshold_mads` baseline
  MADs from the original median, else `TRANSIENT_ANOMALY` -- implements `algorithm_selection.md` §3's
  named EWMA mechanism exactly, using only the EWMA's own slow rate against the static Phase 38
  baseline (no second "anomaly-detection window" rate needed, since Phase 40 doesn't exist yet to
  define one). Raises `ValueError` on empty input. `track_node_drift(baseline, new_fingerprints, ...)
  -> Dict[str, DriftTrackingResult]` batches this across the 4 continuous `NodeBehavioralBaseline`
  features, guarding against `node_id`/`window` mismatches. Populates the real `AnomalyClass` enum
  (`backend/app/models/anomaly.py`, Phase 04) for the first time. Explicit, documented precondition:
  meaningful only on an already-deviating sequence -- deciding whether a sequence deviates at all is
  Phase 40's job; ordinary non-deviating input vacuously classifies `TRANSIENT_ANOMALY`. No
  persistence. Verified: new `backend/tests/test_flowmind_drift.py` (9/9: empty-input `ValueError`;
  a reverting blip classifies transient; a sustained 20-step shift classifies drift; EWMA trace
  matches a hand-computed value exactly (`[15.0, 17.5, 18.75]`); `track_node_drift`'s empty/
  node_id-mismatch/window-mismatch `ValueError`s; coverage of all 4 continuous features; a mixed
  scenario correctly separates a drifting feature from a stable one); combined suite 306/306 (up
  from 297/297), no regressions; `scripts.validate_data_contracts` re-verified clean (38/38, no
  schema changes -- `AnomalyClass` populated, not modified); `scripts.check_ground_truth_boundary`
  re-verified clean. `docs/architecture/concept_drift_detection.md` has full detail, including the
  worked EWMA example.

- Phase 40 — Multi-Dimensional Anomaly Detection (`backend/flowmind/anomaly/node_anomaly.py`, new
  `backend/flowmind/anomaly/` package; edits to `backend/flowmind/features/node_features.py`,
  `backend/app/models/behavior.py`, `backend/flowmind/baseline/node_baseline.py`,
  `backend/flowmind/drift/node_drift.py`; FR-1.17). `detect_node_anomalies(baseline, fingerprint,
  z_threshold=3.0, novelty_scale=1.0, mad_floor=1e-6) -> List[Anomaly]` implements
  `algorithm_selection.md` §3's two selected mechanisms: robust z-score deviation (`DESTINATIONS`,
  `TIMING`, `BEHAVIOR`, `TRAFFIC_VOLUME`) and set-difference novelty (`PORTS`, `PROTOCOLS`). Closed
  the `TRAFFIC_VOLUME` gap by adding `total_byte_count` (defaulted `0`, backward-compatible) to
  `NodeBehavioralFeatures`/`BehavioralFingerprint`/`NodeBehavioralBaseline`, and to Phase 39's
  `track_node_drift` (now 5 continuous features, one existing test assertion widened accordingly).
  Explicitly never produces `AnomalyDimension.TOPOLOGY` -- documented scope-out, deferred to Phase
  45's graph-diff machinery (`GraphChangeEvent`/`NetworkSnapshot`, reserved since Phase 04,
  unimplemented). Score formula reuses Phase 30's `1 - exp(-x/scale)` saturating curve. Cold-start
  guarded via Phase 38's `is_sufficient`. `detect_node_anomalies_with_drift(baseline,
  new_fingerprints, ...)` upgrades a single-fingerprint check's provisional `TRANSIENT_ANOMALY` label
  to a real classification via a genuine call into Phase 39's `track_feature_drift` over the full
  sequence. Verified: new `backend/tests/test_flowmind_anomaly.py` (12/12: cold-start `[]`;
  `DESTINATIONS` evidence_values matching spec Phase 41's own worked example format; `TIMING`/
  `BEHAVIOR`/`TRAFFIC_VOLUME` z-score anomalies; `PORTS`/`PROTOCOLS` novelty anomalies firing only
  for genuinely new values; scores bounded in `[0,1)` without float-saturation at a realistic
  baseline MAD; `detect_node_anomalies`'s always-`TRANSIENT_ANOMALY` default; `detect_node_
  anomalies_with_drift`'s real upgrade to `CONCEPT_DRIFT` on a sustained sequence; `TOPOLOGY` never
  produced; a real end-to-end run through `assemble_node_fingerprint`); re-verified Phase
  33/38/39 suites (26/26: `test_flowmind_node_features.py`, `test_flowmind_baseline.py`,
  `test_flowmind_drift.py`, confirming the schema extension broke nothing); combined suite 318/318
  (up from 306/306), no regressions; `scripts.validate_data_contracts` re-verified clean (38/38,
  `Anomaly` schema unchanged, `BehavioralFingerprint`'s new field additive); `scripts.
  check_ground_truth_boundary` re-verified clean. `docs/architecture/
  multidimensional_anomaly_detection.md` has full detail, including both gap-resolution arguments.

- Phase 41 — Explainable Anomalies (`backend/flowmind/anomaly/node_anomaly.py`, evidence-formatting
  fix, same functions modified not new ones; new `backend/flowmind/anomaly/explain.py`; FR-1.18).
  Fixed a real formatting divergence: Phase 40's continuous-feature evidence always used `.3f`
  (`"4.000"`), drifted from Phase 04's own contract example
  (`scripts/validate_data_contracts.py`'s `"historical_destinations": "4"`) -- a new `_format_value`
  renders whole numbers as clean integers, keeping 3-decimal precision only for genuinely fractional
  values (`z_score` always keeps it). Novelty checks (`PORTS`/`PROTOCOLS`) gained a symmetric
  `current_<label>_count` alongside the existing `historical_<label>_count`, using data the function
  already had in hand. New `format_anomaly_report(anomalies: List[Anomaly]) -> str` renders any
  same-`node_id` `Anomaly` list into the master spec's own literal PHASE 41 worked-example block
  (`Node: / <Label>: <value> lines / Evidence: bullet lines`), deriving field labels generically from
  each anomaly's `evidence_values` keys -- no per-dimension hardcoding. Raises `ValueError` on an
  empty list or a list spanning more than one `node_id`, matching this project's established
  fail-fast convention. Deliberately no new detection signal: FR-1.18's own text asks for "historical
  vs. current destination counts" and "specific new ports observed," both already true from Phase 40;
  specific new-*destination*-identity tracking (the spec's illustrative "New destination: X") is an
  honest, documented, deliberately out-of-scope limitation for a later phase (confirmed with the
  user before implementation), not silently added or silently skipped. No persistence or API wiring
  -- `GET /anomalies` remains a 501 stub. Verified: updated `backend/tests/test_flowmind_anomaly.py`
  (2 assertions corrected from the drifted `.3f` values to clean integers; 2 new assertions for the
  added `current_<label>_count` keys); new `backend/tests/test_flowmind_anomaly_explain.py` (7/7:
  empty-list and mixed-node_id `ValueError`s; a single `DESTINATIONS` anomaly renders clean
  `Node:`/`Historical destinations:`/`Current destinations:`/`Evidence:` lines; a single `PORTS`
  anomaly names the specific new port plus before/after counts; a combined `DESTINATIONS`+`PORTS`
  report for one node reproduces the master spec's own worked-example shape; deterministic output
  across repeated calls; a real end-to-end run through `build_node_baseline`/`detect_node_anomalies`,
  not hand-built fixtures, confirming the formatting fix against genuinely detector-produced
  evidence); combined suite 325/325 (up from 318/318), no regressions; `scripts.
  validate_data_contracts` re-verified clean (38/38, `Anomaly` schema unchanged); `scripts.
  check_ground_truth_boundary` re-verified clean; a real, manual end-to-end run (no Docker needed)
  built a synthetic fingerprint history for node `API-2`, triggered a `DESTINATIONS` + `PORTS`
  anomaly with the master spec's own example numbers (historical destinations 4, current 9, new port
  4444), and confirmed the rendered report visually matches the spec's literal PHASE 41 worked
  example. `docs/architecture/explainable_anomalies.md` has full detail, including the scope-decision
  argument and the worked example.

- Phase 42 — FLOWMIND Evaluation (new `experiments/metrics/anomaly_evaluation.py`; FR-1.19; RQ3).
  `evaluate_anomaly_detection(detected: List[Anomaly], labeled_events: List[LabeledAnomalyEvent],
  total_checks=None) -> AnomalyDetectionEvaluation` scores real Phase 40 detector output against
  caller-supplied labeled ground truth (`LabeledAnomalyEvent(node_id, dimension, onset_at)` --
  deliberately minimal, since no injected-anomaly dataset generator exists anywhere in this repo;
  RQ3's own `dataset_anomaly`/`dataset_noisy` remain future work, not this phase's job). Matching is
  greedy per `(node_id, dimension)`: each label claims at most one detection (the earliest with
  `detected_at >= onset_at`); an early detection cannot be credited and itself becomes a false
  positive. `precision`/`recall`/`f1`/`false_negative_rate` are always real and computable (`0.0`
  convention when a denominator is structurally empty, e.g. zero detections at all -- never a
  fabricated `1.0`); `false_positive_rate` needs a countable negative-instance universe that
  `detected`/`labeled_events` alone can't supply, so it stays honestly `None` unless the caller
  supplies `total_checks` (the real number of node×dimension checks actually run), from which
  `true_negative_count = total_checks - TP - FP - FN` (raises `ValueError` if negative);
  `mean_detection_latency_seconds` is `None` with zero true positives, never `0.0`. Mirrors Phase
  32/37's established "plain dataclass, not `MetricResult`" precedent exactly --
  `MetricResult.experiment_id` is still required and no experiment registry exists anywhere in this
  repo (`Experiment`, Phase 04, is never constructed for real anywhere). `GET /metrics` untouched,
  already explicitly scoped to Phase 68 in its own docstring. Verified: new `experiments/tests/
  test_anomaly_evaluation.py` (10/10: perfect detection scores precision/recall/f1 all `1.0`; a
  missed label drops recall only; a spurious detection drops precision only; a pre-onset detection
  counts as neither a match nor a free pass -- the label becomes a false negative AND the early
  detection becomes a false positive; empty `labeled_events` raises `ValueError`; a hand-computed
  mean detection latency across two true positives matches exactly; zero true positives leaves mean
  latency `None`; `false_positive_rate` is `None` without `total_checks` and real with it; an
  inconsistent `total_checks` raises `ValueError`; a real end-to-end run through
  `build_node_baseline`/`detect_node_anomalies`, not hand-built `Anomaly` fixtures, scores a
  genuinely detector-produced anomaly as a true positive with real, non-fabricated latency); combined
  suite 335/335 (up from 325/325), no regressions; `scripts.validate_data_contracts` re-verified
  clean (38/38, no schema changes this phase); `scripts.check_ground_truth_boundary` re-verified
  clean; a real, manual end-to-end run (no Docker needed) built a synthetic fingerprint history for
  node `API-2`, triggered a real `DESTINATIONS` anomaly detected 6 seconds after a labeled onset, and
  confirmed real `precision=1.0`/`recall=1.0`/`f1=1.0`/`mean_detection_latency_seconds=6.0` plus a
  real `false_positive_rate=0.0` with `total_checks=50` supplied. `docs/architecture/
  flowmind_evaluation.md` has full detail, including the matching algorithm, the
  `MetricResult`-vs-dataclass argument, and the worked example.

- Phase 43 — Temporal Graph Model (`backend/nettrace/topology/{discovery,edges,graph}.py`, same
  functions modified, not new ones; FR-1.20; the first phase of the new "Temporal Intelligence
  (Network Archaeology)" section). `discover_nodes`/`discover_edges`/`build_topology_graph` each
  gained a backward-compatible `as_of: Optional[datetime] = None` parameter: `discover_nodes`
  filters packets to `timestamp <= as_of` before its existing first/last-observed aggregation;
  `discover_edges` filters flows to `first_seen <= as_of` before bucketing (the identical inclusion
  rule, so nodes and edges agree on "existed as of `as_of`"); `build_topology_graph` threads
  `as_of` into both. Confidence/evidence are genuinely recomputed from the narrower evidence set,
  not filtered after the fact -- rejected the cheaper "filter an already-built graph" alternative
  because an edge's confidence is itself computed from all its contributing flows, so post-hoc
  filtering would silently overstate certainty at time `t`; genuine recomputation lets confidence
  legitimately grow between two `as_of` values (Phase 31's noisy-OR formula is monotonic in
  evidence). `as_of=None` (default) reproduces the exact prior, whole-capture behavior --
  `build_topology_graph(..., as_of=t)` is literally G(t). Deliberately narrow scope, confirmed
  against `backend/app/models/snapshot.py`'s own docstring: `NetworkSnapshot` (versioned identity/
  persistence) is explicitly Phase 44's job, `GraphChangeEvent` (structural diffing) is explicitly
  Phase 45's job -- neither touched. No new `backend/archaeology/` package created (an intentional,
  explained departure from the "first phase of a section gets its own package" pattern of Phase
  21/33) -- it stays justified for Phase 44, when `NetworkSnapshot` persistence needs a genuine new
  home with no fit in `nettrace/`. `GET /topology` untouched -- no `as_of` query parameter, since a
  time-bounded graph has no stable identity yet without Phase 44's versioning. Verified: extended
  `backend/tests/test_nettrace_topology_discovery.py` (8/8 -> 12/12: a node whose only packet is
  after `as_of` excluded; `as_of` exactly equal to a packet's timestamp included, inclusive
  boundary; `last_observed` correctly narrows; `as_of=None` matches the unbounded call
  byte-for-byte); extended `backend/tests/test_nettrace_topology_edges.py` (20/20 -> 23/23: a flow
  starting after `as_of` excluded, changing edge count/protocols; confidence at an earlier `as_of`
  is `<=` confidence once later flows are visible, matching the fully-unbounded call exactly once
  all flows included; `as_of=None` matches unbounded); new `backend/tests/
  test_nettrace_topology_graph.py` (6/6, the first dedicated unit-test file for
  `build_topology_graph` itself -- its Phase 32 coverage previously lived only in `test_api.py`'s
  `GET /topology` section): before/between/after a two-episode synthetic capture produce
  correctly-scoped graphs; node/edge counts grow monotonically across three `as_of` points;
  omitting `as_of`, passing it explicitly as `None`, and passing a far-future `as_of` all agree
  exactly; a missing capture returns an empty graph regardless of `as_of`; combined suite 348/348
  (up from 335/335), no regressions; `scripts.validate_data_contracts` re-verified clean (38/38, no
  schema changes); `scripts.check_ground_truth_boundary` re-verified clean; a real, manual
  end-to-end run (no Docker needed) built a synthetic capture with two time-separated episodes and
  confirmed the printed node/edge/confidence output across four `as_of` points exactly matched the
  doc's worked example. `docs/architecture/temporal_graph_model.md` has full detail, including the
  scope-boundary argument against Phase 44/45 and the recompute-vs-filter design decision.

- Phase 44 — Network Snapshot Engine (new `backend/archaeology/{__init__,snapshots}.py`, the first
  real code in a new package; `experiments/artifacts/paths.py` gains `snapshots_dir`; FR-1.21).
  `create_snapshot(root, capture_id, captured_at=None, ...)` finally connects three pieces each
  already designed for this moment: `NetworkSnapshot` (Phase 04, never constructed for real
  anywhere before this), `snapshot_path` (reserved since Phase 10, never called anywhere before
  this), and Phase 43's `as_of`-aware `build_topology_graph`. `captured_at` (default
  `datetime.now(timezone.utc)`) is passed straight into `build_topology_graph` as `as_of` *and*
  stored on the `NetworkSnapshot` -- so a snapshot's claimed capture time always genuinely matches
  its graph's evidence, rather than being a label decoupled from content (rejected the alternative
  of always building the full graph and merely labeling it, since that would let two snapshots
  claim different times while carrying identical evidence). `list_snapshots(root, capture_id)`
  reads every persisted snapshot back sorted by `version`; `create_snapshot` uses `1` if none exist
  yet else `max(existing) + 1` -- generation order, not `captured_at` order, documented explicitly.
  `read_snapshot_graph` is a small reusable one-liner fetching a snapshot's referenced graph.
  `snapshot_id = graph_id = f"{capture_id}-snapshot-{version}"` -- `-`-separated, not this project's
  usual `:`-separated `<capture_id>:<type>:<index>` convention (`Node`/`Edge`/`Flow`), because these
  ids are used directly as filename components and `:` is invalid in a Windows path; an initial
  `:`-separated attempt crashed `write_json` with a real `OSError` on this Windows environment,
  caught and fixed during this phase's own test run, not a hypothetical concern. Deliberately no
  deduplication of unchanged consecutive snapshots (the spec says "generate," not "generate only on
  change"; *whether* something changed is Phase 45's job) and no API wiring (no `/snapshots` route
  exists among Phase 09's 12 fixed endpoint groups at all; `GET /history` is explicitly scoped to
  Phase 49 and returns `GraphChangeEvent`, Phase 45's schema, not raw snapshots). Never raises for a
  missing/empty capture -- mirrors `build_topology_graph`'s own stance, producing a valid,
  empty-graph version-1 snapshot instead. Verified: new `backend/tests/test_archaeology_snapshots.py`
  (9/9: version starts at 1 and increments per call; graph and snapshot both round-trip
  byte-for-byte through `read_json`; `captured_at` genuinely bounds the graph using Phase 43's own
  two-episode fixture pattern; `list_snapshots` returns `[]` for none and orders existing ones by
  version; `read_snapshot_graph` returns the exact referenced graph; omitting `captured_at` defaults
  to approximately "now"; two capture_ids version independently; a missing capture produces a valid
  empty-graph version-1 snapshot, never an error); combined suite 357/357 (up from 348/348), no
  regressions; `scripts.validate_data_contracts` re-verified clean (38/38, no schema changes);
  `scripts.check_ground_truth_boundary` re-verified clean (the new package imports no
  `simulator.ground_truth`); a real, manual end-to-end run (no Docker needed) built a synthetic
  two-episode capture, created three snapshots at increasing `captured_at` values, and confirmed
  version/node/edge counts and `list_snapshots` ordering exactly matched the doc's worked example.
  `docs/architecture/network_snapshot_engine.md` has full detail, including the
  captured-at-doubles-as-as_of design decision and both explicit non-goals.

- Phase 45 — Graph Difference Engine (new `backend/archaeology/diff.py`; FR-1.21 second half). The
  first real use of `GraphChangeEvent`/`ChangeType` (Phase 04) -- its 5-value enum is the master
  spec's own bullet list verbatim. `diff_snapshots(root, capture_id, from_snapshot, to_snapshot)`
  fetches both graphs via Phase 44's `read_snapshot_graph` and diffs by plain `node_id`/`edge_id`
  set comparison, relying on a directly-verified property: because Phase 43's `as_of` filtering
  only ever adds evidence as `as_of` grows, every already-included node/edge's `first_observed`
  (and therefore its deterministic index-based id) never changes, so an entity's id is stable
  across snapshots of the same capture -- no separate "same real-world entity" matching problem to
  solve, unlike Phase 32's ground-truth comparison. Attribute changes tracked for edges only
  (`confidence`, `protocols`); node attribute changes are explicitly never produced -- a `Node`'s
  only non-identity field (`last_observed`) trivially advances with any later traffic at all and
  would be pure noise with no topological significance (the same documented-scope-out pattern as
  Phase 40 never producing `TOPOLOGY`). One event per changed attribute (the schema allows exactly
  one `attribute_name` per event); every event carries real, concrete evidence from construction
  (specific ids, specific old/new values), satisfying `GraphChangeEvent.evidence`'s own
  non-empty requirement with genuine content from the start. Deterministically ordered by
  `(change_type, target_id, attribute_name)`. Removals are structurally real (correctly produced
  when snapshots are compared out of chronological order) but practically vacuous under normal
  forward-in-time usage, since topology reconstruction is cumulative with no expiry concept --
  documented, not hidden. No persistence (no `events_path` exists or was added) and no API wiring
  -- a pure function over two already-persisted snapshots, mirroring Phase 41/42's own unpersisted
  evaluation functions; `GET /history` remains explicitly scoped to Phase 49. Verified: new
  `backend/tests/test_archaeology_diff.py` (10/10: the id-stability property holds directly, not
  just assumed; node/edge additions detected; no changes between identical snapshots; a genuinely
  growing edge confidence produces one `ATTRIBUTE_CHANGED` event with `previous_value <
  new_value`; a new protocol on an existing edge produces an `ATTRIBUTE_CHANGED` event; no
  node-level attribute-change event ever fires even when `last_observed` demonstrably advances;
  reversed-order comparison correctly produces `NODE_REMOVED`/`EDGE_REMOVED` and zero additions;
  every event carries real non-empty evidence; identical repeated calls produce identical,
  identically-ordered output); combined suite 367/367 (up from 357/357), no regressions;
  `scripts.validate_data_contracts` re-verified clean (38/38, `GraphChangeEvent`/`ChangeType`
  unchanged, first real use only); `scripts.check_ground_truth_boundary` re-verified clean; a real,
  manual end-to-end run (no Docker needed) built the same two-episode capture, created two
  snapshots, diffed them, and confirmed the printed output (2 node additions, 1 edge addition, each
  with concrete evidence) exactly matched the doc's worked example. `docs/architecture/
  graph_difference_engine.md` has full detail, including the id-stability argument and both
  explicit limitations.

- Phase 46 — Behavioral Evolution Tracking (new `backend/archaeology/behavior_evolution.py`;
  FR-1.22 first half). The first Network Archaeology code to operate on FLOWMIND's
  `BehavioralFingerprint` (Phase 33-35) rather than a `TopologyGraph`/`NetworkSnapshot` (Phase
  43-45). `track_node_behavioral_evolution(fingerprints)` is a pure function over a caller-supplied,
  time-ordered list of one node's fingerprints (no Phase 04 schema is reserved for this -- unlike
  `GraphChangeEvent`, whose own docstring scopes it to "spec Phase 45, 47-48" not 46 -- so this
  follows Phase 38/39's own precedent of a plain `@dataclass`, `BehavioralEvolutionEvent`, instead).
  Walks consecutive fingerprint pairs and compares all 7 fields: `distinct_ports`/
  `distinct_protocols` by set difference (evidence names the concrete added/removed elements,
  mirroring Phase 38's set-valued novelty tracking); `distinct_destinations`/
  `mean_flow_duration_seconds`/`outbound_byte_ratio`/`total_byte_count` by exact value inequality --
  the same "no invented magnitude threshold" precedent Phase 45 already set comparing
  `Edge.confidence`, also a continuous float, the exact same way; `is_persistent_talker` by boolean
  flip. One event per changed field per transition, each carrying concrete, non-empty evidence.
  Deliberately NOT a duplicate of Phase 39's `track_node_drift`: that classifies a sequence against
  a static baseline as `CONCEPT_DRIFT`/`TRANSIENT_ANOMALY` (a FLOWMIND statistical detection
  judgment); this phase makes no such judgment -- it is a raw, evidenced chronological record, the
  direct behavioral analogue of Phase 45's `diff_snapshots`. No new persistent fingerprint-history
  store exists -- Phase 35's `fingerprints.jsonl` is overwritten per batch, not appended, so no real
  cross-batch history exists on disk yet; building one remains explicitly out of scope, the same
  call Phase 38/39 already made for their own history parameters. No persistence (no new artifact
  path) and no API wiring -- `GET /behaviors/{node_id}` remains a 501 stub, still blocked on Phase
  36-37's role wiring, unrelated to this phase; mirrors Phase 41/42/45's own pure, unpersisted
  function precedent. Verified: new `backend/tests/test_archaeology_behavior_evolution.py` (12/12:
  empty/mixed-node/mixed-window `ValueError`s; a single fingerprint returns `[]`; no changes between
  identical fingerprints returns `[]`; a changed continuous feature produces exactly one event with
  correct previous/new values; a changed port set names the added port; a removed protocol names
  it; an `is_persistent_talker` flip is detected; every event carries non-empty evidence; multiple
  transitions are chronologically ordered and identical repeated calls produce identical output; a
  real end-to-end-shaped test building fingerprints via Phase 35's `assemble_node_fingerprint` from
  two distinct flow sets for the same node); combined suite 379/379 (up from 367/367), no
  regressions; `scripts.validate_data_contracts` re-verified clean (38/38, no schema changes);
  `scripts.check_ground_truth_boundary` re-verified clean; a real, manual end-to-end run (no Docker
  needed) built two synthetic fingerprints for the same node 5 minutes apart with a deliberately
  widened port set, byte ratio, persistence flag, and byte volume, and confirmed the printed events
  exactly matched the doc's worked example. `docs/architecture/behavioral_evolution_tracking.md` has
  full detail, including the Phase 39 non-duplication argument and the no-reserved-schema rationale.

- Phase 47 — Topology Event Timeline (new `backend/archaeology/timeline.py`; new
  `experiments/artifacts/paths.py::events_path`; FR-1.22 second half). Reuses `GraphChangeEvent`/
  `ChangeType` (Phase 04) unmodified -- its own docstring already scoped it to "spec Phase 45,
  47-48", so no new schema was needed. `build_topology_event_timeline(root, capture_id)` fetches
  every persisted `NetworkSnapshot` for a capture via Phase 44's `list_snapshots` (already ordered
  by `version` ascending -- generation order), calls Phase 45's `diff_snapshots` unmodified on
  every consecutive pair, and concatenates the results in pair order into one flat list -- no new
  comparison or sorting logic; `diff_snapshots`'s own `(change_type, target_id, attribute_name)`
  ordering within a pair is preserved exactly as-is. Fewer than 2 snapshots returns `[]`, never an
  error, mirroring `create_snapshot`/`list_snapshots`'s own convention. Chains by snapshot
  *generation* order, not a `captured_at` re-sort -- `create_snapshot`'s own docstring already
  documents these as potentially different if snapshots are created out of sequence; normal usage
  makes them equivalent, and the divergent case is an explicit, documented caveat, the same style
  as Phase 45's own "practically vacuous under normal usage" note. Write-through persistence via
  the new `events_path` (`captures/<capture_id>/topology_events.jsonl`, `write_jsonl`) -- always
  recomputed and overwritten on every call, mirroring Phase 32's `topology_path` convention, not a
  cache. `read_topology_event_timeline` reads it back, returning `[]` for a capture with no
  timeline built yet, mirroring `list_snapshots`'s missing-directory convention. No API wiring --
  `GET /history` remains an untouched 501 stub, its own docstring already scoping its backing
  implementation to "spec Phase 49 (Historical Investigation Engine)"; this phase builds the
  capability that route will later query. Verified: new
  `backend/tests/test_archaeology_timeline.py` (8/8: zero and one snapshots both produce an empty
  timeline; three snapshots produce a timeline exactly equal to the concatenation of two separate
  `diff_snapshots` calls; events are grouped by consecutive generation pair in order, not re-sorted
  globally; `read_topology_event_timeline` round-trips byte-for-byte with what was just persisted;
  a capture with no timeline built yet reads back `[]`; repeated builds are deterministic; every
  event carries real non-empty evidence); combined suite 387/387 (up from 379/379), no
  regressions; `scripts.validate_data_contracts` re-verified clean (38/38, no schema changes);
  `scripts.check_ground_truth_boundary` re-verified clean; a real, manual end-to-end run (no Docker
  needed) built the same two-episode capture, created three snapshots, and confirmed the printed
  timeline (2 node additions + 1 edge addition, all attributed to the first generation pair)
  exactly matched the doc's worked example. `docs/architecture/topology_event_timeline.md` has full
  detail, including the generation-order-vs-captured_at-order caveat.

- Phase 48 — Change Attribution (`backend/app/models/snapshot.py`; `backend/archaeology/diff.py`
  extended in place; new `backend/archaeology/attribution.py`; FR-1.23). Three of FR-1.23's four
  named attribution items (observation evidence, timestamps, affected nodes) were already real on
  `GraphChangeEvent` since Phase 45; the real gap was affected flows -- no code anywhere linked a
  change event to concrete `Flow`s. Closed by adding `GraphChangeEvent.affected_flow_ids: List[str]
  = []` (backward-compatible, default-valued), the same "extend an earlier phase's schema once a
  later phase's requirement needs it" precedent Phase 40 already set for `total_byte_count` -- a
  separate `ChangeAttribution` dataclass was considered and rejected as pure duplication of fields
  `GraphChangeEvent` already has. `diff_snapshots` (Phase 45, extended in place, not a new function)
  now also reads `flows_path`, filtered to `flow.first_seen <= to_snapshot.captured_at` (the same
  `as_of` bound Phase 43/44 already establish), and matches flows against the affected node's/
  edge's IP set(s) -- genuine recomputation from typed `Flow` objects, not string-parsing of
  `Edge.evidence`'s human-readable text. Documented, honest scope limitation: an `ATTRIBUTE_CHANGED`
  event attributes to every flow supporting the edge as of the later snapshot, not only the
  specific new flow(s) that drove that one attribute's delta -- isolating that subset would need
  flow-level diffing between snapshots, not attempted here, mirroring Phase 30's own
  "evidence is every flow in the bucket" granularity. New `format_change_attribution`/
  `format_timeline_attribution` (mirroring Phase 41's `explain.py`) render each event's full
  attribution plus a fixed, unconditional causal disclaimer -- structural, not a confidence
  threshold, since this system has no causal-inference mechanism at all yet (`CausalEvidenceReport`,
  `backend/app/models/dependency.py`, is explicitly scoped to Phase 56, a different, later concern,
  not reusable here). No new persistence (`affected_flow_ids` reaches disk automatically via Phase
  47's existing `topology_events.jsonl`) and no API wiring -- `GET /history` remains Phase 49's
  untouched 501 stub. Verified: `backend/tests/test_archaeology_diff.py` grew from 10/10 to 14/14
  (a `NODE_ADDED` event's `affected_flow_ids` matches the real flows touching that node; an
  `EDGE_ADDED` event's matches the real flows connecting its two nodes; an `ATTRIBUTE_CHANGED`
  event's matches every flow supporting the edge; an ICMP-only node's added event correctly gets
  `[]`); new `backend/tests/test_archaeology_attribution.py` (9/9: every rendered field present and
  correct; an honest "none directly attributable" line when no flows exist; the causal disclaimer
  present in every report across all five `ChangeType` values with no exceptions; multi-event
  timeline ordering; empty-timeline handling); combined suite 400/400 (up from 387/387), no
  regressions; `scripts.validate_data_contracts` re-verified clean (38/38, the new field is
  optional/default-valued); `scripts.check_ground_truth_boundary` re-verified clean; a real, manual
  end-to-end run (no Docker needed) rebuilt the same two-episode capture, diffed two snapshots, and
  confirmed the printed `edge_added` event's `affected_flow_ids` and rendered report exactly matched
  the doc's worked example. `docs/architecture/change_attribution.md` has full detail, including
  the schema-extension precedent and the causal-disclaimer design rationale; a one-line amendment
  pointer was added to `docs/architecture/graph_difference_engine.md`.

- Phase 49 — Historical Investigation Engine (`backend/app/api/routes/history.py`; FR-1.24). A
  wire-up phase, not a new-capability one: `GET /history` now calls Phase 47's
  `build_topology_event_timeline(root, capture_id)` unmodified, filters to `start <= occurred_at <=
  end` (inclusive both ends), and paginates with the existing `PageParams`/`PaginatedResponse`
  machinery `GET /flows` already uses -- no new schema, no new inference. Deliberately does not 404
  on an unknown `capture_id`, unlike `GET /flows`/`GET /topology`: `build_topology_event_timeline` ->
  `list_snapshots` already follows the archaeology layer's "missing means empty" convention, so an
  unrecognized capture and a real one with no snapshots yet are indistinguishable at this layer, and
  both correctly return an empty, still-200 paginated result rather than reintroducing a distinction
  the layer underneath doesn't make. Verified: `backend/tests/test_api.py` gained 4 new `GET
  /history` tests (unknown capture returns `200`/empty, not `404`; a full window returns the real
  events `build_topology_event_timeline` produces; a narrow window before any snapshot pair excludes
  every event; pagination `limit`/`offset` is honored and `total` reflects the pre-pagination window
  count) and lost its old 501-stub parametrization entry for `/history` (9 -> 8 remaining stub
  groups); full repo suite re-run clean, no regressions; `scripts.validate_data_contracts` and
  `scripts.check_ground_truth_boundary` both re-verified clean (no schema changes this phase).
  `docs/architecture/historical_investigation_engine.md` has full detail, including the
  empty-not-404 convention rationale.

- Phase 50 — Dependency and Causal Reasoning: Communication vs. Dependency Distinction (new
  `backend/dependency/` package, `backend/dependency/communication.py`; FR-1.25, RQ5). The type
  separation FR-1.25 requires (`CommunicationRelationship` vs. `DependencyEdge`,
  `backend/app/models/dependency.py`) was already built in Phase 04 -- its own module docstring
  already calls this "the central design point (spec Phase 50, RQ5)". What was missing was a real
  computation of the "communicates" side: `derive_communication_relationships` aggregates Phase
  29's `discover_nodes` and Phase 30-31's `discover_edges` output, both reused unmodified (the same
  "combine, don't reinvent" pattern Phase 32's `build_topology_graph` uses), mapping each `Edge` to
  one `CommunicationRelationship` (`persistence_seconds = last_observed - first_observed`;
  `frequency = observation_count / persistence_seconds`, falling back to raw `observation_count`
  when `persistence_seconds == 0` -- an honest, documented zero-duration edge case, not a
  `ZeroDivisionError` or a fabricated rate). Candidate pairs are exactly `discover_edges`'s own
  already-inferred topology edges, per `docs/architecture/algorithm_selection.md` section 6's
  committed design ("pruned first by the already-inferred topology edges"), not a fresh O(V^2) scan.
  No strength/directionality/temporal-precedence scoring (Phase 51/52-53's job) and no API wiring --
  `GET /dependencies` remains explicitly scoped to Phase 51 ("Dependency Strength"). Verified: new
  `backend/tests/test_dependency_communication.py` (7/7: empty capture returns `[]`; a single
  exchange's relationship matches its corresponding `Edge` exactly; two independent episodes produce
  two relationships matching `discover_edges`'s two-edge output; a zero-duration flow falls back to
  `frequency == observation_count`; `as_of` bounding excludes later communication; computed
  `frequency`/`persistence_seconds` are always non-negative; every relationship's field set is
  exactly `{source_node_id, target_node_id, frequency, persistence_seconds}`, structurally incapable
  of carrying a dependency-shaped claim); full repo suite 410/410 (up from 403/403), no regressions;
  `scripts.validate_data_contracts` 38/38 and `scripts.check_ground_truth_boundary` both re-verified
  clean (no schema changes this phase). `docs/architecture/communication_vs_dependency.md` has full
  detail, including the zero-duration fallback rationale and the explicit "what this phase does NOT
  do" scope boundary.

- Phase 51 — Dependency Strength (new `backend/dependency/strength.py`; refactored
  `backend/nettrace/topology/edges.py`; three new `Settings` fields; FR-1.26). Estimates
  `DependencyEdge.strength`/`directionality_score` from four of FR-1.26's five named signals --
  frequency, persistence, directionality, traffic characteristics -- deliberately excluding temporal
  relationships (`algorithm_selection.md` section 6 tags it "spec Phase 52";
  `temporal_precedence_score` stays at its schema default `0.0`). No new evidence anywhere: frequency/
  persistence reuse Phase 50's `derive_communication_relationships` unmodified; directionality reuses
  Phase 30-31's `_bidirectionality(forward_byte_ratio)` inverted (that helper measures balanced-ness,
  the opposite of "how one-directional"); traffic characteristics reuses `Edge.confidence` (Phase 31)
  directly. Combination mirrors Phase 31's `_confidence` noisy-OR shape exactly (one primary
  saturating frequency term, three secondary signals scaled by one shared, uniformly-applied
  `dependency_signal_strength`), via new provisional `Settings` fields (`dependency_frequency_scale`,
  `dependency_persistence_scale`, `dependency_signal_strength`, mirroring `edge_confidence_*`'s own
  "pending Phase 68 calibration" wording). One small, behavior-preserving refactor first:
  `discover_edges`'s inline flow-bucketing loop was extracted into `bucket_flows_by_node_pair`
  (`edges.py`) so this phase could reuse the identical per-node-pair buckets for directionality --
  `discover_edges`'s own signature/behavior are unchanged, verified by re-running the full edge/
  topology/API suite before any new code. `GET /dependencies` is now real (unlike Phase 50, whose
  route stayed untouched by design), keeping the "missing means empty" convention -- no 404 on an
  unrecognized `capture_id`. `estimate_dependency_strength` relies on an explicit, documented
  invariant: `discover_edges` and `derive_communication_relationships` output are index-aligned
  since both are deterministic functions of the identical inputs, so `edges[i]`/`relationships[i]`
  refer to the same node pair without a separate lookup. Verified: new
  `backend/tests/test_dependency_strength.py` (7/7: empty capture returns `[]`; a single exchange's
  `DependencyEdge` matches hand-computed fields exactly with `temporal_precedence_score` always
  `0.0`; two independent episodes produce two dependency edges; `as_of` bounding excludes later
  communication; one-way vs. balanced traffic produce near-maximal vs. near-minimal
  `directionality_score`; a missing capture never raises); `backend/tests/test_api.py` gained 3 new
  `GET /dependencies` tests (unknown capture returns `200`/empty; a real ingested capture returns
  real, bounded `DependencyEdge`s; pagination respected) and lost its 501-stub parametrization entry
  (8 -> 7 remaining stub groups); full repo suite 419/419 (up from 410/410), no regressions;
  `scripts.validate_data_contracts` 38/38 and `scripts.check_ground_truth_boundary` both
  re-verified clean (no schema changes this phase). `docs/architecture/dependency_strength.md` has
  full detail, including the noisy-OR formula and the index-alignment invariant.

- Phase 52 — Temporal Precedence Analysis (new `backend/dependency/temporal_precedence.py`;
  `backend/dependency/strength.py` extended in place, same function; two new `Settings` fields;
  FR-1.27 first half). Implements `algorithm_selection.md` section 6's already-committed algorithm
  -- time-lagged cross-correlation, part of the same combined scoring function already producing
  `DependencyEdge.strength` -- closing the gap Phase 51 deliberately left open
  (`temporal_precedence_score` was schema-default `0.0`, never set). Real design decision on what
  "changes" means: per-node OVERALL flow activity (any counterpart, time-bucketed by
  `Flow.first_seen`), not just the specific pair's own flows (which would make source/target series
  nearly identical -- every flow between A and B touches both at the same timestamp -- collapsing to
  trivial zero-lag correlation and conflating with the already-separate directionality signal), and
  not Phase 45/47's `GraphChangeEvent`s (too sparse per node -- essentially one `NODE_ADDED` ever,
  cumulative topology with no expiry) or Phase 46's `BehavioralEvolutionEvent` (only available from
  a caller-supplied fingerprint list, no persisted history exists, which would break
  `estimate_dependency_strength`'s automatic/self-sufficient calling convention). Reuses Phase
  33/34's `flows_touching_node` directly (new cross-package import, dependency/ -> flowmind/, a
  deliberate, justified reuse of an already-generic utility). `estimate_temporal_precedence`
  cross-correlates (stdlib `statistics.correlation`, same module `node_baseline.py` already uses for
  median/MAD) source vs. lag-shifted target over a bounded set of positive lag offsets (per section
  6's O(T) complexity note); scores `0.0` unless the best positive-lag correlation beats the zero-lag
  baseline AND is itself positive -- a merely-simultaneous relationship is deliberately not counted
  as "precedes." `estimate_dependency_strength` now reads `flows_path` once (reused across every
  pair in its loop, not re-read per pair), calls the new function per `(source_node, target_node)`
  pair, extends the noisy-OR `survival` product with a fourth secondary term identical in shape to
  the existing three, and actually sets `temporal_precedence_score` on every constructed
  `DependencyEdge` -- the moment `strength` genuinely reflects all five of FR-1.26's named signals
  for the first time (frequency, persistence, directionality, temporal relationships, traffic
  characteristics). Two new provisional `Settings` fields (`dependency_temporal_bucket_seconds=10.0`,
  mirroring Phase 34's short-window precedent; `dependency_temporal_max_lag_buckets=5`), same
  "pending Phase 68 calibration" wording as every other numeric constant. `GET /dependencies` threads
  both through, same pattern as Phase 51's own three settings. Deliberately does NOT build candidate
  causal-relationship generation -- explicitly Phase 53's job per FR-1.27's own "Phase 52-53" span
  and `algorithm_selection.md`'s own scoping (its option (c) rejection note cites the Phase 53
  wording specifically). Verified: new `backend/tests/test_dependency_temporal_precedence.py` (6/6: a
  genuine positive lag over irregularly-spaced bursts -- avoiding periodicity aliasing, where a
  periodic pattern would also show spurious correlation at other lags sharing the period -- is
  detected with a high score; a purely simultaneous zero-lag pattern scores `0.0`; unrelated/sparse
  activity scores low; reversed source/target roles score meaningfully lower than the true
  direction; a zero-activity counterpart never crashes; empty input returns `0.0`);
  `backend/tests/test_dependency_strength.py` grew 7/7 -> 8/8 (the existing hand-computed formula
  test now explicitly includes the fourth noisy-OR term, a documented no-op for that minimal
  fixture since `temporal_precedence_score` is honestly `0.0` there too -- no room for a
  positive-lag window; a new end-to-end test with a genuinely lagged multi-node scenario, using
  third/fourth "side conversation" nodes to give source/target genuinely distinguishable activity
  series, confirms a real non-zero `temporal_precedence_score` and that `strength`'s
  hand-recomputed value matches the extended formula exactly); `test_api.py`'s existing `GET
  /dependencies` tests needed no changes -- their minimal fixture still honestly scores
  `temporal_precedence_score == 0.0`, correctly, for the same "no room for a positive lag" reason;
  combined suite 426/426 (up from 419/419), no regressions; `scripts.validate_data_contracts`
  re-verified clean (38/38, no schema changes -- `DependencyEdge`'s already-reserved field is simply
  populated for real now); `scripts.check_ground_truth_boundary` re-verified clean. Also corrected a
  real, separate documentation gap found while starting this phase: `README.md` had been stuck at
  "Current phase: 48" despite Phases 49-51 being complete and committed -- backfilled the missing
  bullets before adding this phase's own. `docs/architecture/temporal_precedence_analysis.md` has
  full detail, including the worked example; `docs/architecture/dependency_strength.md` updated with
  a pointer note.

- Phase 53 — Causal Candidate Generation (new `backend/dependency/causal_candidates.py`; one new
  `Settings` field; FR-1.27 second half). Implements the design boundary already committed at Phase
  05: `algorithm_selection.md` section 6 explicitly evaluated and rejected constraint-based causal
  discovery (the PC algorithm) in favor of a "scored-candidate approach... without requiring full
  causal-graph discovery" -- this phase is a filter/promotion step over Phase 51/52's already-real
  `DependencyEdge` list, not a new causal-inference algorithm. `GET /causal/{dependency_id}` stays
  untouched, its own docstring already scoped to "spec Phase 56"; RQ5's own experiment design
  confirms the same split (Phase 53 produces candidates, Phase 56 wraps an accepted one in the full
  `CausalEvidenceReport` format). Qualifying rule is the literal, structural implementation of "do
  not equate correlation with causation": a `DependencyEdge` is promoted only when it has BOTH
  sufficient `strength` (new provisional `causal_candidate_strength_threshold=0.5`) AND a real,
  positive `temporal_precedence_score` -- `strength` alone, however high, is deliberately never
  sufficient by itself, since it's built entirely from correlation/communication-style signals
  (frequency, persistence, directionality, traffic characteristics), while temporal precedence
  specifically supports directional, time-ordered evidence, the logical prerequisite for a causal
  claim, not proof of one. `CausalCandidate` is a plain frozen dataclass (no new Phase 04 schema),
  following the precedent already set by Phase 32/37/42/46's own evaluation/filtering-style
  outputs; `generate_causal_candidates` is a pure function over caller-supplied `DependencyEdge`s,
  deterministically ordered by strength descending, tie-broken by `dependency_id`. Every candidate's
  `rationale` names concrete evidence values (e.g. `"strength 0.850 meets threshold 0.500"`), never
  a bare label. `format_causal_candidate` unconditionally appends a new
  `CAUSAL_CANDIDATE_DISCLAIMER` (worded for this context, distinct from Phase 48's own
  structural-change disclaimer), mirroring Phase 48's "structural, not confidence-gated" disclaimer
  pattern extended to this new artifact type. No persistence, no API wiring; `CausalEvidenceReport`
  remains unpopulated, explicitly Phase 56's job. Verified: new `backend/tests/
  test_dependency_causal_candidates.py` (10/10: a qualifying dependency becomes a candidate; the
  key case -- high strength but zero temporal precedence -- does not qualify, however high the
  strength; low strength with real temporal precedence also does not qualify; multiple qualifying
  edges deterministically ordered by strength descending, tie-broken by `dependency_id`; every
  candidate's rationale is non-empty and references real values; empty input returns `[]`; a custom
  threshold changes qualification; `format_causal_candidate` always includes the disclaimer and full
  content; a real end-to-end run through `estimate_dependency_strength`, not hand-built
  `DependencyEdge` fixtures, confirms the genuinely-leading pair becomes a real candidate while its
  side-conversation edges do not); combined suite 436/436 (up from 426/426), no regressions;
  `scripts.validate_data_contracts` re-verified clean (38/38, no schema changes this phase);
  `scripts.check_ground_truth_boundary` re-verified clean; a real, manual end-to-end run (no Docker
  needed) built the same multi-node lagged-activity capture, ran `estimate_dependency_strength` then
  `generate_causal_candidates`, and confirmed the printed output (3 dependency edges reduced to 1
  genuine candidate) exactly matched the doc's worked example. `docs/architecture/
  causal_candidate_generation.md` has full detail, including the qualifying-rule argument and the
  worked example.

- Phase 54 — Failure Propagation Graph (new `backend/dependency/failure_propagation.py`; FR-1.28).
  The first real use of `PropagationImpact`/`ImpactOrder` (Phase 04, docstring-tagged "spec Phase
  54, 61", never constructed anywhere before this). A real, previously-undocumented design
  decision: propagates over Phase 53's `List[CausalCandidate]`, not raw `List[DependencyEdge]` --
  `Edge`/`DependencyEdge.source_node_id`/`target_node_id` are undirected (`discover_edges` assigns
  them by alphabetically sorting the node-id pair, not by any real dependency direction), so
  following a raw `DependencyEdge`'s `source -> target` would often mean propagating in a direction
  with zero supporting evidence (`temporal_precedence_score == 0.0`) -- an artifact of alphabetical
  sorting, not a causal claim. `CausalCandidate`s are exactly the subset where `source -> target`
  carries genuine, positive temporal-precedence evidence, making this the only edge set in the
  codebase where "if source fails, target is impacted" is actually justified by real evidence --
  the natural, evidence-grounded continuation of Phase 51 -> 52 -> 53. Algorithm: `propagate_failure`
  produces the primary impact (the failed node itself, `caused_by_node_id=None`) plus a
  breadth-first traversal over `source_node_id -> target_node_id`, exactly two hops deep (matching
  the spec's literal three-order list -- primary/secondary/tertiary, no further cascading, a
  documented future-enhancement possibility, not attempted, NFR-9). Each node is visited at most
  once across the whole traversal -- a cycle can never loop, and a diamond-shaped candidate graph
  (two paths converging on one descendant) never double-counts a node; the first order/candidate
  that reaches it wins. Fully deterministic processing order: frontier nodes sorted by node id,
  each node's outgoing candidates sorted by `dependency_id`. Every non-primary impact's `evidence`
  cites the specific `CausalCandidate`'s real `strength`/`temporal_precedence_score` values, never a
  bare label. Returns `[PRIMARY only]` for a failed node with no outgoing candidates or empty input
  -- never an error. No new `Settings` field -- the edge set is already governed entirely by Phase
  53's own `causal_candidate_strength_threshold`. No persistence, no API wiring -- `POST /simulation`
  stays untouched, its own docstring already scoped to "spec Phase 59-61". Verified: new
  `backend/tests/test_dependency_failure_propagation.py` (8/8: a simple chain produces exactly
  primary/secondary/tertiary with a fourth hop correctly excluded; a node with no outgoing
  candidates produces only the primary impact; a diamond pattern visits the shared descendant
  exactly once, deterministically attributed; a cycle never infinite-loops or revisits an
  already-impacted node; every non-primary impact's evidence references the real candidate values
  that caused it; empty input produces only the primary impact; repeated calls produce identical,
  identically-ordered output; a real end-to-end run through `estimate_dependency_strength` ->
  `generate_causal_candidates`, not hand-built `CausalCandidate` fixtures, over a genuine 3-hop
  lagged-activity capture -- with no direct A<->C traffic at all, so tertiary discovery of C must
  come from real propagation through B, not a shortcut edge -- confirms real primary/secondary/
  tertiary impacts); combined suite 444/444 (up from 436/436), no regressions; `scripts.
  validate_data_contracts` re-verified clean (38/38, no schema changes this phase -- first real use
  of already-reserved fields); `scripts.check_ground_truth_boundary` re-verified clean; a real,
  manual end-to-end run (no Docker needed) built the same 3-hop lagged-activity capture and ran the
  full `estimate_dependency_strength` -> `generate_causal_candidates` -> `propagate_failure`
  pipeline, confirming the printed output exactly matched the doc's worked example.
  `docs/architecture/failure_propagation_graph.md` has full detail, including the undirected-edge
  argument and the worked example.

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
- Multi-window modeling's (Phase 34) `long` (300s) window duration has no direct supporting evidence
  in this repo's own captures/tests (all of which run under a minute) — a documented, explicit
  extrapolation pending real multi-minute lab data, not a gap; see
  `docs/architecture/multi_window_behavior_modeling.md`.
- `GET /behaviors/{node_id}` remains a 501 stub after Phase 35: its Phase-09-fixed `NodeBehavior`
  response requires a `RoleClassification` that doesn't exist until Phase 36-37 — a structural
  blocker on the route's own contract, not a gap in Phase 35's own scope; documented in
  `docs/architecture/node_behavioral_fingerprints.md`.
- Role inference (Phase 36) has no model trained on real Docker-lab data — verified only against
  synthetic labeled fixtures this session (no Docker), and `GET /behaviors/{node_id}` remains a 501
  stub as a direct consequence; documented in `docs/architecture/service_role_inference.md`. Producing
  a genuine labeled training set from the lab is left to a future phase with real Docker/lab access.
- Uncertainty-aware classification (Phase 37) fitted no real temperature and measured no real
  calibration error against real Docker-lab ground truth — both verified only against synthetic
  labeled fixtures this session (no Docker); `GET /behaviors/{node_id}` remains a 501 stub as a direct
  consequence, unchanged from Phase 36; documented in
  `docs/architecture/uncertainty_aware_classification.md`. Real validation is left to a future phase
  with real Docker/lab access.
- The behavioral baseline (Phase 38) has no cross-capture historical-fingerprint store — it's a pure
  function over a caller-supplied history, and `min_observations=5` (the cold-start threshold) is a
  documented, evidence-light provisional default; `mad` is reported honestly un-floored, left for a
  future consumer to floor if/when it computes a z-score; documented in
  `docs/architecture/behavioral_baseline.md`.
- Concept drift detection (Phase 39) only tracks the continuous `NodeBehavioralBaseline` features
  (5 as of Phase 40's `total_byte_count` addition) — no EWMA-drift analogue is defined for the 2
  historical-set features or the persistence frequency, since `algorithm_selection.md` §3 doesn't
  specify what "drift" means for those. `alpha=0.05`/`drift_threshold_mads=2.0` are documented,
  evidence-light provisional defaults, not empirically validated (no Docker this session); documented
  in `docs/architecture/concept_drift_detection.md`.
- Multi-dimensional anomaly detection (Phase 40) never produces an `AnomalyDimension.TOPOLOGY`
  anomaly — a documented scope-out, deferred to Phase 45's graph-diff machinery, not a gap. Its
  `z_threshold=3.0`/`novelty_scale=1.0` are documented, evidence-light provisional defaults, not
  empirically validated (no Docker this session); documented in
  `docs/architecture/multidimensional_anomaly_detection.md`.
- Explainable anomalies (Phase 41) standardized `node_anomaly.py`'s evidence formatting to match
  Phase 04's own contract example (clean integers, not `.3f` everywhere) and added a new
  `format_anomaly_report` (`backend/flowmind/anomaly/explain.py`) rendering any `Anomaly` list into
  the master spec's literal human-readable report shape. Deliberately no new detection signal
  (specific new-destination identity, unlike ports/protocols, remains an honest, documented
  limitation) and no API/persistence wiring — documented in
  `docs/architecture/explainable_anomalies.md`.
- FLOWMIND evaluation (Phase 42) is a pure scoring function (`evaluate_anomaly_detection`,
  `experiments/metrics/anomaly_evaluation.py`) over caller-supplied `Anomaly` output and labeled
  ground truth — it builds no dataset itself. `false_positive_rate` is honestly `None` unless the
  caller supplies `total_checks`; documented in `docs/architecture/flowmind_evaluation.md`.
- Temporal graph model (Phase 43) extended `discover_nodes`/`discover_edges`/
  `build_topology_graph` in place with a backward-compatible `as_of` parameter, rather than
  creating a new `backend/archaeology/` package — that package stays justified for Phase 44's
  `NetworkSnapshot` persistence instead; documented in `docs/architecture/temporal_graph_model.md`.
- Network snapshot engine (Phase 44) created `backend/archaeology/` for real, `create_snapshot`
  ties `NetworkSnapshot.captured_at` to Phase 43's `as_of` bound so a snapshot's claimed time
  always matches its graph's evidence. Snapshot/graph ids use `-` separators, not this project's
  usual `:`, because `:` is invalid in a Windows filename and these ids become path components;
  documented in `docs/architecture/network_snapshot_engine.md`.
- Graph difference engine (Phase 45) diffs snapshots by plain `node_id`/`edge_id` set comparison,
  relying on a directly-verified id-stability property from Phase 43's monotonic `as_of` filtering
  — no separate entity-matching problem, unlike Phase 32's ground-truth comparison. Node attribute
  changes are never produced (only `last_observed` exists, which is pure noise); documented in
  `docs/architecture/graph_difference_engine.md`.
- Behavioral evolution tracking (Phase 46) has no real cross-batch fingerprint-history store to read
  from — Phase 35's `fingerprints.jsonl` is overwritten per batch, not appended — so
  `track_node_behavioral_evolution` is verified only against caller-constructed and
  `assemble_node_fingerprint`-derived fingerprint lists, never a real persisted multi-batch history;
  building one is future work, not a gap in this phase's own scope. It also makes no statistical
  significance judgment (deliberately left to Phase 39's `track_node_drift`, not duplicated here);
  documented in `docs/architecture/behavioral_evolution_tracking.md`.
- Topology event timeline (Phase 47) chains snapshots by generation order, not a `captured_at`
  re-sort — equivalent under normal (chronologically increasing) usage, but would reflect
  generation order rather than wall-clock order if snapshots were ever created out of sequence; a
  documented caveat, not a gap. Inherits Phase 45's own "removals practically vacuous under normal
  usage" limitation unchanged (no new removal-detection logic was added). No API wiring yet — `GET
  /history` remains explicitly scoped to Phase 49; documented in
  `docs/architecture/topology_event_timeline.md`.
- Change attribution (Phase 48) attributes an `ATTRIBUTE_CHANGED` event to every flow supporting
  the edge as of the later snapshot, not only the specific flow(s) that drove that one attribute's
  delta — isolating that subset would require flow-level diffing between snapshots, not attempted
  here; a documented, honest limitation, not a gap. The causal disclaimer is unconditional because
  no causal-inference mechanism exists anywhere in this system yet (Phase 50-56's job), not because
  a sufficiency threshold was evaluated and passed; documented in
  `docs/architecture/change_attribution.md`.
- Historical investigation engine (Phase 49) deliberately does not 404 on an unrecognized
  `capture_id` -- the archaeology layer's own "missing means empty" convention makes that
  indistinguishable from a real capture with no snapshots yet, so both return an empty, still-200
  result; a documented convention choice, not a gap. Inherits Phase 47's generation-order-vs-
  `captured_at`-order caveat and Phase 45's "removals practically vacuous" limitation unchanged --
  no new filtering logic was added beyond the `start`/`end` window; documented in
  `docs/architecture/historical_investigation_engine.md`.
- Communication vs. dependency distinction (Phase 50) computes `CommunicationRelationship.frequency`
  as raw `observation_count` (not a divide-by-zero or a fabricated rate) when
  `persistence_seconds == 0` -- a real, if unusual, case (every contributing flow shares one
  instant), documented, not hidden. No strength/directionality/temporal-precedence scoring exists
  anywhere in this system yet (Phase 51/52-53's job); documented in
  `docs/architecture/communication_vs_dependency.md`.
- Dependency strength (Phase 51) uses provisional, uncalibrated noisy-OR weights
  (`dependency_frequency_scale`/`dependency_persistence_scale`/`dependency_signal_strength`), pending
  real calibration (Phase 68), not claimed-accurate values -- same status as `edge_confidence_*`'s
  own weights since Phase 31. A high-frequency, persistent, one-directional but coincidental
  communication pattern (e.g. a health-check poller) can score a falsely high `strength` -- an
  expected, documented failure mode (`algorithm_selection.md` section 6), not eliminated by
  construction; measuring it is Phase 68's job. `strength` can compute to exactly `1.0` under
  floating-point underflow for extreme frequency/persistence values relative to their scales (the
  schema's `le=1` already allows this); documented in `docs/architecture/dependency_strength.md`.
- Temporal precedence analysis (Phase 52) uses per-node overall flow activity (not the specific
  pair's own flows, which would collapse to trivial zero-lag correlation), time-bucketed and
  cross-correlated at a bounded set of positive lag offsets, provisional/uncalibrated like every
  other Phase 51/68-pending constant; documented in
  `docs/architecture/temporal_precedence_analysis.md`.
- Causal candidate generation (Phase 53) requires BOTH sufficient `strength` AND a real, positive
  `temporal_precedence_score` to promote a `DependencyEdge` to a `CausalCandidate` -- strength alone
  is deliberately never sufficient, since FR-1.26's other four signals are all correlation/
  communication evidence, not temporal-ordering evidence; documented in
  `docs/architecture/causal_candidate_generation.md`.
- Failure propagation (Phase 54) traverses Phase 53's `CausalCandidate`s, not raw `DependencyEdge`s
  -- the latter are undirected (alphabetically-sorted node-id pairs), so propagating along them
  would often follow a direction with zero real evidence; documented in
  `docs/architecture/failure_propagation_graph.md`.
- Next: Phase 55 (Criticality Analysis, FR-1.29). Compute graph criticality metrics (degree,
  betweenness, articulation points, path dependency, connectivity) with documented rationale for
  each metric's relevance. Not started; awaiting explicit request.
