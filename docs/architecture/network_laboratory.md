# NETSCOPE-X — Multi-Tier Network Laboratory

Phase 11 + Phase 12 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 11 — MULTI-TIER
NETWORK LABORATORY" and §"PHASE 12 — NETWORK NAMESPACE ISOLATION"). Builds the controlled Docker
network with the 10 required services (Client, Gateway, Load Balancer, API-1, API-2, Redis, Database,
Worker, DNS, External-service simulator) and, as of Phase 12, segments them across 4 controlled
network boundaries. Code: `simulator/docker/`. This is the first controlled environment NETSCOPE-X
will eventually observe traffic on (starting Phase 21) — it is separate from, and not a substitute
for, the repo-root `docker-compose.yml` (Phase 06's backend/frontend development containers).

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

As of Phase 12, the 10 services run across 4 controlled network boundaries (edge/app/data/external —
see "Phase 12 — Network Namespace Isolation" below) rather than one flat network; only containers that
legitimately need to cross a tier boundary are multi-homed onto both sides of it.

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

## Phase 12 — Network Namespace Isolation

Spec §"PHASE 12": "Implement controlled network boundaries and verify routing." This **modifies**
`simulator/docker/docker-compose.yml` in place (a documented change to an earlier phase's artifact per
spec §38, not a silent architecture change, and not a parallel/duplicate lab): the single flat
`netscope-x-lab` network from Phase 11 is replaced with four tiered networks, so that only the
containers that should legitimately cross a boundary are multi-homed onto both sides of it.

```
edge:      client, gateway, dns
app:       gateway, load-balancer, api-1, api-2, worker
data:      api-1, api-2, worker, redis, database
external:  api-1, api-2, external-service
```

`gateway` bridges edge↔app. `api-1`/`api-2` bridge app↔data and app↔external. `worker` bridges
app↔data (it participates in the app tier as a lab node but never serves inbound app traffic).
`load-balancer`, `redis`, `database`, `external-service`, `client`, and `dns` are each confined to
their one relevant network.

### Verification actually performed this phase

**Positive (intended paths still work, regression-checked against Phase 11):**
```
$ docker compose exec client curl -s http://gateway/
{"service": "api-1", "redis_reachable": true, "database_reachable": true, "external_reachable": true}
$ docker compose exec client curl -s http://gateway/
{"service": "api-2", "redis_reachable": true, "database_reachable": true, "external_reachable": true}
```
Full chain unchanged after segmentation.

**Negative (boundaries actually enforced, not just declared):**
```
$ docker compose exec client curl -sv --max-time 3 http://api-1:5000/
* Resolving timed out after 3001 milliseconds        (exit 28)
$ docker compose exec client curl -sv --max-time 3 http://redis:6379/
* Resolving timed out after 3001 milliseconds         (exit 28)
$ docker compose exec client curl -sv --max-time 3 http://database:5432/
* Resolving timed out after 3002 milliseconds         (exit 28)
$ docker compose exec gateway curl -sv --max-time 3 http://redis:6379/
* Resolving timed out after 3003 milliseconds
$ docker compose exec gateway curl -sv --max-time 3 http://database:5432/
* Resolving timed out after 3002 milliseconds
$ docker compose exec gateway curl -sv --max-time 3 http://external-service/
* Could not resolve host: external-service
$ docker compose exec load-balancer curl -sv --max-time 3 http://redis:6379/
* Resolving timed out after 3002 milliseconds
$ docker compose exec load-balancer curl -sv --max-time 3 http://database:5432/
* Resolving timed out after 3002 milliseconds
```
Every negative case fails at **DNS resolution**, not merely at the TCP/HTTP layer — because Docker's
embedded per-network DNS only resolves names for containers sharing a network, a container with no
membership in the target's network cannot even resolve its name. This is a stronger, cleaner proof of
isolation than a firewall-rule-based block would be: there is no route to fail over, the name simply
doesn't exist from that container's point of view. (`gateway`'s `external-service` lookup returned an
immediate "Could not resolve host" rather than a timeout — a harmless resolver-behavior variation
between how Alpine's musl resolver treated the two cases, not a different isolation outcome.)

**Routing evidence** — `docker network inspect` membership, matching the intended design exactly:
```
netscope-x-lab-edge:     gateway, client, dns
netscope-x-lab-app:      gateway, load-balancer, api-1, worker, api-2
netscope-x-lab-data:     redis, api-1, worker, api-2, database
netscope-x-lab-external: external-service, api-1, api-2
```
Interface evidence — `client` (should be single-homed) vs `api-1` (should be triple-homed):
```
client eth0: 172.22.0.2/16                    (1 interface -- edge only)
api-1  eth0: 172.18.0.4/16                    (app)
api-1  eth1: 172.20.0.3/16                    (data)
api-1  eth2: 172.21.0.2/16                    (external)
```
Teardown (`docker compose ... down`) performed after verification, same discipline as Phase 11.

## Explicitly deferred (later phases)

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
`dnsmasq.conf`), satisfies Phase 11 (all 10 required services built, started, and exercised
end-to-end) and Phase 12 (the lab is now segmented into 4 controlled network boundaries, with both the
intended paths and the enforced boundaries verified by actually running positive and negative
connectivity checks, plus `docker network inspect`/`ip addr` routing evidence) — all captured above,
not asserted.
