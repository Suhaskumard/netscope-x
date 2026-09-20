# NETSCOPE-X — Development Guide

Phase 69 documentation deliverable, assembled from the accumulated per-phase environment notes as
`docs/development/environment.md` (Phase 06) itself anticipated ("this is a working note, not the
final `DEVELOPMENT.md` — that is assembled at Phase 69").

## Prerequisites

- Python 3.12
- Node 22
- Docker (optional — needed only for the containerized backend/frontend and the network lab; not
  available in the environment this phase was written in, see `docs/LIMITATIONS.md`)

## Bootstrap

```bash
bash scripts/setup.sh
```

Creates `.venv`, installs `requirements-dev.txt`, runs `scripts/validate_data_contracts.py` and the
`backend/tests` suite as a smoke check, and runs `npm install` in `frontend/`. Safe to re-run on an
existing clone.

## Repository layout

```
backend/app/          FastAPI app, API routes, Pydantic models, cross-cutting config/logging
backend/nettrace/      Capture, normalization, flow reconstruction, topology inference
backend/flowmind/      Behavioral features, fingerprints, role classification, baseline, drift, anomaly
backend/archaeology/   Temporal snapshots, diffs, behavior evolution, event timeline, attribution
backend/dependency/    Communication/dependency/causal analysis, criticality, experiment recommendations
backend/digital_twin/  Twin construction + synchronization
backend/simulation/    Failure injection, path engine, propagation pipeline, resilience, counterfactuals
backend/tests/         Backend unit/integration tests (pytest)
experiments/           Research artifact I/O, synthetic traffic, evaluation metrics, matrix runner
experiments/tests/     Experiments-layer tests
simulator/             Docker network lab, traffic/protocol generators, ground truth, scenarios
simulator/tests/       Simulator-layer tests
frontend/              React/TypeScript/Vite scaffold (placeholder only — see docs/LIMITATIONS.md)
scripts/               setup.sh, validate_data_contracts.py, check_ground_truth_boundary.py, run_experiment_matrix.py
docs/                  This documentation set + docs/architecture/*.md per-module design docs
```

## Running things locally

```bash
# Backend API (real /capture, /flows, /topology, /dependencies, /causal, /history, /experiments, /metrics;
# 5 routes still 501 -- see docs/API.md)
uvicorn backend.app.main:app --reload

# Full test suite
pytest backend/tests experiments/tests simulator/tests

# Data-contract and ground-truth-boundary gates (run these after any model/import change)
python -m scripts.validate_data_contracts
python -m scripts.check_ground_truth_boundary

# The experimental matrix (Phase 68)
python -m scripts.run_experiment_matrix
```

## Docker (network lab + containerized services)

```bash
docker compose up --build                                     # backend + frontend dev containers
docker compose -f simulator/docker/docker-compose.yml up -d   # 10-service network lab
python -m scripts.validate_observatory                        # verify the lab before using it
```

See `docs/DEPLOYMENT.md` for details and `docs/LIMITATIONS.md` for what has (and hasn't) been
verified against a real Docker daemon.

## Code conventions (enforced by review across all 69 phases, not tooling)

- Every backend model is a Pydantic `BaseModel` (NFR-2); every module has a real, non-mocked pytest
  suite alongside it.
- No hardcoded paths or unnamed magic numbers (NFR-4) — configuration lives in
  `backend/app/core/config.py::Settings`, sourced from environment variables.
- No circular imports, no giant files, no global state (NFR-7) — checked structurally by
  `scripts/check_ground_truth_boundary.py` for the ground-truth import boundary specifically; no
  general-purpose linter is configured in this repository (`pyflakes` was used ad hoc during Phase 69
  cleanup, see `docs/TESTING.md`).
- Every module and architectural decision gets a `docs/architecture/<topic>.md` write-up explaining
  the algorithm and its documented limitations — read one before modifying its module.

## Where to look next

- `docs/ARCHITECTURE.md` — system-level pipeline overview
- `docs/API.md` — full endpoint reference
- `docs/TESTING.md` — how to run and interpret the test suites
- `docs/EXPERIMENTS.md` — running the research validation matrix
- `docs/DEPLOYMENT.md` — Docker Compose usage
- `docs/LIMITATIONS.md` — what is and isn't verified, and why
- `docs/PROJECT_STATE.md` — the phase-by-phase build log (the authoritative history)
