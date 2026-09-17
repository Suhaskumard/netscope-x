# NETSCOPE-X — Research Problem Definition

Phase 01 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 01 — RESEARCH PROBLEM
FORMALIZATION"). This document defines the problem NETSCOPE-X solves, the assumptions it operates
under, what it can and cannot observe, the environments it supports, its limitations and boundaries,
who it is for, and how success will be measured.

## 1. Exact problem

Given only network traffic and other permitted observable telemetry from a network whose structure
is *not* known in advance, reconstruct a probabilistic operational model of that network and reason
about it: what nodes exist, how they communicate, what roles they play, what their normal behavior
looks like, how that behavior and topology change over time, which relationships are dependencies
rather than incidental communication, how failures would propagate through those dependencies, which
components are structurally critical, and what would happen under hypothetical changes to the
network — with every claim traceable to observed evidence and validated where possible against a
controlled ground truth.

This is explicitly **not** the problem of building a packet sniffer, an intrusion-detection system,
or a chatbot that talks about a network. The intelligence must come from packet analysis, flow
reconstruction, graph construction, statistical/probabilistic inference, temporal graph analysis,
dependency modeling, graph algorithms, simulation, and controlled experiments. An LLM, if used at
all, is restricted to explaining structured evidence already produced by that pipeline — it must
never invent topology, evidence, or metrics (see §6 below and spec §23).

## 2. Assumptions

- NETSCOPE-X observes a network from one or more vantage points with packet- or flow-level
  visibility (via PCAP ingestion or controlled live capture). It does not assume host-level agents,
  application instrumentation, or privileged access to endpoints beyond what is visible on the wire.
- Traffic may be partially or fully encrypted. NETSCOPE-X assumes it can use only what is legitimately
  observable without decryption: headers, timing, sizes, connection metadata, and permitted metadata
  such as TLS version/handshake fields — never plaintext payload content.
- The system assumes it is deployed and evaluated inside a laboratory environment that the operator
  owns or has explicitly configured for testing (Docker / Linux network namespaces), not against
  arbitrary production or third-party infrastructure.
- A **ground-truth topology** exists in the laboratory for evaluation purposes only. NETSCOPE-X's
  inference pipeline assumes it has no access to this ground truth at inference time — ground truth
  may be used solely to generate experiments, validate results, and compute accuracy metrics after
  the fact (spec §4). Any design that lets ground truth leak into the inference path is treated as a
  correctness bug, not a shortcut.
- Observability may be incomplete (partial capture, dropped packets, subset of vantage points). The
  system assumes it must degrade gracefully and report reduced confidence rather than assume complete
  visibility.

## 3. Observability model

**What NETSCOPE-X can observe (its evidence base):**
- Raw packets from PCAP files or controlled live capture (Phase 21).
- Normalized packet fields: timestamps, source/destination IP, ports, protocol, size, direction,
  transport-layer details (Phase 22).
- Reconstructed bidirectional flows (5-tuple) with TCP state (SYN/SYN-ACK/ACK/FIN/RST,
  retransmissions, partial sessions) and UDP session modeling via timing/endpoint heuristics
  (Phases 23–25).
- Protocol fingerprints inferred from observable evidence (not from claiming to fully parse every
  protocol) (Phase 26).
- Encrypted-traffic *metadata* only — TLS version, connection duration, packet-size distributions,
  timing, endpoint relationships (Phase 27). Payload decryption is explicitly out of scope.
- Derived flow-level statistics: packet/byte counts, duration, burstiness, inter-arrival times,
  directionality, destination/port diversity, connection persistence (Phase 28).

**What NETSCOPE-X cannot and will not observe or claim:**
- Decrypted application payload content.
- Host-internal state (running processes, filesystem, memory) unless a future phase explicitly adds
  such a source and updates this document.
- Ground-truth topology, roles, or dependency labels at inference time (see Assumptions above).
- Full protocol coverage for every possible application protocol — coverage is limited to what
  protocol fingerprinting can actually support and must be stated as such, not overclaimed.

## 4. Supported network environments

- **In scope**: controlled, owned laboratory networks built with Docker and/or Linux network
  namespaces, matching the multi-tier pattern introduced later in the spec (client → gateway → load
  balancer → API services → cache/database/worker/DNS/external-service simulator), plus additional
  generated topology archetypes (simple chain, star, multi-tier, redundant, multi-path, dynamic
  service network — Phase 18).
- **Out of scope for active experimentation**: any external, third-party, or production network.
  NETSCOPE-X may ingest a PCAP captured elsewhere for offline analysis, but active traffic
  generation, failure injection, routing experiments, and live capture are restricted to the
  controlled laboratory (spec §5, Safety Boundary). No unauthorized scanning or destructive testing
  against infrastructure the operator does not own or has not explicitly authorized.

## 5. Limitations

- Confidence in inferred nodes, edges, and roles degrades as observability completeness decreases;
  this degradation must be measured (Phase 68 observation-completeness sweep: 100/90/75/50/25%), not
  assumed away.
- Communication observed between two nodes does not by itself establish a dependency — the system
  must distinguish "A communicates with B" from "A depends on B" (Phase 50) and will report
  uncertainty explicitly rather than collapsing the two.
- Causal and dependency claims are inferred from correlation, temporal precedence, and structural
  evidence; they are not proof of causation. Every such claim must ship with evidence, confidence,
  counter-evidence, and limitations (Phase 56) — never a bare assertion.
- Protocol and role classification is uncertainty-aware, not binary; low-confidence or "Unknown"
  outcomes are valid, expected outputs, not failures to be hidden.
- Performance and scalability claims will not be made without benchmarks (Phase 68/69); if an
  algorithm fails under low observability or at scale, that failure is reported, not concealed
  (spec §21, "No Fake Metrics").

## 6. Research boundaries

- No fabricated results, metrics, screenshots, test counts, accuracy values, or successful
  executions — every reported number must come from an actual execution against real data (spec
  §21, "No Fake Metrics"; §14, "Never fabricate execution").
- No hardcoded topology, hardcoded service classifications, or predetermined answers standing in for
  genuine inference (spec §3, "Real implementation over fake implementation").
- If an LLM/AI explanation layer is added in a later phase, it operates strictly downstream of
  structured evidence (topology, metrics, confidence values already computed by the deterministic
  pipeline) and must never fabricate topology, invent packet evidence, invent metrics, replace core
  inference/graph algorithms, or make unsupported causal claims (spec §23).
- No unauthorized scanning, no targeting of systems the operator does not own/control, no destructive
  testing against production infrastructure (spec §5).

## 7. Intended users

- **Network and security researchers** evaluating topology-inference, anomaly-detection, and
  dependency/causal-reasoning techniques against a reproducible, ground-truth-backed testbed.
- **Technically strong reviewers/interviewers** assessing the project's engineering quality and
  scientific validity (spec §39: "must be something that can be demonstrated to technically strong
  interviewers and defended academically").
- **Developers extending the system** — the modular architecture (NETTRACE / FLOWMIND / Archaeology
  / Causal / PathForge / Counterfactual / Experiments) is meant to be legible and extensible, not a
  monolith.
- **Not** intended as an operational SOC/NOC production monitoring tool, an intrusion-detection
  product, or a generic admin dashboard (spec §35, "What Not To Do").

## 8. Success criteria

Directly adopted from the spec's Final Success Criteria (§36), restated as this project's acceptance
bar. The project is successful only if it can demonstrate all of the following, each backed by an
actual executed experiment rather than an assertion:

| # | Criterion | What must be shown |
|---|---|---|
| A | Observation | Actual traffic can be processed (real PCAP/capture in, structured output out). |
| B | Reconstruction | Topology can be inferred from observation alone, without ground-truth leakage. |
| C | Behavioral intelligence | Node behavior can be modeled from observed flow/timing/protocol features. |
| D | Temporal intelligence | Topology and behavior changes over time can be detected and attributed to evidence. |
| E | Dependency reasoning | Observed communication can be analyzed for probable dependency, distinct from mere communication. |
| F | Digital twin | The inferred system state can be represented computationally and kept in sync with new observations. |
| G | Simulation | Controlled failures (node/edge/latency/loss/bandwidth/degradation) can be simulated on the twin. |
| H | Counterfactuals | Hypothetical "what if" scenarios can be evaluated without mutating the real baseline. |
| I | Validation | Simulation/counterfactual predictions can be compared against real, controlled experiments and the gap measured. |
| J | Research evidence | Results (precision/recall/F1/accuracy/etc.) are reproducible, versioned, and quantitatively evaluated — not asserted. |

Phase-specific measurable research questions and hypotheses (topology reconstruction, behavioral
inference, anomaly detection, temporal change detection, dependency inference, failure propagation,
counterfactual simulation) are deferred to **Phase 02 — Research Questions and Hypotheses**, which
builds on this document's success-criteria table.

## Status

This document satisfies Phase 01 of the 69-phase execution plan. It is documentation-only — there is
no code to execute or test for this phase. Verification consists of confirming this file exists and
covers all eight required elements from the spec (problem, assumptions, observability model,
supported environments, limitations, research boundaries, intended users, success criteria), which it
does above.
