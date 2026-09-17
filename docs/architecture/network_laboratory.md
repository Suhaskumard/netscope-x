# NETSCOPE-X — Multi-Tier Network Laboratory

Phase 11 + Phase 12 + Phase 13 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 11 —
MULTI-TIER NETWORK LABORATORY", §"PHASE 12 — NETWORK NAMESPACE ISOLATION", §"PHASE 13 — ROUTING
LABORATORY"). Builds the controlled Docker network with the 10 required services (Client, Gateway,
Load Balancer, API-1, API-2, Redis, Database, Worker, DNS, External-service simulator), segments them
across 4 controlled network boundaries (Phase 12), and (Phase 13) adds a second load balancer so the
gateway→app-tier hop has two real, independently-controllable routes with observed failover. Code:
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

## Phase 13 — Routing Laboratory

Spec §"PHASE 13": "Create multiple routes and controlled routing changes. Verify actual packet paths."

**Scope decision.** The lab runs on Docker Desktop's bridge networking; Docker owns each container's
kernel routing table, and there is no meaningful way to hand-install custom multi-path kernel routes
between containers without fighting Docker's own network driver. The interpretation implemented and
verified here is **service-level route redundancy with real, observed failover** — the same mechanism
already proven for load-balancer→api in Phase 11, extended one hop earlier (gateway→app tier) — stated
explicitly rather than silently substituted for kernel-level multi-routing.

**Change** (again modifies `simulator/docker/docker-compose.yml` and `gateway/nginx.conf` in place,
spec §38-compliant): added a second load balancer, `load-balancer-2` (identical config, same `app`
network). `gateway/nginx.conf`'s single `proxy_pass http://load-balancer:80` became an `upstream
load_balancers { server load-balancer:80; server load-balancer-2:80; }` pool with
`proxy_next_upstream error timeout`, a short `proxy_connect_timeout 2s`/`proxy_read_timeout 5s` (so a
dead peer is detected and failed over quickly rather than hanging), and
`add_header X-Gateway-Upstream $upstream_addr always;` so the actual chosen route is visible in every
response.

**Verification actually performed:**

1. **Multiple real routes** — 6 requests, both load balancers up, `X-Gateway-Upstream` genuinely
   alternates: `172.18.0.6, 172.18.0.5, 172.18.0.6, 172.18.0.5, 172.18.0.6, 172.18.0.5`.
2. **Controlled routing change, zero downtime** — `docker compose stop load-balancer-2` (gateway left
   running, not restarted, so this is a live topology change, not a fresh config load), then 6 more
   requests: all 6 returned `200 OK`. One response's header explicitly showed the failover trail,
   `X-Gateway-Upstream: 172.18.0.5:80, 172.18.0.6:80` (nginx tried the dead peer, failed fast, retried
   the survivor within the same request); the remaining 5 landed directly on `172.18.0.6` (nginx's
   passive health check skipping the known-bad peer for subsequent requests). **No request failed.**
   An earlier attempt that restarted `gateway` while `load-balancer-2` was stopped hit a real, worth
   documenting failure mode: `nginx: [emerg] host not found in upstream "load-balancer-2:80"` — Docker
   removes a stopped container's DNS entry entirely, and nginx's default `upstream` directive resolves
   hostnames once at config-load time, so restarting nginx while a peer is down is fatal. This is why
   the actual test (and any real deployment using this pattern) must keep the proxy running continuously
   through the failure, not restart it — documented here as a genuine finding, not smoothed over.
3. **Recovery** — `docker compose start load-balancer-2`, waited past nginx's default `fail_timeout`
   (10s), 6 more requests: alternation resumed (`172.18.0.6, 172.18.0.6, 172.18.0.5, 172.18.0.6,
   172.18.0.5, 172.18.0.6`).
4. **Routing table evidence** — real kernel routes via `ip route`:
   ```
   gateway: default via 172.18.0.1 dev eth1
            172.18.0.0/16 dev eth1  (app)
            172.20.0.0/16 dev eth0  (edge)
   api-1:   default via 172.18.0.1 dev eth0
            172.18.0.0/16 dev eth0  (app)
            172.21.0.0/16 dev eth2
            172.22.0.0/16 dev eth1
   ```
   (api-1's other two interfaces are its `data` and `external` memberships; Docker assigns subnet
   ranges at network-creation time, so which of 172.21/172.22 is which is not fixed across lab
   restarts — the interface *count* (3, matching app+data+external) is the invariant worth noting,
   consistent with the Phase 12 finding, not the specific subnet-to-name mapping.)
5. Teardown (`docker compose ... down`) performed after verification.

## Explicitly deferred (later phases)

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
end-to-end), Phase 12 (the lab segmented into 4 controlled network boundaries, both intended paths and
enforced boundaries verified via positive and negative connectivity checks plus routing evidence), and
Phase 13 (a second load balancer gives the gateway→app-tier hop two real routes; a live,
zero-downtime failover was actually triggered and observed, then recovery confirmed) — all captured
above, not asserted.
