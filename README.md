# NETSCOPE-X

Autonomous Network Reconstruction, Behavioral Intelligence, Temporal Network Archaeology, Causal
Reasoning, Digital Twin and Counterfactual Failure Simulation Platform.

NETSCOPE-X observes a network through traffic (and other permitted observable telemetry) and
progressively reconstructs an operational model of it: what nodes exist, who talks to whom, what role
each node plays, what's normal, what changed, which relationships are dependencies, how failures would
propagate, and what would happen under hypothetical changes — validated against controlled ground
truth. It is a research platform, not a chatbot or a generic dashboard: the core intelligence comes
from packet analysis, flow reconstruction, graph algorithms, probabilistic inference, and controlled
experiments. See `docs/research/problem_definition.md` for the full problem statement and
`docs/research/research_questions.md` for the research questions this project answers.

This project is being built according to a 69-phase execution plan; this README reflects status as of
the most recently completed phase and is updated after every phase.

## Project status

**Current phase: 36 of 69 complete** (Phase 21's controlled live capture remains
implemented-and-unit-verified-but-not-yet-Docker-verified — see `docs/architecture/packet_capture.md`).
A real Naive Bayes role classifier (`fit_role_model`/`classify_node_role`) now implements the exact
algorithm `docs/architecture/algorithm_selection.md` §2 selected — genuinely computed posteriors, not
fabricated, but not yet validated as calibrated (Phase 37) and not yet trained on real Docker-lab data
(no Docker this session) — see `docs/architecture/service_role_inference.md`. `GET /behaviors/{node_id}`
stays a 501 stub. Next: Phase 37.

Full phase-by-phase state, architecture decisions, test status, and pending work:
[`docs/PROJECT_STATE.md`](docs/PROJECT_STATE.md).

### What exists so far

- **Research foundation** (Phases 01-03): problem definition, research questions, system requirements
  — `docs/research/`, `docs/requirements/`.
- **Data contracts** (Phase 04): typed Pydantic schemas for every core domain object (packet, flow,
  node, edge, topology, behavioral fingerprint, anomaly, snapshot, dependency, failure, simulation,
  experiment, metric) — `backend/app/models/`.
- **Algorithm selections** (Phase 05): documented, justified algorithm choices for flow
  reconstruction, role inference, anomaly detection, graph criticality, path analysis, and dependency
  inference — `docs/architecture/algorithm_selection.md`.
- **Reproducible dev environment** (Phase 06): pinned Python backend stack, a React/TypeScript/Vite/
  Tailwind frontend scaffold, Docker images for both, a one-command bootstrap script —
  `requirements*.txt`, `frontend/`, `backend/Dockerfile`, `frontend/Dockerfile`, `docker-compose.yml`,
  `scripts/setup.sh`.
- **Observability** (Phase 07): structured JSON logging, request/experiment ID propagation,
  performance timing — `backend/app/core/{context,logging,timing}.py`.
- **Configuration & secrets** (Phase 08): environment-driven settings, secret handling with a
  production safety guard — `backend/app/core/config.py`, `.env.example`, `.env.test`.
- **API architecture** (Phase 09): all 12 required endpoint groups routed and validated under
  `/api/v1`, with consistent error handling — `backend/app/api/`. `POST /capture` (Phase 21) and
  `GET /flows` (Phase 23, now including real TCP state as of Phase 24), and `GET /topology`
  (Phase 32) are real; the other 9 still return a structured 501 (not yet implemented) — see
  "What doesn't exist yet" below.
- **Research artifact architecture** (Phase 10): reproducible on-disk formats (JSON / JSON Lines) for
  flows, graphs, snapshots, experiments, metrics, and hash-verified ground truth —
  `experiments/artifacts/`.
- **Multi-tier network laboratory** (Phase 11): a 10-service controlled Docker lab (client, gateway,
  load balancer, 2x API, redis, database, worker, DNS, external-service simulator) that NETSCOPE-X
  observes starting Phase 21 — `simulator/docker/`.
- **Network namespace isolation** (Phase 12): the lab is segmented into 4 controlled network
  boundaries (edge/app/data/external); intended request paths still work, and unintended cross-tier
  access is verifiably blocked at DNS resolution — `docs/architecture/network_laboratory.md`.
- **Routing laboratory** (Phase 13): a second load balancer gives the gateway two real routes into
  the app tier; a live failure was triggered (one route stopped) and traffic rerouted with zero
  downtime, then recovery was confirmed — `docs/architecture/network_laboratory.md`.
- **Traffic workload generator** (Phase 14): reproducible schedules for all 6 required traffic
  patterns (normal, burst, periodic, concurrent, idle, degraded), executed for real against the live
  lab — `simulator/traffic/`, `docs/architecture/traffic_generation.md`.
- **Protocol workload generator** (Phase 15): real wire-level traffic for all 6 required protocols
  (HTTP, TCP, UDP/DNS, cache, database, TLS), run against the live lab — real DNS answers, a real
  Redis PONG, a real Postgres handshake byte, a real negotiated TLS 1.3 session —
  `simulator/traffic/protocols.py`, `docs/architecture/protocol_generation.md`.
- **Ground-truth generator** (Phase 16): automatically generates authoritative nodes, edges, roles,
  and expected paths from the lab's real running state (real container IPs, hash-verified,
  deliberately kept outside `backend/` so future inference code has no import path to it) —
  `simulator/ground_truth/`, `docs/architecture/ground_truth.md`.
- **Ground-truth integrity** (Phase 17): each ground-truth generation is now versioned — re-running
  the generator for the same capture_id writes a new numbered generation (`v1/`, `v2/`, ...) rather
  than overwriting the previous one, tracked in a hash-protected manifest — and a static `ast`-based
  checker (`scripts/check_ground_truth_boundary.py`) fails the build the moment any code outside
  ground-truth generation/evaluation/test code imports `simulator.ground_truth` —
  `experiments/artifacts/{ground_truth_manifest,io}.py`, `docs/architecture/ground_truth.md`.
- **Scenario generator** (Phase 18): 6 required network architectures (simple chain, star,
  multi-tier, redundant, multi-path, dynamic service network) generated programmatically and
  parametrically, each with a real NetworkX-verified structural property, plus one new reusable
  generic container image that makes every generated scenario actually deployable — proven by
  really deploying one (`star-4`) with `docker compose up`, confirming live reachability, and
  capturing its ground truth — `simulator/scenarios/`, `docs/architecture/scenario_generation.md`.
- **Traffic replay engine** (Phase 19): deterministically re-derives the request sequence and
  relative timing recorded in a Phase 14/15 JSON-Lines workload log (from each record's `sent_at`
  timestamps) and genuinely re-executes it, reusing Phase 14/15's own request senders — proven by
  capturing a real burst-pattern recording against the live lab and replaying it twice, producing
  identical replay logs (excluding wall-clock-only fields) with real observed jitter of roughly
  2-18ms — `simulator/traffic/replay.py`, `docs/architecture/traffic_replay.md`.
- **Observatory validation** (Phase 20): a standalone, repeatable gate (`scripts/validate_observatory.py`)
  that automates Phases 11-13/15's own one-off manual lab checks — expected services, expected
  connectivity (positive and negative/boundary), expected routes, and expected traffic — proven by a
  real run against the live lab (all 5 checks passing) plus a deliberately induced `load-balancer-2`
  outage confirming the gate can actually detect a real problem, not just always pass —
  `scripts/validate_observatory.py`, `docs/architecture/observatory_validation.md`.
- **High-fidelity packet capture** (Phase 21, the first NETTRACE phase): `POST /capture` is real
  for `source=pcap_upload` — a staged file is validated as a genuine, non-empty pcap via Scapy and
  ingested into the canonical `captures/<capture_id>/raw.pcap` artifact layout, proven by a real
  end-to-end run through the live FastAPI app. `source=live_interface` validates the requested
  interface against an authorized allowlist and documents the real, two-step lab-side capture
  workflow (`simulator/capture/live.py`, run inside the lab's `client` container); that lab-side
  half is implemented and unit-verified but not yet run against a real Docker lab in this session
  (no Docker available in this environment) — `backend/nettrace/capture/`,
  `simulator/capture/live.py`, `docs/architecture/packet_capture.md`.
- **Packet normalization** (Phase 22): `normalize_pcap()` reads a real `raw.pcap` via Scapy and
  produces one normalized `Packet` (timestamp, IPs, ports, protocol, size, TCP flags) per real
  captured frame with an IP layer, written to `captures/<capture_id>/packets.jsonl` — proven by a
  real end-to-end run (a real TCP handshake, a UDP packet, and an ICMP packet, ingested and then
  normalized, every field checked against the synthetic input). `direction` is deliberately left
  `unknown` at this stage — it's relative to a flow, and flows are Phase 23 —
  `backend/nettrace/normalize.py`, `docs/architecture/packet_normalization.md`.
- **Five-tuple flow reconstruction** (Phase 23): `GET /flows` is real — given a `capture_id`, it
  normalizes and reconstructs fresh on every request, grouping TCP/UDP packets into bidirectional
  flows and finally resolving each packet's `direction` (the initiator's orientation becomes
  `forward`, the reply becomes `reverse`). `FlowFeatures` is populated with everything honestly
  computable now (packet/byte counts, duration, mean inter-arrival, forward-byte-ratio, burstiness);
  `fingerprinted_protocol` stays `None` and `is_persistent` stays `False`, explicitly deferred to
  Phases 26/28 — proven by a real end-to-end run (a real TCP exchange and a separate UDP exchange,
  ingested then queried, with byte-exact features and correctly resolved directions confirmed both
  in the API response and on disk) — `backend/nettrace/reconstruct.py`,
  `docs/architecture/flow_reconstruction.md`.
- **TCP state tracking** (Phase 24): `Flow.tcp_state` is now real for every TCP flow — a
  retransmission-safe finite state machine walks each flow's packets in order (flags + already-
  resolved direction), landing on `established`/`closing`/`closed`/`reset`/`partial` (a duplicate
  SYN/FIN never corrupts the result). UDP flows keep `tcp_state = None`. Mid-stream TCP *data*
  retransmission detection (by sequence number) remains an honest, documented limitation — `Packet`
  carries no TCP sequence/ack field — proven by a real end-to-end run (three distinct real TCP
  exchanges — full handshake+teardown, handshake+RST, bare mid-stream ACK-only with no SYN —
  ingested then queried, yielding `closed`/`reset`/`partial` exactly as expected) —
  `backend/nettrace/reconstruct.py`, `docs/architecture/tcp_state_tracking.md`.
- **UDP session modeling** (Phase 25): a UDP five-tuple's packets are now split into separate
  session-`Flow`s wherever the gap between consecutive packets exceeds a real, configurable
  idle-timeout (`Settings.udp_session_idle_timeout_seconds`, default 30s, `NETSCOPE_`-overridable —
  NFR-4, no hardcoded thresholds); each session's own first packet resolves its own forward
  direction. TCP flows are unaffected. Proven by a real end-to-end run (a UDP five-tuple with two
  bursts separated by a real gap past the configured timeout, plus a TCP flow with an equally large
  gap): the UDP five-tuple produced exactly 2 real flows, the TCP flow stayed exactly 1 —
  `backend/nettrace/reconstruct.py`, `docs/architecture/udp_session_modeling.md`.
- **Protocol fingerprinting** (Phase 26): `Flow.fingerprinted_protocol` is now real — a small,
  explicit port/transport lookup table (`http`/TCP:80, `tls`/TCP:443, `postgresql`/TCP:5432,
  `redis`/TCP:6379, `dns`/UDP:53), since `Packet` carries no payload for deep packet inspection.
  Scoped to exactly the protocols the lab's own traffic generator produces real traffic for, so every
  entry is independently verifiable; anything else stays honestly `None`, never a guess. Proven by a
  real end-to-end run (HTTP-shaped, DNS-shaped, and unrecognized-port exchanges ingested then
  queried, yielding `"http"`/`"dns"`/`None` exactly as expected) — `backend/nettrace/fingerprint.py`,
  `docs/architecture/protocol_fingerprinting.md`.
- **Encrypted traffic metadata** (Phase 27): four of FR-1.7's five named items (duration, sizes,
  timing, endpoint relationships) were already real via Phases 23/25's `Flow`/`FlowFeatures` fields;
  this phase adds the fifth — real TLS version. `Flow.tls_version` is now populated by parsing a
  `ServerHello` handshake message's cleartext header and (for TLS 1.3) `supported_versions`
  extension — never encrypted, in any TLS version, so this is genuine metadata extraction, not
  decryption. Cross-checked against the lab's own real negotiated version (`TLSv1.3`, Phase 15).
  Proven by a real end-to-end run (a crafted TLS 1.3 handshake ingested then queried, yielding
  `fingerprinted_protocol == "tls"` and `tls_version == "TLS 1.3"` exactly as expected) —
  `backend/nettrace/tls_metadata.py`, `docs/architecture/encrypted_traffic_metadata.md`.
- **Flow feature completion** (Phase 28): every `FlowFeatures` field is now real — no more hardcoded
  placeholders. `destination_diversity`/`port_diversity` are real cross-flow aggregates (distinct
  destination IPs/ports seen, within a capture, across every flow sharing a source IP), and
  `is_persistent` is real five-tuple recurrence detection within a capture — which, given how flows are
  structurally built, only ever fires for UDP (Phase 25's idle-timeout session splitting is the only
  mechanism producing multiple flows from one five-tuple). Proven by a real end-to-end run (two flows
  from one source to two destinations correctly reporting diversity `2`/`2`; a UDP five-tuple
  idle-gap-split into two sessions correctly reporting `is_persistent=True` for both) —
  `backend/nettrace/reconstruct.py`, `docs/architecture/flow_feature_completion.md`.
- **Node discovery** (Phase 29, the first topology-inference phase): `discover_nodes` reads a
  capture's normalized `packets.jsonl` directly (not `flows.jsonl`), so every distinct IP address
  observed as a packet source or destination becomes a real `Node` — including hosts whose only
  traffic is ICMP/OTHER, which flow reconstruction excludes by design. One IP currently maps to
  exactly one node (NAT/multi-homed correlation is a documented, deliberate limitation); nothing is
  persisted to disk yet, and nothing calls this from the API layer yet — both wait on Phase 30 (edge
  discovery) and Phase 32 (the combined probabilistic topology graph). Proven by 8 real unit tests,
  including one that seeds an ICMP-only exchange and confirms both endpoints are discovered as nodes
  while the same fixture produces zero flows from `reconstruct_flows` —
  `backend/nettrace/topology/discovery.py`, `docs/architecture/node_discovery.md`.
- **Edge discovery** (Phase 30): `discover_edges` aggregates a capture's already-reconstructed flows
  (not raw packets — the opposite source choice from node discovery, since `Edge.protocols`/evidence
  need flow-level data) into one `Edge` per communicating node pair, with real
  `observation_count`/`evidence`/`protocols`/timestamps. Edges are undirected (no initiator claim at
  the edge level); an ICMP-only capture produces nodes but zero edges, matching flow reconstruction's
  own documented scope — `backend/nettrace/topology/edges.py`, `docs/architecture/edge_discovery.md`.
- **Probabilistic edge confidence** (Phase 31): `Edge.confidence` is now a real multi-signal score,
  combining Phase 30's packet-volume term with five independent, already-real `Flow`-derived signals
  (TCP handshake completion, protocol fingerprinting, TLS negotiation, five-tuple persistence,
  bidirectionality) via noisy-OR: `confidence = 1 - (1-p_volume) * prod(1 - signal_strength *
  indicator)`, bounded and monotonic by construction — more evidence never lowers confidence, and
  confidence never claims exact certainty. All corroborating signals share one uniform strength
  constant (`edge_confidence_signal_strength`, default `0.3`) since nothing yet justifies weighting
  one signal above another; real calibration remains Phase 32/68's job (ground truth is off-limits at
  inference time). `evidence` now includes a bucket-level summary line explaining which signals fired.
  Proven by 20 real unit tests total (12 from Phase 30 plus 8 new), including isolated
  established-vs-partial, TLS-vs-none, fingerprinted-vs-not, and bidirectional-vs-one-way comparisons,
  a combined-signal monotonicity test, and confirmation that structurally-inapplicable signals (e.g.
  TCP-only signals on a UDP-only edge) never incur a penalty — `backend/nettrace/topology/edges.py`,
  `backend/app/core/config.py`, `docs/architecture/edge_discovery.md`.
- **Probabilistic topology reconstruction** (Phase 32): `GET /topology` is real — `build_topology_graph`
  combines Phase 29's nodes and Phase 30-31's edges into one `TopologyGraph`, recomputed fresh and
  persisted (`experiments/artifacts` `write_json`/`topology_path`) on every call, `graph_id` a stable
  per-capture constant (not a timestamp or content hash, for determinism — NFR-3). A new,
  evaluation-only `compare_topology_to_ground_truth` (`experiments/metrics/topology_comparison.py`)
  matches inferred and ground-truth nodes/edges by resolved IP address (the two sides' id schemes are
  independently generated and not otherwise comparable), treats edges as unordered IP-pairs (honoring
  inference's undirected edges against ground truth's directed declarations), and reports real
  node/edge precision/recall/F1 plus a self-defined `graph_similarity = (node_f1 + edge_f1) / 2` — never
  reachable from any API route, strictly evaluation-only per FR-1.11. Proven by 9 real tests (4 API-level,
  5 comparison-level) — `backend/nettrace/topology/graph.py`, `backend/app/api/routes/topology.py`,
  `experiments/metrics/topology_comparison.py`, `docs/architecture/topology_reconstruction.md`.
- **Behavioral feature store** (Phase 33, the first FLOWMIND phase): `compute_node_behavioral_features`
  computes a real per-node feature vector from any caller-supplied `Flow` list — `distinct_ports`
  (destination-side ports only, a deliberate choice to isolate server-like listening-port signal from
  client ephemeral-port noise), `distinct_protocols`, `distinct_destinations` (outbound fan-out only),
  `mean_flow_duration_seconds`, `outbound_byte_ratio` (real per-flow directionality data reused), and
  `is_persistent_talker`. Deliberately window-agnostic (no time-window decision made here — Phase 34)
  and produces a plain `NodeBehavioralFeatures` dataclass, not yet a `BehavioralFingerprint` (Phase 35)
  — field names match that future schema exactly so assembly will be a plain copy. Proven by 9 real
  tests, including a hand-computed `outbound_byte_ratio` and a real end-to-end run through
  `reconstruct_flows`/`discover_nodes` — `backend/flowmind/features/node_features.py`,
  `docs/architecture/behavioral_feature_store.md`.
- **Multi-window behavior modeling** (Phase 34): `compute_node_features_all_windows` runs Phase 33's
  feature computation over three real, nested trailing windows — short (10s), medium (60s), long
  (300s) — each anchored on the node's *own* latest observed activity, not the whole capture's or
  calendar time, so `long ⊇ medium ⊇ short` by construction. Durations are evidence-graded: short/medium
  match this repo's own real capture/test timescales, long is an explicit, documented extrapolation.
  Still produces a plain feature dict, not a `BehavioralFingerprint` — that assembly is Phase 35's job.
  Proven by 8 real tests, including a hand-verified nesting property and a real end-to-end run —
  `backend/flowmind/features/windows.py`, `docs/architecture/multi_window_behavior_modeling.md`.
- **Node behavioral fingerprints** (Phase 35): `assemble_node_fingerprint`/`assemble_all_node_fingerprints`
  wrap Phase 33-34's per-window feature computation into real, persistable `BehavioralFingerprint`
  instances (`node_id`/`window`/`computed_at` plus the six feature fields, copied verbatim — no new
  computation) — one per node per observation window (all three, not just one), sharing a single
  `computed_at` per batch. Persisted as JSON Lines (`fingerprints_path`, new). `GET /behaviors/{node_id}`
  stays a 501 stub: its Phase-09-fixed response also requires a `RoleClassification`, which doesn't
  exist until Phase 36-37 — wiring it now would mean fabricating a role. Proven by 7 real tests,
  including exact field-copy verification and a real end-to-end run —
  `backend/flowmind/fingerprints/node_fingerprint.py`, `docs/architecture/node_behavioral_fingerprints.md`.
- **Service role inference** (Phase 36): `fit_role_model`/`classify_node_role` implement exactly the
  Naive-Bayes-style classifier `algorithm_selection.md` §2 already selected — per-role Gaussian
  likelihoods for continuous features (destination diversity, mean flow duration, outbound byte
  ratio, port count as an honest proxy for "port set entropy") and Laplace-smoothed Bernoulli
  likelihoods for binary features (persistence, protocol-mix presence, well-known-port presence reusing
  Phase 26's exact port table), combined via Bayes' rule into a real, numerically-stable softmax
  posterior — a genuine `RoleClassification`, not a fabricated one, but not yet validated as
  *calibrated* (Phase 37's job) and not yet trained on real Docker-lab data (no Docker this session —
  verified instead with synthetic labeled fixtures, the same convention every phase's tests already
  use). No model is shipped; `GET /behaviors/{node_id}` stays unwired. Proven by 7 real tests,
  including a protocol-mix-isolation test and a real pipeline-types end-to-end test —
  `backend/flowmind/classification/role_classifier.py`, `docs/architecture/service_role_inference.md`.

### What doesn't exist yet

Calibrated uncertainty, anomaly detection, temporal archaeology, dependency/causal reasoning, the
digital twin, simulation, and counterfactual engines have not been implemented yet — those begin at
Phase 37 and continue through the 69-phase plan. The API surface and data contracts are real and
tested; most of the research intelligence they will eventually serve is not built yet. Nothing in this
repository
currently fabricates results — every phase's completion report documents exactly what was and wasn't
verified by
actual execution.

## Repository layout

```
backend/app/
  models/     Phase 04 data contracts (Pydantic)
  core/       Phase 07-08 observability + configuration
  api/        Phase 09 API routes (versioned /api/v1)
backend/nettrace/
  capture/    Phase 21 PCAP ingestion (pure logic; no Docker/live-socket dependency)
  normalize.py  Phase 22 packet normalization (raw.pcap -> Packet -> packets.jsonl)
  reconstruct.py  Phase 23 five-tuple flow reconstruction (packets.jsonl -> Flow -> flows.jsonl)
  topology/discovery.py  Phase 29 node discovery (packets.jsonl -> Node)
  topology/edges.py  Phase 30-31 edge discovery + probabilistic confidence (flows.jsonl + Node list -> Edge)
  topology/graph.py  Phase 32 topology assembly (Node + Edge lists -> TopologyGraph), real via GET /topology
backend/flowmind/
  features/node_features.py  Phase 33 reusable per-node behavioral features (Flow list + Node -> NodeBehavioralFeatures)
  features/windows.py  Phase 34 multi-window modeling (nested short/medium/long trailing windows)
  fingerprints/node_fingerprint.py  Phase 35 fingerprint assembly (features -> real BehavioralFingerprint)
  classification/role_classifier.py  Phase 36 Naive Bayes role classifier (fingerprint -> RoleClassification)
experiments/
  artifacts/  Phase 10 reproducible artifact I/O + Phase 17 versioned ground-truth manifest
  metrics/    Phase 32 evaluation-only ground-truth comparison (never reachable from backend/)
frontend/     Phase 06 placeholder React/Vite/Tailwind scaffold
simulator/
  docker/         Phase 11-15 multi-tier network laboratory
  traffic/        Phase 14-15 traffic + protocol workload generators, Phase 19 replay engine
  ground_truth/   Phase 16 authoritative ground-truth generator
  scenarios/      Phase 18 controlled network architecture generator
  capture/        Phase 21 lab-side controlled live capture (Scapy sniff/wrpcap)
docs/
  research/       Phase 01-02 problem definition & research questions
  requirements/   Phase 03 system requirements
  architecture/   Phase 04-05, 09-36 design docs
  development/    Phase 06 environment notes
  PROJECT_STATE.md   authoritative, continuously-updated project state
scripts/      setup, validation, ground-truth import-boundary (Phase 17), and (Phase 20)
              observatory validation scripts
```

## Getting started

```bash
bash scripts/setup.sh          # bootstraps .venv + backend deps + frontend npm deps
pytest backend/tests experiments/tests simulator/tests   # run the full test suite (279 tests)
docker compose up --build      # backend (real /capture, placeholder everything else) + frontend dev containers
docker compose -f simulator/docker/docker-compose.yml up -d   # the network lab
python -m scripts.validate_observatory   # Phase 20 gate: verify the lab itself before using it
```

See `docs/development/environment.md` for what's actually been verified to work, and
`docs/architecture/network_laboratory.md` for the lab's topology and how to exercise it.

## Master specification

The full 69-phase execution plan, non-negotiable engineering rules, and acceptance criteria this
project follows are defined in `NETSCOPE (1).pdf` at the repository root. Every phase's completion is
reported using the spec's required format (STATUS/OBJECTIVE/IMPLEMENTED/.../VERIFICATION/NEXT PHASE)
and is never marked complete without actually running and verifying its deliverables.
