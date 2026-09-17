# NETSCOPE-X — Project State

This file is the single source of truth for project progress across the 69-phase execution plan
defined in the master spec (`NETSCOPE (1).pdf`). Update it after every phase.

## Current phase

Phase 06 (Reproducible Development Environment) complete. Phase 07 (Observability Framework) not
started.

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
- `pytest backend/tests` — 3/3 passed (`test_environment_smoke.py`: pinned deps import, data-contracts
  package imports, basic NetworkX operation works).
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

Next: Phase 07 — Observability Framework (structured logs, request IDs, experiment IDs, module-level
logging, error reporting, performance timing). Not started; awaiting explicit request.
