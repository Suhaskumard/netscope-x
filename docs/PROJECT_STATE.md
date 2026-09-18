# NETSCOPE-X — Project State

This file is the single source of truth for project progress across the 69-phase execution plan
defined in the master spec (`NETSCOPE (1).pdf`). Update it after every phase.

## Current phase

Phase 17 (Ground-Truth Integrity) complete. Phase 18 (Scenario Generator) not started.

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
- `pytest simulator/tests` — 47/47 passed: 19 traffic-pattern tests (Phase 14) + 8 protocol
  wire-format tests (Phase 15) + 9 ground-truth tests (Phase 16) + 11 ground-truth integrity tests
  (Phase 17: versioning round-trips, manifest/artifact hash cross-check, boundary-checker real-repo
  scan + synthetic-violation detection), all pure/no-Docker. Plus real Docker-based runs: 3 traffic
  patterns (Phase 14), all 6 protocols (Phase 15), a full ground-truth generation (Phase 16, with
  hash-verified read-back and tamper-detection re-confirmed), and two successive ground-truth
  generations for one capture_id (Phase 17, v1 confirmed unchanged after v2 was written, tamper
  detection re-confirmed on the versioned layout) — not part of the pytest suite, manual integration
  verification like Phases 11-13.
- `python scripts/check_ground_truth_boundary.py` (Phase 17) — run standalone, zero violations found
  in the real repository.
- `pytest backend/tests experiments/tests simulator/tests` (combined) — 95/95 passed, no regression.
- Multi-tier lab (`simulator/docker/`): verified through Phase 13 (11 containers, 4 segmented
  networks, load-balancer failover) and exercised again in Phase 14 with real generated traffic; torn
  down after each verification run — nothing left running between sessions.

## Current datasets

None yet — datasets are introduced starting Phase 14/16/19.

## Current metrics

None yet — no experiments have been run.

## Pending work

Next: Phase 18 — Scenario Generator (generate multiple controlled network architectures: simple
chain, star, multi-tier, redundant, multi-path, dynamic service network). Not started; awaiting
explicit request.
