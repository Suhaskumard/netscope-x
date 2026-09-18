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

**Current phase: 21 of 69 (PCAP ingestion complete and real-verified; controlled live capture
implemented and unit-verified, live-Docker-lab verification pending — see
`docs/architecture/packet_capture.md`).** Next: Phase 22 — Packet Normalization.

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
  `/api/v1`, with consistent error handling — `backend/app/api/`. `POST /capture` is real as of
  Phase 21; the other 11 still return a structured 501 (not yet implemented) — see "What doesn't
  exist yet" below.
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

### What doesn't exist yet

Flow reconstruction, topology inference, behavioral modeling, anomaly detection, digital twin,
simulation, and counterfactual engines have not been implemented yet — those begin at Phase 22 and
continue through the 69-phase plan. The API surface and data contracts are real and tested; most of
the research intelligence they will eventually serve is not built yet. Nothing in this repository
currently fabricates results — every phase's completion report documents exactly what was and wasn't
verified by actual execution.

## Repository layout

```
backend/app/
  models/     Phase 04 data contracts (Pydantic)
  core/       Phase 07-08 observability + configuration
  api/        Phase 09 API routes (versioned /api/v1)
backend/nettrace/
  capture/    Phase 21 PCAP ingestion (pure logic; no Docker/live-socket dependency)
experiments/
  artifacts/  Phase 10 reproducible artifact I/O + Phase 17 versioned ground-truth manifest
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
  architecture/   Phase 04-05, 09-21 design docs
  development/    Phase 06 environment notes
  PROJECT_STATE.md   authoritative, continuously-updated project state
scripts/      setup, validation, ground-truth import-boundary (Phase 17), and (Phase 20)
              observatory validation scripts
```

## Getting started

```bash
bash scripts/setup.sh          # bootstraps .venv + backend deps + frontend npm deps
pytest backend/tests experiments/tests simulator/tests   # run the full test suite (153 tests)
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
