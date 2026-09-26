# NETSCOPE-X — Deployment Guide

Phase 69 documentation deliverable. NETSCOPE-X has two independent Docker Compose stacks — they are
not alternatives, they serve different purposes and can run simultaneously.

## 1. App containers (`docker-compose.yml`, repo root — Phase 06)

```bash
docker compose up --build
# backend:  http://localhost:8000  (real API — see docs/API.md; /health also present)
# frontend: http://localhost:4173  (placeholder scaffold only — see docs/LIMITATIONS.md, FR-1.42)
```

Two services: `backend` (built from `backend/Dockerfile`, the real FastAPI app) and `frontend` (built
from `frontend/Dockerfile`, `vite preview` serving the production build of the placeholder scaffold).
This is the deployable app; it is not the network laboratory it observes.

## 2. The network laboratory (`simulator/docker/docker-compose.yml`, Phase 11-13)

```bash
docker compose -f simulator/docker/docker-compose.yml up -d
python -m scripts.validate_observatory   # Phase 20 gate -- verify the lab before using it
docker compose -f simulator/docker/docker-compose.yml down
```

10 required service roles (client, gateway, 2x load-balancer, 2x api, redis, database, worker, dns,
external-service) segmented across 4 networks (edge/app/data/external) — this is the controlled,
authorized environment NETSCOPE-X's own inference pipeline observes traffic from (spec §5 Safety
Boundary: capture only ever happens here, never against a system the operator doesn't own). See
`docs/architecture/network_laboratory.md` for the full topology rationale.

Once the lab is up, generate traffic and capture it:

```bash
docker compose -f simulator/docker/docker-compose.yml exec client \
    python3 -m simulator.traffic.generate --pattern <name> --seed <n> --out /tmp/traffic.log
docker compose -f simulator/docker/docker-compose.yml exec client \
    python3 -m simulator.capture.live --interface eth0 --duration 10 --out /tmp/live_capture.pcap
```

Then feed the resulting pcap to `POST /capture` (`source=pcap_upload`) against the app containers'
backend.

## Environment variables (backend `Settings`, `backend/app/core/config.py`)

Configuration is entirely env-driven (NFR-4 — no hardcoded paths). Key variables:

| Variable | Purpose |
|---|---|
| `NETSCOPE_ARTIFACT_ROOT` | Root directory for all research artifacts (captures, topology, experiments, metrics) — must match whatever `scripts/run_experiment_matrix.py --root` was pointed at for `GET /experiments`/`/metrics` to read the same data. |
| `NETSCOPE_UPLOAD_STAGING_DIR` | Where `POST /capture` (`source=pcap_upload`) looks for `pcap_filename`. |

See `backend/app/core/config.py::Settings` for the complete list (edge-confidence scales, dependency
thresholds, UDP session timeout, causal-candidate strength threshold, etc.) — every tunable named and
documented there, none hardcoded in the algorithm modules themselves.

## What has and hasn't been verified against a real deployment

`docker compose config` and `docker compose build` for the app stack, and the lab's own
`scripts.validate_observatory` gate, were exercised successfully during Phase 06/20 in a session that
had Docker available. This Phase 69 session does not have Docker access — no deployment step above was
re-verified here. See `docs/LIMITATIONS.md`.

## Replicated deployment (Phase 93)

`docker-compose.ha.yml` runs two backends that mirror each other's artifact volume; see
`docs/architecture/high_availability.md`. Configure any instance with `NETSCOPE_REPLICA_ROOTS` (comma list) and
optionally `NETSCOPE_REPLICA_MIN_WRITES`. The compose file has not been run in this environment (no Docker exercised);
the failover behavior is verified with two real uvicorn processes in `backend/tests/test_ha_failover.py`.
