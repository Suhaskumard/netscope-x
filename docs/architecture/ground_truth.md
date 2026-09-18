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

## Phase 17 — Ground-Truth Integrity

Phase 16 already got per-generation content-hashing "for free" by reusing Phase 10's
`write_ground_truth`/`read_ground_truth`, but left two gaps open: re-running the generator for the
same `capture_id` silently overwrote the previous generation, and nothing would stop a future
inference module from importing `simulator.ground_truth` directly. Phase 17 closes both.

### Versioned generations

`experiments/artifacts/ground_truth_manifest.py` adds `GroundTruthManifest`/
`GroundTruthManifestEntry` (version number, timestamp, per-file sha256 map).
`experiments/artifacts/io.py` adds `write_ground_truth_generation`/`read_ground_truth_generation`,
built on top of the existing `write_ground_truth`/`read_ground_truth` primitives rather than a new
storage format: each generation is written to its own `ground_truth/<capture_id>/v<N>/` directory
(never overwriting `v<N-1>/`), and a hash-protected `manifest.json` records every generation. Reading
a generation cross-checks the manifest's recorded hash against the artifact's own sidecar hash — an
extra layer that catches a manifest edited out of sync with its artifact, not just a single tampered
file. `simulator/ground_truth/cli.py` now calls `write_ground_truth_generation` once instead of
`write_ground_truth` three times, and prints the resulting version number.

### Structural safeguard against inference-pipeline contamination

`scripts/check_ground_truth_boundary.py` statically walks every `.py` file in the repository (via
`ast`) and flags any import of `simulator.ground_truth` whose importing file is outside the
spec-sanctioned allowlist (`simulator/`, `experiments/`, `scripts/`, any `tests/` directory —
"generating experiments, validating results, calculating metrics, checking reconstruction accuracy",
spec §4). Inference code (`nettrace/`, `flowmind/`, ...) doesn't exist yet — it starts spec Phase
21+ — so the check currently passes trivially; its purpose is to fail immediately the day such an
import is ever added, rather than relying on the current absence of `backend/`→`simulator/` imports
being a coincidence forever.

### Verification actually performed this phase

- `pytest simulator/tests/test_ground_truth_integrity.py` — 11/11 passed: version 1/2 written for the
  same capture_id without either overwriting the other; manifest lists both generations with correct
  hashes; `version="latest"` resolves to the newest generation, `version=1` still reads the original;
  per-file tamper detection still fires inside a generation; a manifest/artifact hash mismatch
  (artifact re-signed to a tampered value, manifest left pointing at the original hash) is detected;
  reading an unrecorded version raises; the boundary checker finds zero violations scanning the real
  repository; a synthetic temp repo with one disallowed import (`nettrace/topology.py` importing
  `simulator.ground_truth`) is correctly flagged, and simulator/experiments/test-directory imports of
  the same module are correctly allowed.
- Full combined suite (`backend/tests experiments/tests simulator/tests`) — 95/95 passed, no
  regression.
- `python scripts/check_ground_truth_boundary.py` run standalone — clean exit, zero violations.
- **Real integration run** against the live 11-container lab: ran
  `python -m simulator.ground_truth.cli --capture-id phase17-run --root experiments_data` twice.
  First run wrote `v1/` (sha256 `64360442...` for `topology.json`); second run wrote `v2/`
  (sha256 `1ad84937...`) alongside it, `v1/` byte-for-byte unchanged, both listed in
  `manifest.json`. Read both generations back through `read_ground_truth_generation` and confirmed
  `version="latest"` resolved to v2 while `version=1` still returned v1's content. Deliberately
  tampered `v1/topology.json` on disk and confirmed `read_ground_truth_generation` raised
  `GroundTruthIntegrityError` naming the expected vs. actual hash — the same tamper-detection
  guarantee Phase 16 confirmed, now re-verified against the versioned layout. Lab torn down
  (`docker compose ... down`) after verification.

## Status

This document, together with `simulator/ground_truth/{topology,models,generate,cli}.py`,
`experiments/artifacts/{ground_truth_manifest,io,paths}.py`, `scripts/check_ground_truth_boundary.py`,
`simulator/tests/test_ground_truth.py`, and `simulator/tests/test_ground_truth_integrity.py`,
satisfies Phases 16 and 17: authoritative nodes, edges, roles, services, and expected paths are
generated automatically from the lab's declared architecture plus its real running state; every
generation is independently versioned, hashed, and tamper-verified; and a real, currently-passing
structural check guards against ground truth ever leaking into the (not-yet-built) inference
pipeline.
