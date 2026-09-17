# NETSCOPE-X — Ground-Truth Generator

Phase 16 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 16 — GROUND-TRUTH GENERATOR"):
"Automatically generate authoritative: nodes, edges, roles, services, routes, expected paths." Code:
`simulator/ground_truth/`. Verified by `simulator/tests/test_ground_truth.py` (9 pure unit tests) and
a real run against the live Phase 11-15 lab.

## Why this lives in `simulator/`, not `backend/`

Spec §4 (the ground-truth rule, restated in `docs/research/problem_definition.md` §2/§6) is explicit:
ground truth may be used only for generating experiments, validating results, and computing metrics —
**it must never leak into the inference pipeline**. NETSCOPE-X's future inference code (NETTRACE,
FLOWMIND, topology reconstruction, ...) lives under `backend/` and will start in Phase 21. Placing
ground-truth generation in `simulator/ground_truth/` instead keeps it physically and importably
separate: there is no plausible accidental `import` path from a future `backend/nettrace/topology.py`
into `simulator/ground_truth/topology.py`, because nothing in `backend/` has a reason to import from
`simulator/`.

## Two real sources, nothing invented

1. **Declared architecture** (`simulator/ground_truth/topology.py`) — a hardcoded, reviewable mapping
   of each of the lab's 11 services to a `ServiceRole` (Phase 04 enum) and a list of `DeclaredEdge`s
   (source, target, protocols) reflecting the actual intended dependency structure built in Phases
   11-15. `external-service` correctly maps to `ServiceRole.UNKNOWN` — it stands in for a third-party
   dependency, not one of the defined internal roles, which is the *correct* ground-truth label for it,
   not a gap. Edge protocols are the real protocols Phase 15 actually verified against each hop (HTTP,
   DNS, REDIS, POSTGRES, TLS, TCP), not guessed.
2. **The actual running lab** (`simulator/ground_truth/cli.py`'s `docker_ip_lookup`) — real container
   IPs fetched via `docker ps --filter label=com.docker.compose.service=<name>` (not a guessed
   container-naming convention) + `docker inspect`, so the generated ground truth reflects one
   concrete, live instantiation of the lab — the same instantiation a future real packet capture
   (Phase 21+) of this exact lab run would need to be compared against.

`generate.py`'s `check_services_match_compose` cross-checks the declared role map against
`docker-compose.yml`'s actual service list (parsed with PyYAML, now an explicit direct dependency
rather than relying on it being merely a transitive one) and raises loudly on any drift — a service
added or removed from the lab without updating the ground-truth declaration is a hard error, not a
silent staleness.

## What's generated

Reusing Phase 04's schemas directly (no new domain types invented) and Phase 10's hashed I/O layer
(no new storage format invented):

- **Nodes + edges** → a `TopologyGraph` (11 nodes, 16 edges this run). Every edge has
  `confidence=1.0` and `evidence=["ground truth: declared lab architecture..."]` — ground truth is
  certain by construction, never inferred, so it uses the top of the confidence scale deliberately,
  not because an inference process happened to score it there.
- **Roles + services** → a `GroundTruthRoles` (`simulator/ground_truth/models.py`, a thin
  package-local wrapper around Phase 04's `RoleClassification`) — one entry per node, each with
  `role_probabilities={true_role: 1.0}`. "Services" in the spec's wording is treated as synonymous
  with node identity + role here (there is no separate "service" concept beyond a node's declared
  role in this lab).
- **Routes / expected paths** → a `GroundTruthPaths` (`"source->target"` → ordered node-id list),
  computed with **NetworkX's Dijkstra/shortest-path** — the Phase 05-selected path-analysis algorithm,
  used here for the first time — over the ground-truth graph, for three representative pairs
  (client→redis, client→database, client→external-service).

All three are persisted via Phase 10's `write_ground_truth`/`read_ground_truth` (JSON + SHA-256
sidecar, integrity-verified on every read) under `experiments_data/ground_truth/<capture_id>/`.

## Verification actually performed this phase

- `pytest simulator/tests/test_ground_truth.py` — 9/9 passed (pure, fake `ip_lookup`, no Docker):
  every declared service gets exactly one node; all 16 declared edges construct successfully (Phase
  04's `TopologyGraph` validator itself refuses dangling edges, so successful construction is part of
  the proof); every edge has confidence 1.0 and non-empty evidence; every node's role classification
  is certain (`probabilities[true_role] == 1.0`, `best_role == true_role`); the computed
  client→redis and client→external-service paths match the hand-verified expected route shape
  (client → gateway → a load balancer → an api node → target); the compose cross-check accepts the
  real declared set and rejects both an added and a removed service.
- **Real integration run** against the live 11-container lab:
  ```
  $ python -m simulator.ground_truth.cli --capture-id lab-run-1 --root experiments_data
  Ground truth written to experiments_data\ground_truth\lab-run-1
    nodes: 11  edges: 16
    topology.json sha256: 529d641b...
    roles.json    sha256: c1eda118...
    paths.json    sha256: 8c9f6734...
    expected path client->redis: client -> gateway -> load-balancer -> api-1 -> redis
    expected path client->database: client -> gateway -> load-balancer -> api-1 -> database
    expected path client->external-service: client -> gateway -> load-balancer -> api-1 -> external-service
  ```
  Inspecting the written file confirmed real, distinct per-container IPs matching Phase 12's network
  segmentation (e.g. `redis`/`database` on the `172.22.0.0/16` data subnet, `external-service` alone
  on `172.18.0.0/16`). All three files were read back through `read_ground_truth` and verified their
  hash successfully. A deliberate tamper test (editing the on-disk `topology.json` after generation)
  correctly raised `GroundTruthIntegrityError` naming the expected vs. actual hash, then the file was
  restored.
- Full combined suite (`backend/tests experiments/tests simulator/tests`) — 84/84 passed, no
  regression.
- Lab torn down (`docker compose ... down`) after verification. `experiments_data/` (generated,
  reproducible from code) added to `.gitignore`.

## Explicitly deferred (Phase 17)

Phase 17 ("Ground-Truth Integrity") is a separate spec phase focused on the *tooling and process*
around ground-truth integrity — versioning multiple generations, and structural safeguards that make
it hard for future inference code to accidentally import or read ground truth. This phase already gets
per-generation content-hashing "for free" by reusing Phase 10's `write_ground_truth`; building
additional integrity tooling now, before Phase 17 defines what's actually needed, would be
speculative. Not built here, deliberately.

## Status

This document, together with `simulator/ground_truth/{topology,models,generate,cli}.py` and
`simulator/tests/test_ground_truth.py`, satisfies Phase 16: authoritative nodes, edges, roles,
services, and expected paths are generated automatically from the lab's declared architecture plus its
real running state, verified by both pure unit tests and a real run against the live lab with hash
integrity confirmed.
