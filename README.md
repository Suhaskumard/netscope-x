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

**Current phase: 15 of 69 complete.** Next: Phase 16 — Ground-Truth Generator.

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
  `/api/v1`, with consistent error handling — `backend/app/api/`. Every endpoint currently returns a
  structured 501 (not yet implemented), since the pipeline stages that would serve real data start at
  Phase 21 — see "What doesn't exist yet" below.
- **Research artifact architecture** (Phase 10): reproducible on-disk formats (JSON / JSON Lines) for
  flows, graphs, snapshots, experiments, metrics, and hash-verified ground truth —
  `experiments/artifacts/`.
- **Multi-tier network laboratory** (Phase 11): a 10-service controlled Docker lab (client, gateway,
  load balancer, 2x API, redis, database, worker, DNS, external-service simulator) that NETSCOPE-X
  will observe starting Phase 21 — `simulator/docker/`.
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

### What doesn't exist yet

No packet capture, flow reconstruction, topology inference, behavioral modeling, anomaly detection,
digital twin, simulation, or counterfactual engine has been implemented yet — those begin at Phase 21
and continue through the 69-phase plan. The API surface and data contracts are real and tested; the
research intelligence they will eventually serve is not built yet. Nothing in this repository
currently fabricates results — every phase's completion report documents exactly what was and wasn't
verified by actual execution.

## Repository layout

```
backend/app/
  models/     Phase 04 data contracts (Pydantic)
  core/       Phase 07-08 observability + configuration
  api/        Phase 09 API routes (versioned /api/v1)
experiments/
  artifacts/  Phase 10 reproducible artifact I/O
frontend/     Phase 06 placeholder React/Vite/Tailwind scaffold
simulator/
  docker/     Phase 11-15 multi-tier network laboratory
  traffic/    Phase 14-15 traffic + protocol workload generators
docs/
  research/       Phase 01-02 problem definition & research questions
  requirements/   Phase 03 system requirements
  architecture/   Phase 04-05, 09-15 design docs
  development/    Phase 06 environment notes
  PROJECT_STATE.md   authoritative, continuously-updated project state
scripts/      setup and validation scripts
```

## Getting started

```bash
bash scripts/setup.sh          # bootstraps .venv + backend deps + frontend npm deps
pytest backend/tests experiments/tests simulator/tests   # run the full test suite (75 tests)
docker compose up --build      # backend (placeholder API) + frontend dev containers
docker compose -f simulator/docker/docker-compose.yml up -d   # the network lab
```

See `docs/development/environment.md` for what's actually been verified to work, and
`docs/architecture/network_laboratory.md` for the lab's topology and how to exercise it.

## Master specification

The full 69-phase execution plan, non-negotiable engineering rules, and acceptance criteria this
project follows are defined in `NETSCOPE (1).pdf` at the repository root. Every phase's completion is
reported using the spec's required format (STATUS/OBJECTIVE/IMPLEMENTED/.../VERIFICATION/NEXT PHASE)
and is never marked complete without actually running and verifying its deliverables.
