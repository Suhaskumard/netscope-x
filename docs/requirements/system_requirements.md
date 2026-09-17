# NETSCOPE-X — System Requirements

Phase 03 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 03 — SYSTEM REQUIREMENTS").
Requirements below are derived from, and cross-referenced to, `docs/research/problem_definition.md`
(Phase 01), `docs/research/research_questions.md` (Phase 02), and the master spec's own non-negotiable
rules. This document does not invent new obligations beyond what those sources already establish — it
organizes them into testable requirement statements. Requirement IDs are stable identifiers for later
traceability (e.g., in Phase 04 data contracts and Phase 69 acceptance testing).

---

## 1. Functional requirements

Organized by pipeline stage, following the canonical data flow (spec §9: PCAP → Packet → Normalized
Packet → Flow → Flow Features → Node/Edge Candidates → Probabilistic Network Graph → Behavioral
Fingerprints → Baseline → Anomalies → Temporal Snapshots → Dependency Graph → Digital Twin →
Simulation → Counterfactual Scenario → Experimental Validation).

### 1.1 Capture and normalization
- **FR-1.1** The system shall ingest PCAP files and support controlled live capture, restricted to
  authorized lab interfaces (spec Phase 21; problem_definition.md §4).
- **FR-1.2** The system shall normalize packets to a consistent schema: timestamp, source/destination
  IP, ports, protocol, size, direction, transport info (spec Phase 22).

### 1.2 Flow reconstruction
- **FR-1.3** The system shall reconstruct bidirectional five-tuple flows for TCP and UDP (spec
  Phase 23).
- **FR-1.4** The system shall track TCP state (SYN/SYN-ACK/ACK/FIN/RST, retransmissions, partial
  sessions) (spec Phase 24).
- **FR-1.5** The system shall model UDP sessions using endpoint, port, and timing-window heuristics
  (spec Phase 25).
- **FR-1.6** The system shall perform protocol fingerprinting from observable evidence only, and shall
  not claim protocol coverage it cannot support (spec Phase 26; RQ2 in research_questions.md).
- **FR-1.7** The system shall extract permitted metadata from encrypted traffic (TLS version,
  duration, sizes, timing, endpoint relationships) without attempting decryption (spec Phase 27).
- **FR-1.8** The system shall compute per-flow features: packet/byte statistics, duration, burstiness,
  inter-arrival times, directionality, destination/port diversity, connection persistence (spec
  Phase 28).

### 1.3 Topology inference
- **FR-1.9** The system shall infer candidate nodes and edges exclusively from observed evidence, with
  no access to laboratory ground truth at inference time (spec §4; Phase 29–30).
- **FR-1.10** Every inferred edge shall carry a confidence score, supporting evidence, observation
  count, timestamps, and protocol list — never an arbitrary/unjustified confidence value (spec
  Phase 31).
- **FR-1.11** The system shall produce a complete probabilistic topology graph (nodes, edges,
  confidence, evidence, timestamps, protocols) and support comparison against ground truth for
  evaluation purposes only (spec Phase 32; RQ1).

### 1.4 Behavioral intelligence (FLOWMIND)
- **FR-1.12** The system shall build reusable behavioral feature representations per node (spec
  Phase 33) across short/medium/long observation windows (Phase 34).
- **FR-1.13** The system shall generate per-node behavioral fingerprints from traffic, ports,
  protocols, timing, destinations, directionality, and persistence (spec Phase 35).
- **FR-1.14** The system shall infer a service role per node (Client, Gateway, API, Database, Cache,
  DNS, Worker, Load Balancer, Unknown) with a calibrated confidence distribution across candidate
  roles, not a single hard label (spec Phase 36–37; RQ2).
- **FR-1.15** The system shall maintain a behavioral baseline of normal behavior derived from
  historical observations (spec Phase 38).
- **FR-1.16** The system shall distinguish temporary anomalies from persistent behavioral evolution
  (concept drift) (spec Phase 39; RQ3/RQ4).
- **FR-1.17** The system shall detect multi-dimensional anomalies (volume, destinations, ports,
  protocols, timing, topology, behavior) (spec Phase 40).
- **FR-1.18** Every reported anomaly shall include concrete supporting evidence (e.g., historical vs.
  current destination counts, specific new ports observed) — never a bare label (spec Phase 41).
- **FR-1.19** The system shall measure and report FLOWMIND's own precision, recall, F1,
  false-positive rate, false-negative rate, and detection latency against labeled experiments (spec
  Phase 42).

### 1.5 Temporal intelligence (Network Archaeology)
- **FR-1.20** The system shall represent the network as a time-indexed graph G(t), not only a static
  snapshot (spec Phase 43).
- **FR-1.21** The system shall generate versioned network snapshots (spec Phase 44) and compute
  structural diffs between them (node/edge additions/removals, attribute changes) (spec Phase 45).
- **FR-1.22** The system shall track behavioral evolution per node over time (spec Phase 46) and
  expose a chronological topology event timeline (spec Phase 47).
- **FR-1.23** The system shall attribute detected changes to observation evidence, timestamps, and
  affected flows/nodes, and shall not claim a causal explanation without sufficient evidence (spec
  Phase 48).
- **FR-1.24** The system shall support historical investigation queries (e.g., "what changed between
  time A and time B?") returning structured results (spec Phase 49).

### 1.6 Dependency and causal reasoning
- **FR-1.25** The system shall explicitly distinguish "A communicates with B" from "A depends on B" —
  communication alone shall never automatically imply dependency (spec Phase 50; RQ5).
- **FR-1.26** The system shall estimate dependency strength from frequency, persistence,
  directionality, temporal relationships, and traffic characteristics (spec Phase 51).
- **FR-1.27** The system shall analyze temporal precedence between component changes as one input to
  dependency/causal candidate generation, without equating correlation with causation (spec
  Phase 52–53).
- **FR-1.28** The system shall represent failure propagation as a multi-order impact graph (primary →
  secondary → tertiary impact) (spec Phase 54).
- **FR-1.29** The system shall compute graph criticality metrics (degree, betweenness, articulation
  points, path dependency, connectivity) with documented rationale for each metric's relevance (spec
  Phase 55).
- **FR-1.30** For every inferred dependency or propagation relationship, the system shall produce a
  causal evidence report containing: relationship, evidence, confidence, counter-evidence, and
  limitations (spec Phase 56).

### 1.7 Digital twin, simulation, and counterfactuals
- **FR-1.31** The system shall build a computational digital twin combining topology, behavior,
  history, dependencies, routing, and state (spec Phase 57), kept synchronized with new observations,
  including additions, removals, behavior changes, and confidence changes (spec Phase 58).
- **FR-1.32** The system shall support controlled failure injection: node failure, edge failure,
  latency, packet loss, bandwidth reduction, service degradation (spec Phase 59).
- **FR-1.33** The system shall compute shortest paths, alternate paths, path costs, route changes, and
  disconnected components on the (possibly failure-modified) graph (spec Phase 60).
- **FR-1.34** The system shall simulate failure → dependency propagation → routing impact → service
  impact as a connected pipeline, not isolated stages (spec Phase 61).
- **FR-1.35** The system shall compute resilience indicators: connectivity, reachable-node ratio,
  affected services, path degradation, bottleneck emergence, alternative-path availability (spec
  Phase 62).
- **FR-1.36** The system shall support a structured counterfactual scenario language (REMOVE node,
  REMOVE edge, INCREASE latency, REDUCE bandwidth, INCREASE traffic, ADD route) (spec Phase 64) and
  execute counterfactuals on an isolated alternate graph state that never mutates the real baseline
  (spec Phase 65).
- **FR-1.37** The system shall compare baseline vs. counterfactual outcomes across paths,
  connectivity, latency, affected services, bottlenecks, and propagation (spec Phase 66).

### 1.8 Experimentation and validation
- **FR-1.38** The system shall compare digital-twin/counterfactual predictions against actual
  controlled experiment outcomes and shall not claim correctness without this measurement (spec
  Phase 63, 66; RQ6/RQ7).
- **FR-1.39** The system shall generate experiment recommendations from measurable structural evidence
  (e.g., high-criticality node → suggest removal experiment, with stated reasoning) (spec Phase 67).
- **FR-1.40** The system shall support a full experimental matrix (topology complexity ×
  observation-completeness sweep) with reproducible, quantitatively evaluated results across topology
  reconstruction, role inference, anomaly detection, temporal analysis, causal analysis, PathForge,
  counterfactuals, and the four minimum ablation studies (spec Phase 68).

### 1.9 API surface
- **FR-1.41** The system shall expose versioned, typed API endpoints for: `/capture`, `/flows`,
  `/topology`, `/behaviors`, `/anomalies`, `/history`, `/dependencies`, `/causal`, `/simulation`,
  `/counterfactual`, `/experiments`, `/metrics` (spec Phase 09), each validating input and returning
  consistent, typed error responses (spec §"API DESIGN PRINCIPLES").

### 1.10 Frontend
- **FR-1.42** The frontend shall implement, at minimum, the areas specified in spec §12: Overview,
  Topology Explorer, Node Investigation, Timeline, Anomaly Investigation, Causal Analysis, Simulation,
  Counterfactual, Experiment Lab — each showing real data from the API, not placeholder content.

---

## 2. Non-functional requirements

Derived from spec §7 (Architectural Principles).

- **NFR-1** Modular architecture: each pipeline stage (NETTRACE, FLOWMIND, Archaeology, Causal,
  PathForge, Counterfactual, Experiments) is an independently testable module with a defined
  input/output contract (spec §9).
- **NFR-2** Typed interfaces throughout (Pydantic models on the backend, TypeScript types on the
  frontend).
- **NFR-3** Deterministic processing wherever possible — given the same input and configuration
  (including random seed), a module produces the same output, to support reproducibility (ties to
  Reproducibility requirements below).
- **NFR-4** Configuration-driven behavior — no hardcoded paths, thresholds framed as "magic numbers"
  must be named/configurable and documented.
- **NFR-5** Structured logging with request IDs and experiment IDs, module-level logging, and
  performance timing (spec Phase 07).
- **NFR-6** Versioned APIs.
- **NFR-7** No global state, no hidden side effects, no circular imports, no giant files.
- **NFR-8** No hardcoded network topology or service classifications anywhere in the inference path
  (spec §4, §7) — this is treated as a correctness violation, not a style issue.
- **NFR-9** No unnecessary abstractions or overengineering without measurable benefit (spec §7); avoid
  introducing infrastructure components (databases, caches, message queues) without a clearly stated
  purpose (spec §6, Storage).

---

## 3. Performance requirements

Derived from spec §14. Correctness must be established before optimization; all figures below are
requirements to **measure and report**, not target numbers to fabricate.

- **PERF-1** The system shall measure and report packet processing throughput (packets/sec) under
  realistic lab traffic.
- **PERF-2** The system shall measure and report flow processing time (time to reconstruct flows from
  a given packet volume).
- **PERF-3** The system shall measure and report graph construction time (time to go from flows to a
  probabilistic topology graph).
- **PERF-4** The system shall measure and report memory usage under each dataset size
  (small/medium/large — spec §19).
- **PERF-5** The system shall measure and report API latency per endpoint.
- **PERF-6** The system shall measure and report frontend graph-rendering performance, especially for
  large graphs (spec §"Frontend testing").
- **PERF-7** The system shall measure and report simulation/counterfactual execution time.
- **PERF-8** Any scalability claim must be backed by a benchmark; absent a benchmark, no scalability
  claim shall be made (spec §14, §21).

---

## 4. Reliability requirements

Derived from spec §15 (Error Handling) — the system shall fail gracefully (structured error, not a
crash) for each of the following:

- **REL-1** Corrupted PCAP files.
- **REL-2** Malformed packets.
- **REL-3** Missing required fields in captured data.
- **REL-4** Incomplete flows (e.g., missing FIN/RST).
- **REL-5** Unknown/unsupported protocols.
- **REL-6** Duplicate packets.
- **REL-7** Out-of-order packets.
- **REL-8** Invalid scenario/counterfactual definitions.
- **REL-9** Disconnected graphs (e.g., after a simulated failure isolates a component).
- **REL-10** Empty datasets.
- **REL-11** Very large datasets (must degrade in performance, not correctness or crash).
- **REL-12** Unavailable network interfaces during a live-capture request.

---

## 5. Security requirements

Derived from spec §16 and the Safety Boundary (spec §5).

- **SEC-1** All external input (uploaded PCAPs, API request bodies, scenario definitions) shall be
  validated before use.
- **SEC-2** Any subprocess invocation (e.g., tshark) shall use safe, non-shell argument passing — the
  system shall never execute arbitrary user-supplied shell commands.
- **SEC-3** Uploaded files shall be validated (type, size limits) before processing.
- **SEC-4** File paths derived from user input shall be validated/sanitized to prevent path traversal.
- **SEC-5** Resource limits shall be enforced on capture, processing, and simulation operations to
  prevent unbounded resource consumption from a single request.
- **SEC-6** Packet capture shall be restricted to explicitly authorized lab interfaces; the system
  shall not perform capture, scanning, or active traffic generation against systems the operator does
  not own or has not explicitly configured for testing (spec §5).
- **SEC-7** No secrets shall be committed to source control; configuration/secrets handling is
  addressed structurally in Phase 08.
- **SEC-8** Authentication and API-abuse protection shall be added if/when the system is exposed
  beyond a local/lab context (deferred design decision — see Known Limitations below).

---

## 6. Reproducibility requirements

Derived from spec §20 (Research Reproducibility) and §17 (Ground-Truth Integrity).

- **REPRO-1** Every experiment shall record: experiment_id, dataset_version, code_version,
  configuration, random_seed, timestamp, environment, parameters, and results.
- **REPRO-2** Experiments shall be rerunnable from their recorded configuration and shall produce
  equivalent results given the same inputs and seed (ties to NFR-3, determinism).
- **REPRO-3** Ground-truth artifacts shall be versioned and hashed to detect accidental drift or
  contamination (spec Phase 17).
- **REPRO-4** Ground-truth data shall be usable only for generating experiments, validating results,
  and computing metrics — never as an input to the inference pipeline itself (spec §4; restated from
  problem_definition.md §2/§6).
- **REPRO-5** Each dataset (spec §19: dataset_small, _medium, _large, _dynamic, _failure, _anomaly,
  _incomplete, _noisy) shall carry a description, generation procedure, ground truth, expected
  properties, version, and checksum.

---

## Traceability summary

| Category | Primary spec sections | Primary Phase-02 RQ links |
|---|---|---|
| Functional | §9, §"PHASE 09", §12, Phases 21–68 | RQ1–RQ7 (all) |
| Non-functional | §7 | — |
| Performance | §14 | — |
| Reliability | §15 | — |
| Security | §5, §16 | — |
| Reproducibility | §4, §17, §20 | RQ1, RQ5, RQ6, RQ7 (ground-truth/experiment integrity) |

## Known limitations

- This document defines requirements; it does not yet define the data schemas that will make many of
  these requirements testable (that is Phase 04 — Architecture and Data Contracts).
- SEC-8 (authentication/API-abuse protection) is deliberately left as a deferred decision: the current
  problem definition scopes NETSCOPE-X to a controlled lab/local-research context, so full
  authentication may be unnecessary; this will be revisited if the deployment context changes.
- No performance targets (specific numbers) are stated, per PERF-8 and spec §21 — targets will emerge
  from actual benchmarking once a working pipeline exists.

## Status

This document satisfies Phase 03 of the 69-phase execution plan: functional, non-functional,
performance, reliability, security, and reproducibility requirements are all present above, each
traceable to spec sections and/or Phase 02 research questions.
