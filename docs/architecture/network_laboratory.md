# NETSCOPE-X — Multi-Tier Network Laboratory

Phase 11 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 11 — MULTI-TIER NETWORK
LABORATORY"). Builds the controlled Docker network with the 10 required services: Client, Gateway,
Load Balancer, API-1, API-2, Redis, Database, Worker, DNS, External-service simulator. Code:
`simulator/docker/`. This is the first controlled environment NETSCOPE-X will eventually observe
traffic on (starting Phase 21) — it is separate from, and not a substitute for, the repo-root
`docker-compose.yml` (Phase 06's backend/frontend development containers).

## Topology as built

```
client
  |
  v
gateway (nginx, :80)
  |
  v
load-balancer (nginx, :80, round-robins)
  |
  +---------+---------+
  v                   v
api-1 (:5000)      api-2 (:5000)
  |         \          |         \
  v          v         v          v
redis     database  external-service
(:6379)   (:5432)     (nginx, :80)

worker  -----> redis, database (background, no inbound traffic)
dns     -----> answers DNS queries on the lab network (standalone)
```

All 10 services run on a single Docker network (`netscope-x-lab`). Network-namespace-level
segmentation (multiple isolated subnets, simulated routing boundaries) is explicitly Phase 12's job
and is not duplicated here.

## Service roles

| Service | Image | Role |
|---|---|---|
| `client` | `alpine:3.20` + curl/bind-tools | Originates requests for verification; real traffic generation is Phase 14+. |
| `gateway` | `nginx:1.27-alpine` | Reverse-proxies to `load-balancer`. |
| `load-balancer` | `nginx:1.27-alpine` | Round-robins between `api-1`/`api-2` (nginx `upstream` block). |
| `api-1`, `api-2` | `python:3.12-alpine` running `simulator/docker/api/api.py` | On `GET /`, performs real TCP/HTTP reachability checks against redis/database/external-service and reports them as JSON — makes the dependency structure genuinely observable. |
| `redis` | `redis:7-alpine` | Cache tier. |
| `database` | `postgres:16-alpine` | Persistence tier. |
| `worker` | `python:3.12-alpine` running `simulator/docker/worker/worker.py` | Background participant with real dependency edges to redis/database; no inbound traffic — exercises the "not every node is a request target" case. |
| `dns` | `alpine:3.20` + `dnsmasq` | Answers DNS queries on the lab network (`simulator/docker/dns/dnsmasq.conf`). |
| `external-service` | `nginx:1.27-alpine` | Stands in for a third-party dependency `api-1`/`api-2` call out to. |

## Verification actually performed this phase

Per spec Rule 2 (never fabricate execution), every claim below was produced by an actual command run
in this session, not asserted.

1. `docker compose -f simulator/docker/docker-compose.yml config` — validated the compose file.
2. `docker compose ... up -d` — all 10 containers reached `Up` (redis and database additionally reached
   `healthy` per their healthchecks before dependent services started, per `depends_on: condition:
   service_healthy`).
3. **End-to-end request chain**, run twice from the `client` container:
   ```
   $ docker compose exec client curl -s http://gateway/
   {"service": "api-1", "redis_reachable": true, "database_reachable": true, "external_reachable": true}
   $ docker compose exec client curl -s http://gateway/
   {"service": "api-2", "redis_reachable": true, "database_reachable": true, "external_reachable": true}
   ```
   This proves, in one exercised request, that: client reached gateway, gateway reached load-balancer,
   load-balancer reached an api instance (and genuinely alternated between `api-1` and `api-2` across
   the two requests — real round-robin, not asserted), and that api instance reached redis, database,
   and external-service, all for real.
4. **DNS resolution**, from the `client` container against the `dns` container:
   ```
   $ docker compose exec client nslookup -type=A example.lab dns
   Server:    dns
   Address:   172.18.0.3#53
   Name:      example.lab
   Address:   10.10.10.10
   ```
   (exit code 0). Note: an unqualified `nslookup example.lab dns` — which BusyBox also issues an AAAA
   query for — printed a `** server can't find example.lab: REFUSED` line after the correct A-record
   answer, because `dnsmasq` is configured `no-resolv` (no upstream forwarding, by design, to keep this
   test independent of outbound internet access) and has no AAAA record to answer authoritatively for
   that name. This is expected, explained dnsmasq behavior, not a defect — the explicit `-type=A` query
   above shows the clean, unambiguous success case.
5. **Worker heartbeat**, from `docker compose logs worker`:
   ```
   worker heartbeat: redis_reachable=True database_reachable=True
   ```
   (repeated every ~5s, confirmed across 5 consecutive log lines).
6. `docker compose ... down` — full teardown, all containers and the `netscope-x-lab` network removed;
   nothing left running.

## Explicitly deferred (later phases)

- Network namespace isolation and verified routing boundaries — Phase 12.
- Multiple routes / controlled routing changes — Phase 13.
- Traffic generation (normal/burst/periodic/concurrent/idle/degraded) — Phase 14.
- Protocol-specific workload generation (TCP/UDP/DNS/HTTP/TLS/DB/cache traffic) — Phase 15.
- Ground-truth generation (authoritative nodes/edges/roles from this exact topology) — Phase 16.
- Ground-truth integrity (versioning/hashing) — already has its I/O mechanism from Phase 10
  (`experiments/artifacts/io.py`'s `write_ground_truth`/`read_ground_truth`); applying it to this
  lab's actual topology happens in Phase 16-17.
- Additional topology archetypes (star, redundant, multi-path, dynamic) — Phase 18.
- Actual packet capture of this lab's traffic — Phase 21 (this is the first phase where NETSCOPE-X's
  own inference pipeline will observe this exact lab and its output will be compared against this
  document as ground truth).

## Status

This document, together with `simulator/docker/` (compose file, nginx configs, `api.py`, `worker.py`,
`dnsmasq.conf`), satisfies Phase 11: all 10 required services are built, actually started, and
actually exercised end-to-end, with real output captured above.
