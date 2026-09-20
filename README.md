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

## Getting started

**Prerequisites:** Python 3.12, Node 22, Docker (optional, for the containerized backend/frontend
and the network lab).

```bash
bash scripts/setup.sh          # bootstraps .venv + pinned backend deps + frontend npm deps
pytest backend/tests experiments/tests simulator/tests   # run the full test suite (508 tests)
python -m scripts.validate_data_contracts     # Pydantic schema round-trip checks
python -m scripts.check_ground_truth_boundary # static import-boundary guard (spec §4)
```

`scripts/setup.sh` creates `.venv`, installs `requirements-dev.txt`, runs a data-contract/smoke-test
check, and installs `frontend/`'s npm dependencies — safe to re-run on an existing clone.

To run the backend/frontend containers or the network lab:

```bash
docker compose up --build      # backend (real /capture, placeholder everything else) + frontend dev containers
docker compose -f simulator/docker/docker-compose.yml up -d   # the network lab
python -m scripts.validate_observatory   # Phase 20 gate: verify the lab itself before using it
```

See `docs/development/environment.md` for what's actually been verified to work, and
`docs/architecture/network_laboratory.md` for the lab's topology and how to exercise it.

## Project status

**Current phase: 61 of 69 complete** (Phase 21's controlled live capture remains
implemented-and-unit-verified-but-not-yet-Docker-verified — see `docs/architecture/packet_capture.md`).
The failure propagation simulator now composes failure injection, dependency propagation, routing
impact, and itemized service impact into one connected pipeline over any (possibly
failure-modified) `TopologyGraph` — see `docs/architecture/failure_propagation_simulator.md`. Next:
Phase 62.

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
  `/api/v1`, with consistent error handling — `backend/app/api/`. `POST /capture` (Phase 21),
  `GET /flows` (Phase 23, now including real TCP state as of Phase 24), `GET /topology`
  (Phase 32), `GET /history` (Phase 49), `GET /dependencies` (Phase 51), and
  `GET /causal/{dependency_id}` (Phase 56) are real; the other 6 still return a structured 501
  (not yet implemented) — see "What doesn't exist yet" below.
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
- **Uncertainty-aware classification** (Phase 37): `fit_temperature` fits a real, single scalar
  temperature on held-out labeled data by minimizing negative log-likelihood (flattens an
  overconfident posterior, sharpens an underconfident one) — `classify_node_role` gained an optional
  `temperature` parameter (default `1.0`, Phase 36's original behavior unchanged). A separate,
  evaluation-only `evaluate_role_calibration` (`experiments/metrics/role_calibration.py`, mirroring
  Phase 32's `TopologyComparisonResult` precedent — not a `MetricResult`, since no experiment registry
  exists) computes real accuracy, multiclass Brier score, and expected calibration error from
  `RoleClassification` outputs against true-role labels — never reachable from any API route. Neither
  half has been validated against real Docker-lab ground truth this session (no Docker) — verified
  only with synthetic labeled fixtures. Proven by 17 real tests total (12 classifier, 5 calibration),
  including a hand-computed Brier score — `backend/flowmind/classification/role_classifier.py`,
  `experiments/metrics/role_calibration.py`, `docs/architecture/uncertainty_aware_classification.md`.
- **Behavioral baseline** (Phase 38): `build_node_baseline` implements exactly the robust
  median/MAD statistical baseline `algorithm_selection.md` §3 already selected for anomaly detection
  — covering all 6 `BehavioralFingerprint` feature fields via robust median/MAD (destination count,
  flow duration, byte ratio, port count as an entropy proxy), historical value sets (ports, protocols
  — for explicit novelty/set-difference checks), and a historical frequency (persistence). Reports MAD
  honestly un-floored and exposes an explicit cold-start `is_sufficient` flag (`min_observations=5`,
  a documented provisional default). A pure function over a caller-supplied fingerprint history — no
  cross-capture historical store exists yet, and building one is left to a later phase. The
  EWMA-based transient-anomaly-vs-concept-drift decision §3 also names is explicitly Phase 39's job,
  not built here. Proven by 8 real tests, including a hand-computed median/MAD — `backend/flowmind/
  baseline/node_baseline.py`, `docs/architecture/behavioral_baseline.md`.
- **Concept drift detection** (Phase 39): `track_feature_drift`/`track_node_drift` implement exactly
  the EWMA-based mechanism `algorithm_selection.md` §3 already selected — an incremental EWMA seeded
  at Phase 38's robust baseline median, classifying a given deviating sequence as `CONCEPT_DRIFT`
  (the slow-moving EWMA has been pulled measurably away — sustained deviation) or `TRANSIENT_ANOMALY`
  (a blip that reverted before the EWMA could move), populating the real `AnomalyClass` enum
  (Phase 04) for the first time. Deciding *whether* a sequence deviates enough to classify in the
  first place remains explicitly Phase 40's job — calling this on ordinary history vacuously returns
  `TRANSIENT_ANOMALY`, a documented, accepted scope limitation. Proven by 9 real tests, including a
  hand-computed EWMA trace and a mixed scenario correctly separating a drifting feature from a stable
  one — `backend/flowmind/drift/node_drift.py`, `docs/architecture/concept_drift_detection.md`.
- **Multi-dimensional anomaly detection** (Phase 40): `detect_node_anomalies`/
  `detect_node_anomalies_with_drift` implement `algorithm_selection.md` §3's two selected mechanisms —
  robust z-score deviation (`DESTINATIONS`, `TIMING`, `BEHAVIOR`, a new `TRAFFIC_VOLUME` closing a real
  gap via a backward-compatible `total_byte_count` field added to `NodeBehavioralFeatures`/
  `BehavioralFingerprint`/`NodeBehavioralBaseline`) and set-difference novelty (`PORTS`/`PROTOCOLS`,
  reusing Phase 38's historical sets unchanged). `TOPOLOGY` is explicitly never produced — a documented
  scope-out pointing to Phase 45's graph-diff machinery, not a silent gap. A single-fingerprint check
  provisionally labels every anomaly `TRANSIENT_ANOMALY`; a sequence-based check genuinely upgrades
  this via a real call into Phase 39's `track_feature_drift`. Cold-start-guarded via Phase 38's
  `is_sufficient` flag; scores use the same saturating-curve formula as Phase 30/31's confidence.
  Proven by 12 real tests plus 26 re-verified Phase 33/38/39 tests confirming the schema extension
  didn't break anything — `backend/flowmind/anomaly/node_anomaly.py`,
  `docs/architecture/multidimensional_anomaly_detection.md`.
- **Explainable anomalies** (Phase 41): fixed a real formatting divergence — Phase 40's evidence
  always used `.3f` (`"4.000"`), drifted from this project's own Phase 04 contract example
  (`"historical_destinations": "4"`); now whole numbers render as clean integers, and
  `PORTS`/`PROTOCOLS` novelty checks gained a symmetric `current_<label>_count` alongside the
  existing historical count. New `format_anomaly_report` renders any single node's `Anomaly` list
  into the master spec's own literal human-readable report shape (`Node: / <Label>: <value> /
  Evidence: ...`), deriving field labels generically from each anomaly's own evidence — no
  per-dimension hardcoding. Deliberately no new detection signal: specific new-destination identity
  (the spec's illustrative "New destination: X") stays an honest, documented, out-of-scope
  limitation, not silently added or skipped. No persistence or API wiring — `GET /anomalies` remains
  a 501 stub. Proven by 7 new tests plus 4 updated Phase 40 assertions, including a real end-to-end
  run reproducing the master spec's own worked example — `backend/flowmind/anomaly/explain.py`,
  `docs/architecture/explainable_anomalies.md`.
- **FLOWMIND evaluation** (Phase 42): `evaluate_anomaly_detection` scores real Phase 40 anomaly
  output against caller-supplied `LabeledAnomalyEvent` ground truth (deliberately minimal — no
  injected-anomaly dataset generator exists anywhere in this repo yet; RQ3's own `dataset_anomaly`/
  `dataset_noisy` remain future work). Matching is greedy per `(node_id, dimension)`: each label
  claims at most one detection no earlier than its labeled onset. Precision/recall/F1/
  false-negative-rate/detection-latency are always real and computable; false-positive-rate needs a
  countable negative-instance universe that detections alone can't supply, so it's real only when the
  caller supplies `total_checks` (how many detection attempts were actually run), honestly `None`
  otherwise — never fabricated. Mirrors Phase 32/37's "plain dataclass, not `MetricResult`" precedent
  exactly, since no experiment registry exists anywhere to legitimately populate
  `MetricResult.experiment_id`. Proven by 10 real tests including a real end-to-end run through
  `build_node_baseline`/`detect_node_anomalies` — `experiments/metrics/anomaly_evaluation.py`,
  `docs/architecture/flowmind_evaluation.md`.
- **Temporal graph model** (Phase 43, the first Network Archaeology phase): `discover_nodes`/
  `discover_edges`/`build_topology_graph` (Phases 29-32) each gained a backward-compatible `as_of`
  parameter, so `build_topology_graph(..., as_of=t)` is literally `G(t)` — nodes/edges/confidence are
  genuinely recomputed from only the packets/flows observed at or before `t`, not filtered after the
  fact (an edge's confidence is itself computed from all its contributing flows, so post-hoc
  filtering would silently overstate certainty at time `t`; real recomputation lets confidence
  legitimately grow between two `as_of` values instead). `as_of=None` (default) reproduces the exact
  prior, whole-capture behavior. Deliberately narrow: no versioned snapshot identity/persistence
  (`NetworkSnapshot`, explicitly Phase 44's job) and no structural diffing (`GraphChangeEvent`,
  Phase 45's job) — no new `backend/archaeology/` package yet either, an intentional, documented
  choice. `GET /topology` untouched. Proven by 13 new/extended tests across three files, including a
  real end-to-end run against a two-episode synthetic capture — `backend/nettrace/topology/
  {discovery,edges,graph}.py`, `docs/architecture/temporal_graph_model.md`.
- **Network snapshot engine** (Phase 44, the first real code in `backend/archaeology/`):
  `create_snapshot` finally connects three pieces each already designed for this moment —
  `NetworkSnapshot` (Phase 04, never constructed for real before now), `snapshot_path` (reserved
  since Phase 10, never called before now), and Phase 43's `as_of`-aware `build_topology_graph`.
  `captured_at` is passed straight into graph construction as `as_of` *and* stored on the
  `NetworkSnapshot`, so a snapshot's claimed capture time always genuinely matches its graph's
  evidence, never a label decoupled from content. Versioning is per-capture, sequential by
  generation order. Snapshot/graph ids use `-` separators rather than this project's usual `:`,
  since `:` is invalid in a Windows filename and these ids become path components — hit and fixed
  as a real bug during this phase's own test run. Deliberately no deduplication of unchanged
  consecutive snapshots (detecting *whether* something changed is Phase 45's job) and no API wiring
  (no `/snapshots` route exists among Phase 09's 12 fixed endpoint groups at all). Proven by 9 real
  tests including a real end-to-end run against a two-episode synthetic capture —
  `backend/archaeology/snapshots.py`, `docs/architecture/network_snapshot_engine.md`.
- **Graph difference engine** (Phase 45): `diff_snapshots` is the first real use of
  `GraphChangeEvent`/`ChangeType` (Phase 04) — its 5-value enum is the master spec's own bullet
  list verbatim. Diffs two snapshots by plain `node_id`/`edge_id` set comparison, resting on a
  directly-verified (not assumed) property: Phase 43's `as_of` filtering only ever adds evidence as
  `as_of` grows, so an already-observed node/edge's deterministic id is stable across snapshots of
  the same capture — no separate entity-matching problem, unlike Phase 32's ground-truth
  comparison. Attribute changes tracked for edges only (`confidence`, `protocols`) — node attribute
  changes are explicitly never produced, since a `Node`'s only non-identity field (`last_observed`)
  trivially advances with any later traffic and would be pure noise. Every event carries real,
  concrete evidence from construction. Removals are structurally real (verified via a
  reversed-snapshot-order test) but practically vacuous under normal forward-in-time usage, since
  topology reconstruction here is cumulative with no expiry concept — documented, not hidden. No
  persistence or API wiring — a pure function over two already-persisted snapshots. Proven by 10
  real tests including a real end-to-end run producing a human-readable change list —
  `backend/archaeology/diff.py`, `docs/architecture/graph_difference_engine.md`.
- **Behavioral evolution tracking** (Phase 46): `track_node_behavioral_evolution` is the first
  Network Archaeology code to operate on FLOWMIND's `BehavioralFingerprint` (Phase 33-35) rather
  than a `TopologyGraph`/`NetworkSnapshot`. A pure function over a caller-supplied, time-ordered
  list of one node's fingerprints, it walks consecutive pairs and compares all 7 fields — set
  difference for `distinct_ports`/`distinct_protocols`, exact-value inequality for the four
  continuous/count fields (the same no-invented-threshold precedent Phase 45 already set for
  `Edge.confidence`), boolean flip for `is_persistent_talker` — emitting one evidenced
  `BehavioralEvolutionEvent` (a new plain dataclass; no Phase 04 schema is reserved for this,
  unlike `GraphChangeEvent`) per changed field. Deliberately distinct from Phase 39's
  `track_node_drift` (a statistical baseline-relative classification): this is a raw, evidenced
  historical record, not a detector. No real cross-batch fingerprint-history store exists yet
  (Phase 35's `fingerprints.jsonl` is overwritten per batch, not appended) — an honest, documented
  limitation, not a gap. No persistence or API wiring — `GET /behaviors/{node_id}` remains a 501
  stub. Proven by 12 real tests including a real end-to-end run through
  `assemble_node_fingerprint` — `backend/archaeology/behavior_evolution.py`,
  `docs/architecture/behavioral_evolution_tracking.md`.
- **Topology event timeline** (Phase 47): `build_topology_event_timeline` chains Phase 45's
  `diff_snapshots` — unmodified — across every consecutive pair of a capture's own persisted
  `NetworkSnapshot`s (via Phase 44's `list_snapshots`), concatenating the results in generation
  order into one flat, persisted, chronological `GraphChangeEvent` stream (new
  `events_path`/`topology_events.jsonl`, write-through like Phase 32's `topology_path`). No new
  schema (`GraphChangeEvent`'s own docstring already scoped it to "spec Phase 45, 47-48") and no
  new comparison logic — pure assembly over already-real, already-evidenced events. Chains by
  snapshot generation order, not a `captured_at` re-sort — a documented caveat under
  out-of-sequence snapshot creation, equivalent under normal usage. No API wiring — `GET /history`
  stays an untouched 501 stub, explicitly scoped to Phase 49, which will query this stream. Proven
  by 8 real tests, including one confirming the timeline exactly equals a direct concatenation of
  two separate `diff_snapshots` calls — `backend/archaeology/timeline.py`,
  `docs/architecture/topology_event_timeline.md`.
- **Change attribution** (Phase 48): closes the one real gap in FR-1.23's four named attribution
  items — `GraphChangeEvent` gains `affected_flow_ids` (a backward-compatible field addition,
  mirroring Phase 40's own precedent of extending an earlier phase's schema rather than inventing a
  parallel one), populated by extending Phase 45's `diff_snapshots` in place: flows are matched
  against the affected node's or edge's IP set(s), bounded by the same `as_of` (`captured_at`)
  Phase 43/44 already use. New `format_change_attribution`/`format_timeline_attribution`
  (`backend/archaeology/attribution.py`, mirroring Phase 41's `explain.py`) render every change's
  evidence, timestamp, affected node/edge, and affected flows, paired with a fixed, unconditional
  non-causal disclaimer — structural, not a confidence threshold, since this system has no
  causal-inference mechanism at all yet (that begins at Phase 50-56). `ATTRIBUTE_CHANGED` events
  attribute to every flow supporting the edge, not only the ones that drove that specific delta — a
  documented, honest scope limitation, not a gap. No new persistence or API wiring. Proven by 23
  real tests (14 extended `diff.py` tests + 9 new attribution tests), including one confirming an
  ICMP-only node correctly gets `[]`, never a fabricated flow id — `backend/archaeology/diff.py`,
  `backend/archaeology/attribution.py`, `docs/architecture/change_attribution.md`.
- **Historical investigation engine** (Phase 49): `GET /history` is now real, wiring Phase 47's
  persisted `build_topology_event_timeline` stream to a `capture_id` + `start`/`end` window filter
  (inclusive both ends) and the same pagination machinery `GET /flows` already uses — no new schema,
  no new inference logic. Deliberately does not 404 on an unknown `capture_id`: the archaeology
  layer's existing "missing means empty" convention already makes that indistinguishable from "no
  snapshots yet," so it returns an empty, still-200 paginated result instead. Proven by 4 new route
  tests (empty-not-404, full-window, narrow-window exclusion, pagination) plus the 8 existing
  `build_topology_event_timeline` tests this route relies on unchanged —
  `backend/app/api/routes/history.py`, `docs/architecture/historical_investigation_engine.md`.
- **Communication vs. dependency distinction** (Phase 50, new `backend/dependency/` package): the
  type separation FR-1.25 requires (`CommunicationRelationship` vs. `DependencyEdge`) was already
  built in Phase 04; this phase makes the "communicates" side real for the first time.
  `derive_communication_relationships` aggregates Phase 29's `discover_nodes` and Phase 30-31's
  `discover_edges` output, both reused unmodified, into real `CommunicationRelationship` records
  (`persistence_seconds` from `last_observed - first_observed`; `frequency` as
  `observation_count / persistence_seconds`, falling back to raw `observation_count` when
  `persistence_seconds == 0` — a documented, honest edge case, never a `ZeroDivisionError`).
  Candidate pairs come from already-inferred topology edges, not a fresh O(V²) scan, per
  `docs/architecture/algorithm_selection.md`'s committed design. No strength/directionality scoring
  and no API wiring — `GET /dependencies` remains explicitly scoped to Phase 51. Proven by 7 real
  tests, including one confirming every returned relationship's field set is structurally incapable
  of carrying a dependency-shaped claim — `backend/dependency/communication.py`,
  `docs/architecture/communication_vs_dependency.md`.
- **Dependency strength** (Phase 51): `GET /dependencies` is now real. `estimate_dependency_strength`
  computes `DependencyEdge.strength`/`directionality_score` from four of FR-1.26's five signals —
  frequency/persistence (Phase 50's `derive_communication_relationships`, unmodified), directionality
  (Phase 30-31's `_bidirectionality(forward_byte_ratio)`, inverted), and traffic characteristics
  (`Edge.confidence`, Phase 31, reused directly) — combined via the same noisy-OR shape Phase 31's
  edge confidence already uses. Temporal relationships (`temporal_precedence_score`) is deliberately
  excluded — stays at its schema default `0.0` until Phase 52. A small, behavior-preserving refactor
  (`bucket_flows_by_node_pair`, extracted from `discover_edges`) let this phase reuse the same
  per-node-pair flow buckets rather than re-deriving them. Proven by 7 real tests plus 3 new
  `GET /dependencies` route tests — `backend/dependency/strength.py`,
  `docs/architecture/dependency_strength.md`.
- **Temporal precedence analysis** (Phase 52): closes Phase 51's deliberately-left gap —
  `estimate_temporal_precedence` (new `backend/dependency/temporal_precedence.py`) implements
  `algorithm_selection.md`'s already-committed time-lagged cross-correlation algorithm over per-node
  OVERALL flow activity (any counterpart, not just the specific pair — using only the pair's own
  flows would collapse source/target series to near-identical, trivially-zero-lag-correlated data,
  conflating with directionality). Considered and rejected Phase 45/47's `GraphChangeEvent`s (too
  sparse per node) and Phase 46's `BehavioralEvolutionEvent` (no persisted history exists) as the
  primary signal. Scores `0.0` unless the best positive-lag correlation beats the zero-lag baseline
  and is itself positive — a merely-simultaneous relationship is deliberately not counted as
  "precedes." `estimate_dependency_strength` (Phase 51, extended in place) now folds this into a
  fourth noisy-OR term and genuinely sets `temporal_precedence_score` — `DependencyEdge.strength`
  finally reflects all five of FR-1.26's named signals. Deliberately does not build candidate
  causal-relationship generation, explicitly Phase 53's job. Proven by 6 new tests plus a new
  end-to-end dependency-strength test confirming a real, non-zero score flows through into
  `strength` — `backend/dependency/temporal_precedence.py`,
  `docs/architecture/temporal_precedence_analysis.md`.
- **Causal candidate generation** (Phase 53): implements the design boundary already committed at
  Phase 05 — `algorithm_selection.md` explicitly rejected full causal-graph discovery (the PC
  algorithm) in favor of a "scored-candidate approach," so this phase is a filter/promotion step
  over Phase 51/52's `DependencyEdge`s, not a new causal-inference algorithm. `generate_causal_candidates`
  (new `backend/dependency/causal_candidates.py`) promotes a `DependencyEdge` to a `CausalCandidate`
  only when it has BOTH sufficient `strength` AND a real, positive `temporal_precedence_score` —
  strength alone, however high, is deliberately never enough, since it's built entirely from
  correlation/communication-style signals, while temporal precedence specifically supports
  directional, time-ordered evidence — the literal, structural implementation of "do not equate
  correlation with causation." `CausalCandidate` is a plain dataclass (no new Phase 04 schema,
  matching Phase 32/37/42/46's own precedent); every candidate's `rationale` names concrete evidence
  values. `format_causal_candidate` unconditionally appends a new disclaimer stating this is a
  candidate for further investigation, not a confirmed relationship. No persistence or API wiring —
  `GET /causal/{dependency_id}` remains untouched, explicitly scoped to Phase 56. Proven by 10 real
  tests including a real end-to-end run confirming the genuinely-leading pair becomes a candidate
  while unrelated side-conversation edges do not — `backend/dependency/causal_candidates.py`,
  `docs/architecture/causal_candidate_generation.md`.
- **Failure propagation graph** (Phase 54): `propagate_failure` (new
  `backend/dependency/failure_propagation.py`) is the first real use of `PropagationImpact`/
  `ImpactOrder` (Phase 04). A real, previously-undocumented design decision: traverses Phase 53's
  `CausalCandidate`s, not raw `DependencyEdge`s — the latter are undirected (alphabetically-sorted
  node-id pairs, not a real dependency direction), so propagating along them would often follow a
  direction with zero supporting evidence. `CausalCandidate`s are the only edge set in the codebase
  where "if source fails, target is impacted" is actually justified by real evidence. Produces the
  primary impact (the failed node) plus a breadth-first traversal exactly two hops deep (matching
  the spec's literal primary/secondary/tertiary list); each node visited at most once, so cycles
  never loop and diamond patterns never double-count; fully deterministic processing order. Every
  non-primary impact's evidence cites the real strength/temporal-precedence values that caused it.
  No persistence or API wiring — `POST /simulation` remains untouched, explicitly scoped to Phase
  59-61. Proven by 8 real tests including a real end-to-end run over a genuine 3-hop lagged-activity
  capture with no direct shortcut edge — `backend/dependency/failure_propagation.py`,
  `docs/architecture/failure_propagation_graph.md`.
- **Criticality analysis** (Phase 55): `compute_graph_criticality` (new
  `backend/dependency/criticality.py`) implements the algorithm and per-metric rationale already
  committed at Phase 05 — exact NetworkX degree centrality, Brandes' betweenness centrality,
  Tarjan's articulation points — confirmed to operate on `TopologyGraph`, not `DependencyEdge`, by
  Phase 05's own confidence caveat referencing `Edge.confidence`. Resolves that caveat (a
  low-confidence edge shouldn't inflate a criticality score with false precision) via a new
  `mean_incident_edge_confidence` field reported *alongside*, not blended into, the exact centrality
  numbers — avoiding an unjustified confidence-weighting scheme the spec never asked for. Adds
  `path_dependency_impact`, a real graph-theoretic quantity (how many other nodes are stranded
  outside the main remaining component if this node is removed) as a graded refinement of the
  boolean articulation-point flag. `METRIC_RATIONALE` documents why each metric matters as a real,
  quotable in-code artifact. No combined/ranked score — the five metrics stay separate, matching the
  spec's literal "compute... metrics." No persistence or API wiring — no `/criticality` route exists
  among Phase 09's 12 fixed endpoint groups. Proven by 10 real tests (star/chain/cycle topologies
  with hand-computed expected values) including a real end-to-end run over a hub-and-spoke capture
  confirming the gateway is discovered as a genuine articulation point —
  `backend/dependency/criticality.py`, `docs/architecture/criticality_analysis.md`.
- **Causal evidence report** (Phase 56): `GET /causal/{dependency_id}` is now real — the sixth of
  Phase 09's 12 endpoint groups to become so. Two relationship kinds per FR-1.30's own "dependency
  OR propagation" wording: `build_dependency_evidence_report` words `relationship` differently for
  a `CausalCandidate` (Phase 53) vs. a mere `DependencyEdge`, reuses `strength` as `confidence`
  directly, and builds `counter_evidence` only from genuine per-edge signals (zero/low temporal
  precedence, low directionality, non-candidate status) — legitimately empty for a strong
  candidate, verified directly. `limitations` always carries the health-check-poller confounding
  risk and provisional-thresholds caveats regardless of the edge's own numbers.
  `build_propagation_evidence_report` looks up the specific candidate that caused a
  secondary/tertiary impact, rejecting primary impacts (the given input, not an inferred
  relationship) and mismatched candidate lists with `ValueError`. The route takes an explicit
  `capture_id` query parameter — deliberately not parsed out of `dependency_id`'s internal id
  format — and 404s via a new `DependencyNotFoundError` for an unknown id, mirroring
  `GET /flows`/`GET /topology`'s single-resource convention. Proven by 11 real tests plus 3 new API
  tests, including a real end-to-end run through the full dependency-strength →
  causal-candidate → failure-propagation pipeline — `backend/dependency/{causal_evidence,errors}.py`,
  `docs/architecture/causal_evidence_report.md`.
- **Digital twin model** (Phase 57): `build_digital_twin` (new `backend/digital_twin/twin.py`)
  assembles a frozen `DigitalTwin` anchored at a given `NetworkSnapshot` — an assembly phase, not
  new inference, reusing every already-real artifact from earlier phases: Phase 32's
  `TopologyGraph` (via Phase 44's `read_snapshot_graph`), Phase 35's caller-supplied
  `BehavioralFingerprint`s, Phase 47's event timeline filtered to `occurred_at <=
  snapshot.captured_at`, and Phase 51-53's dependencies estimated `as_of=snapshot.captured_at`.
  Routing is honestly represented by the topology graph's own edges (Phase 60's job to add real
  path algorithms); state is the anchoring snapshot itself — confirmed by `SimulationRun`'s own
  `twin_snapshot_id` field (Phase 04). No new schema, no API route — nothing in Phase 09's fixed
  12-endpoint surface names a twin resource yet. Proven by 9 real tests, including a real
  end-to-end run confirming every twin dependency's endpoints are genuine topology node ids —
  `backend/digital_twin/twin.py`, `docs/architecture/digital_twin_model.md`.
- **Digital twin synchronization** (Phase 58): `sync_digital_twin` (new
  `backend/digital_twin/sync.py`) advances a `DigitalTwin` to a new `NetworkSnapshot`, again an
  assembly phase reusing already-real machinery rather than new diff logic — Phase 45's
  `diff_snapshots` for additions/removals/confidence changes, and Phase 46's
  `track_node_behavioral_evolution` (called once per `(node_id, window)`) for behavior changes. A
  fingerprint not resupplied this round is carried forward unchanged into the rebuilt twin rather
  than dropped; one that is resupplied for a node with no prior fingerprint produces no
  behavior-change event (nothing to diff against yet) but is still included. Rebuilds the twin
  fresh via Phase 57's own `build_digital_twin` rather than mutating the old one. No new schema, no
  API route. Proven by 6 real tests, including a real end-to-end run confirming `sync_digital_twin`'s
  outputs exactly match `diff_snapshots`/`track_node_behavioral_evolution` called standalone on the
  same inputs — `backend/digital_twin/sync.py`, `docs/architecture/digital_twin_synchronization.md`.
- **Controlled failure injection** (Phase 59): `apply_failure_scenario` (new
  `backend/simulation/failure_injection.py`) applies a `FailureScenario` (Phase 04's already-real
  `FailureType`/`FailureScenario` schemas — no new schema added) to a `TopologyGraph`. Node/edge
  failure structurally remove the target and its incident edges (edge failure) into an isolated
  graph copy; latency injection, packet loss, bandwidth reduction, and service degradation leave
  the graph structurally unchanged and instead mark the affected edges (`degraded_edge_ids`) for
  Phase 60's path-cost engine to weight — no path-cost computation happens here. Packet
  loss/bandwidth reduction can target an edge directly or a node (all its incident edges); raises
  `ValueError` if neither target is given, or if a target doesn't exist in the graph. No API
  route yet — `POST /simulation` stays scoped through Phase 61. Proven by 11 real tests, including a
  real end-to-end run over a topology discovered from synthetic packets —
  `backend/simulation/failure_injection.py`, `docs/architecture/failure_injection.md`.
- **Dynamic path engine** (Phase 60): `compute_shortest_path`/`compute_alternate_paths`/
  `compute_connectivity`/`compute_route_change` (new `backend/simulation/path_engine.py`) implement
  the algorithms already selected at Phase 05 — Dijkstra (via `nx.shortest_path`), Yen's algorithm
  bounded K (via `nx.shortest_simple_paths`), BFS/union-find (via `nx.connected_components`). Edge
  cost is a genuinely probabilistic `-log(confidence)`, with `PACKET_LOSS`/`BANDWIDTH_REDUCTION`
  adding `-log(1 - ratio)` and `LATENCY_INJECTION` adding a scaled `latency_ms` for edges Phase 59
  marked `degraded_edge_ids` — `SERVICE_DEGRADATION` adds no cost (no quantitative field exists for
  it, an honest limitation, not invented). A missing source/target node returns `None` rather than
  raising — the important real case is a route query for a node a `NODE_FAILURE` just removed.
  "Route changes" (undefined by the spec beyond its own phrase) is interpreted as comparing a
  baseline graph's shortest path against a current/failure-modified graph's for the same pair. No
  pipeline composition, no resilience indicators, no API route — all explicitly later phases' jobs.
  Proven by 15 real tests, including a real end-to-end run confirming an `EDGE_FAILURE` on a
  topology's only connecting edge makes it correctly unreachable —
  `backend/simulation/path_engine.py`, `docs/architecture/dynamic_path_engine.md`.
- **Failure propagation simulator** (Phase 61): `run_failure_propagation_pipeline` (new
  `backend/simulation/failure_propagation_pipeline.py`) composes Phase 59's
  `apply_failure_scenario`, Phase 54's `propagate_failure`, and Phase 60's
  `compute_connectivity`/`compute_route_change` into one connected
  failure→propagation→routing→service-impact pipeline — no new algorithm, no new schema.
  Propagation only runs when the scenario has a `target_node_id`; an edge-only failure honestly
  reports an empty propagation stage (neither endpoint has real causal-direction evidence backing
  it) rather than inventing a synthetic origin. Routing impact is whole-graph connectivity
  before/after plus route-change comparisons bounded to the failure site's own former direct
  neighbors, not an all-pairs explosion. Service impact is the itemized union of
  propagation-affected and newly-unreachable nodes, each optionally annotated with a
  caller-supplied `RoleClassification` or an honest `None` — deliberately un-aggregated, since
  aggregate resilience metrics are Phase 62's job. No API route yet — `POST /simulation` stays
  `NotYetImplemented`, now documented as library-complete with API wiring/persistence deliberately
  unscoped. Proven by 9 real tests, including a real end-to-end run over a topology discovered from
  synthetic packets — `backend/simulation/failure_propagation_pipeline.py`,
  `docs/architecture/failure_propagation_simulator.md`.

### What doesn't exist yet

The digital twin *model* now exists, stays synchronized with new observations, can have controlled
failures injected into an isolated copy of its topology, that topology's paths/connectivity can be
analyzed under failure, and a single connected pipeline now ties failure injection, dependency
propagation, routing impact, and itemized service impact together (Phase 57-61), but aggregate
resilience indicators and the counterfactual scenario engine (Phase 62-69) have not been implemented
yet. The API surface and data contracts are real and tested; most of the research intelligence they
will eventually serve is not built yet. Nothing in this repository currently fabricates results —
every phase's completion report documents exactly what was and wasn't verified by actual execution.

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
  topology/graph.py  Phase 32 topology assembly (Node + Edge lists -> TopologyGraph), real via GET /topology; Phase 43 added as_of for G(t)
backend/flowmind/
  features/node_features.py  Phase 33 reusable per-node behavioral features (Flow list + Node -> NodeBehavioralFeatures)
  features/windows.py  Phase 34 multi-window modeling (nested short/medium/long trailing windows)
  fingerprints/node_fingerprint.py  Phase 35 fingerprint assembly (features -> real BehavioralFingerprint)
  classification/role_classifier.py  Phase 36-37 Naive Bayes role classifier + temperature scaling
  baseline/node_baseline.py  Phase 38 robust median/MAD behavioral baseline + historical novelty sets
  drift/node_drift.py  Phase 39 EWMA-based transient-anomaly-vs-concept-drift classifier
  anomaly/node_anomaly.py  Phase 40 multi-dimensional anomaly detection (5 of 7 dimensions; TOPOLOGY deferred to Phase 45)
  anomaly/explain.py  Phase 41 human-readable anomaly report rendering (Anomaly list -> spec-shaped report string)
backend/archaeology/
  snapshots.py  Phase 44 versioned network snapshot generation (capture_id + captured_at -> NetworkSnapshot + persisted TopologyGraph)
  diff.py  Phase 45 graph difference engine (two NetworkSnapshots -> List[GraphChangeEvent])
  behavior_evolution.py  Phase 46 behavioral evolution tracking (one node's BehavioralFingerprint history -> List[BehavioralEvolutionEvent])
  timeline.py  Phase 47 topology event timeline (chains diff_snapshots across a capture's snapshots -> persisted List[GraphChangeEvent])
  attribution.py  Phase 48 change attribution (GraphChangeEvent -> human-readable report with evidence, timestamp, affected flows/nodes, non-causal disclaimer)
backend/dependency/
  communication.py  Phase 50 communication relationship derivation (Node + Edge lists -> List[CommunicationRelationship], no dependency scoring)
  strength.py  Phase 51 dependency strength estimation (CommunicationRelationship + Edge -> List[DependencyEdge], real via GET /dependencies); Phase 52 folds in real temporal_precedence_score
  temporal_precedence.py  Phase 52 temporal precedence analysis (per-node flow activity -> time-lagged cross-correlation score)
  causal_candidates.py  Phase 53 causal candidate generation (DependencyEdge list -> List[CausalCandidate], strength + temporal precedence both required)
  failure_propagation.py  Phase 54 failure propagation graph (CausalCandidate list + failed node -> List[PropagationImpact], primary/secondary/tertiary)
  criticality.py  Phase 55 criticality analysis (TopologyGraph -> GraphCriticalityReport: degree/betweenness/articulation points/path dependency/connectivity)
  causal_evidence.py  Phase 56 causal evidence reports (DependencyEdge/PropagationImpact -> CausalEvidenceReport), real via GET /causal/{dependency_id}
  errors.py  Phase 56 DependencyNotFoundError (404 for an unknown dependency_id)
backend/digital_twin/
  twin.py  Phase 57 digital twin model (NetworkSnapshot + capture -> DigitalTwin: topology, behavior, history, dependencies), no API route yet
  sync.py  Phase 58 digital twin synchronization (DigitalTwin + new NetworkSnapshot -> TwinSyncResult: rebuilt twin + structural/behavior change events), no API route yet
backend/simulation/
  failure_injection.py  Phase 59 controlled failure injection (TopologyGraph + FailureScenario -> FailureInjectionResult: isolated graph copy + removed/degraded edge ids), no API route yet
  path_engine.py  Phase 60 dynamic path engine (TopologyGraph [+ FailureInjectionResult] -> PathResult/ConnectivityResult/RouteChange via Dijkstra/Yen's/BFS), no API route yet
  failure_propagation_pipeline.py  Phase 61 connected failure->propagation->routing->service-impact pipeline (TopologyGraph + FailureScenario + CausalCandidate list [+ RoleClassification map] -> FailurePipelineResult), no API route yet
experiments/
  artifacts/  Phase 10 reproducible artifact I/O + Phase 17 versioned ground-truth manifest
  metrics/    Phase 32/37/42 evaluation-only ground-truth/calibration/anomaly-detection scoring (never reachable from backend/)
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
  architecture/   Phase 04-05, 09-40 design docs
  development/    Phase 06 environment notes
  PROJECT_STATE.md   authoritative, continuously-updated project state
scripts/      setup, validation, ground-truth import-boundary (Phase 17), and (Phase 20)
              observatory validation scripts
```

## Master specification

The full 69-phase execution plan, non-negotiable engineering rules, and acceptance criteria this
project follows are defined in `NETSCOPE (1).pdf` at the repository root. Every phase's completion is
reported using the spec's required format (STATUS/OBJECTIVE/IMPLEMENTED/.../VERIFICATION/NEXT PHASE)
and is never marked complete without actually running and verifying its deliverables.
