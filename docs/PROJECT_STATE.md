# NETSCOPE-X — Project State

This file is the single source of truth for project progress across the 69-phase execution plan
defined in the master spec (`NETSCOPE (1).pdf`). Update it after every phase.

## Current phase

Phase 11 (Multi-Tier Network Laboratory) complete. Phase 12 (Network Namespace Isolation) not started.

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

## Current datasets

None yet — datasets are introduced starting Phase 14/16/19.

## Current metrics

None yet — no experiments have been run.

## Pending work

Next: Phase 12 — Network Namespace Isolation (implement controlled network boundaries and verify
routing). Not started; awaiting explicit request.
