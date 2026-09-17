# NETSCOPE-X — Development Environment

Phase 06 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 06 — REPRODUCIBLE DEVELOPMENT
ENVIRONMENT"). This is a working note, not the final `DEVELOPMENT.md` — that is assembled at Phase 69
from the accumulated per-phase environment notes like this one (spec §31: document as you go).

## What exists

- **Backend**: `requirements.txt` (runtime: FastAPI, Uvicorn, Pydantic, NetworkX, NumPy, Pandas,
  SciPy — the spec §6 preferred baseline) and `requirements-dev.txt` (adds pytest, httpx). A minimal
  placeholder FastAPI app at `backend/app/main.py` (`/health` only) exists solely to give the Docker
  image something real to run — it is not the Phase 09 API.
- **Frontend**: `frontend/` — React 18 + TypeScript + Vite + Tailwind CSS scaffold, with Cytoscape.js
  pinned for later graph visualization (Phase 12+). `frontend/src/App.tsx` is an explicitly labeled
  placeholder page, not the real UI.
- **Docker**: `backend/Dockerfile`, `frontend/Dockerfile`, `docker-compose.yml` — dev-only containers
  for the backend placeholder API and the built frontend preview server. This is **not** the
  multi-tier network laboratory (that's Phase 11's `simulator/docker/`).
- **Scripts**: `scripts/setup.sh` — bootstraps a fresh clone (venv + backend deps + frontend npm
  deps) in one command.

## How to bootstrap

```bash
bash scripts/setup.sh
```

This creates `.venv`, installs pinned backend dependencies, runs `scripts/validate_data_contracts.py`
and the `backend/tests` pytest suite, and runs `npm install` in `frontend/`.

To build and run the dev containers:

```bash
docker compose up --build
# backend:  http://localhost:8000/health
# frontend: http://localhost:4173/
```

## What was actually verified this phase (not merely written)

- `.venv` recreated from scratch; `pip install -r requirements-dev.txt` succeeded (33 packages).
- `scripts/validate_data_contracts.py` re-run after the fresh install: 38/38 checks still pass.
- `pytest backend/tests` (new `test_environment_smoke.py`): 3/3 passed — confirms fastapi, uvicorn,
  pydantic, networkx, numpy, pandas, scipy all import, `backend.app.models` imports, and a basic
  NetworkX shortest-path call works.
- `frontend/`: `npm install` succeeded (138 packages); `npm run build` (type-check + Tailwind + Vite
  production bundle) succeeded.
- `docker compose config` validated the compose file.
- `docker compose build` succeeded for both `backend` and `frontend` images (Docker Desktop had to be
  started first — it was not running at the start of this phase).
- `docker compose up -d` started both containers; `curl http://localhost:8000/health` returned
  `{"status":"ok"}`; `curl http://localhost:4173/` returned HTTP 200. Containers were then stopped
  (`docker compose down`).
- `scripts/setup.sh` was run standalone against a clean state (`.venv` and `frontend/node_modules`
  deleted first) and completed successfully end-to-end.

## Known limitations

- `npm audit` reports one moderate, dev-server-only advisory in `esbuild` (via `vite@5.4.x`) —
  `GHSA-67mh-4wv8-2f99`, "esbuild enables any website to send any requests to the development server
  and read the response." A fix requires upgrading to `vite@8`, a breaking major-version change not
  undertaken in this phase. This only affects the local Vite dev server (not the production build or
  the `vite preview` server used in the Docker image), and is an accepted, documented risk for now,
  not silently ignored. The previously-flagged high-severity PostCSS advisories were resolved by
  pinning `postcss@8.5.28`.
- The backend/frontend Docker images run placeholder applications; they prove the environment is
  reproducible, not that the product works — that is what later phases (09+, 12+) build toward.
- `scripts/setup.sh` is POSIX-shell (works under Git Bash on Windows, as used here); a PowerShell
  equivalent has not been written and is not required by this phase's acceptance criteria, but could
  be added later if native PowerShell usage becomes a real need.

## Status

This document, together with the pinned dependency files, `frontend/`, the two Dockerfiles,
`docker-compose.yml`, and `scripts/setup.sh`, satisfies Phase 06. Every claim above was produced by an
actual command run in this session (see the Phase 06 completion report for the full command list),
not asserted without execution.
