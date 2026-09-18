# NETSCOPE-X — Scenario Generator

Phase 18 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 18 — SCENARIO GENERATOR"):
"Generate multiple controlled network architectures. Examples: simple chain, star, multi-tier,
redundant, multi-path, dynamic service network." Code: `simulator/scenarios/`. Verified by
`simulator/tests/test_scenarios.py` (15 pure unit tests) and a real deployment of one generated
scenario against Docker.

## Why this exists

Everything built in Phases 11-17 targets exactly **one** fixed 11-service lab
(`simulator/docker/docker-compose.yml`), with its architecture hand-declared once in
`simulator/ground_truth/topology.py`. But `docs/research/research_questions.md` already treats
"topology complexity (small / medium / large / multi-path / multi-service / dynamic)" as an
independent variable, and `docs/requirements/system_requirements.md`'s **FR-1.40** requires a full
experimental matrix across topology complexity — both presuppose more than one network shape
exists to test against. Phase 18 makes topology shape a *generated, parameterized* input instead
of a single hardcoded lab, for Phase 19 (Traffic Replay), Phase 20 (Observatory Validation),
Phase 21+ (capture against varied topologies), and ultimately Phase 68's complexity sweep to use.

## Two-piece output, same shape ground truth already uses

`simulator/scenarios/topologies.py` has one pure, parameterized generator per required archetype,
each returning `(roles: Dict[str, ServiceRole], edges: List[ScenarioEdge])` — the same two-piece
shape `simulator/ground_truth/topology.py` hand-declares once, generalized into something callable
with different parameters instead of read as module-level constants:

- `simple_chain(n)` — a straight line, `client -> api -> ... -> database`.
- `star(n)` — one hub, `n` leaves, each leaf touching only the hub.
- `multi_tier(tier_sizes)` — every node in tier *i* connects to every node in tier *i+1*
  (generalizes the real lab's client→gateway→LB→API→data layering).
- `redundant(n)` — a chain plus one skip-connection, reintroducing a cycle so no single edge
  around it is a bridge (generalizes Phase 13's dual-load-balancer routing lab).
- `multi_path(k)` — a source and sink joined by `k` vertex-disjoint intermediate paths.
- `dynamic_service_network(seed, n)` — a seeded, reproducible random graph (random spanning
  structure + extra random edges) standing in for a network whose shape isn't hand-authored.

Each archetype's *actual claimed structural property* is checked with real NetworkX computation in
`simulator/tests/test_scenarios.py`, not just asserted because the generator ran without error:
star's hub degree, multi_path's `nx.node_connectivity`, redundant's `nx.bridges`, multi_tier's
per-edge tier-boundary crossing, simple_chain's `nx.is_simple_path`, and
dynamic_service_network's determinism across two calls with the same seed (spec NFR-3).

## Declaration vs. topology graph — an honesty distinction

A generated scenario is persisted as a `ScenarioDeclaration` (`simulator/scenarios/models.py`) —
roles + edges, JSON via Pydantic — **not** as a `backend.app.models.TopologyGraph`. `TopologyGraph`'s
`Node.ip_addresses` field is documented as "observed addresses"; a scenario that hasn't been
deployed has no real observed IP to put there, and inventing one would be exactly the kind of "fake
data disguised as real output" spec Rule 3 forbids. `simulator/scenarios/generate.py`'s
`build_topology_graph` — which *does* produce a real `TopologyGraph` — is therefore only called once
a scenario is actually running and a real `ip_lookup` (reusing
`simulator.ground_truth.cli.docker_ip_lookup` unchanged — it looks up any running compose service by
its compose label, nothing lab-specific) can resolve real container IPs.

## Real, deployable infrastructure, not just a declared graph

`simulator/scenarios/generic_node/app.py` is one new reusable building block: a minimal Python
stdlib HTTP server that reads its role (`NODE_ROLE`) and upstream dependency hostnames
(`UPSTREAM_HOSTS`, comma-separated) from environment variables and serves a live JSON reachability
report — the same kind of check `simulator/docker/api.py` hand-writes for its two fixed
dependencies, but data-driven instead of hardcoded, so the *same* image can play every node in every
generated scenario. `simulator/scenarios/compose.py` generates a real `docker-compose.yml` from a
scenario's roles/edges (one service per node, all on a scenario-local network, `UPSTREAM_HOSTS`
built from each node's outgoing edges) — following the exact convention every service in
`simulator/docker/docker-compose.yml` already uses (off-the-shelf image + mounted script, no
bespoke Dockerfile). The generated compose file uses absolute host paths for the `app.py` mount and
is only meant to be run on the machine that generated it — the same assumption every other artifact
under `experiments_data/` already makes.

## What's generated

`python -m simulator.scenarios.cli generate-all --root experiments_data` builds one representative
instance of each archetype and writes, per scenario, `declaration.json` and `docker-compose.yml`
under `experiments_data/scenarios/<scenario_id>/`:

| scenario_id | archetype | nodes | edges |
|---|---|---|---|
| `simple-chain-4` | simple_chain(4) | 4 | 3 |
| `star-4` | star(4) | 5 | 4 |
| `multi-tier-1-2-2-1` | multi_tier([1,2,2,1]) | 6 | 8 |
| `redundant-4` | redundant(4) | 4 | 4 |
| `multi-path-3` | multi_path(3) | 5 | 6 |
| `dynamic-6-seed42` | dynamic_service_network(seed=42, n=6) | 6 | 9 |

## Verification actually performed this phase

- `pytest simulator/tests/test_scenarios.py` — 15/15 passed: every archetype's structural claim
  verified via real NetworkX computation (see above); `build_declaration`/`build_roles` round-trip
  correctly; `build_topology_graph` constructs a valid Phase 04 `TopologyGraph` given a fake
  `ip_lookup`; invalid parameters (too few nodes/tiers/paths) correctly raise.
- `python -m scripts.check_ground_truth_boundary` — clean; `simulator/scenarios/` sits under the
  `simulator/` allowlist prefix, as expected.
- **Real integration run**: `python -m simulator.scenarios.cli generate-all` generated all 6
  scenarios for real; inspected `star-4`'s `declaration.json` and `docker-compose.yml` directly.
  Brought the generated `star-4` stack up for real (`docker compose -f
  experiments_data/scenarios/star-4/docker-compose.yml up -d`, 5 containers). Queried the live
  `hub` container's own reachability report (`http://localhost:8080/` inside the container) and
  confirmed all 4 leaves genuinely reachable:
  `{"node_role": "Gateway", "upstream_hosts": ["leaf-1", "leaf-2", "leaf-3", "leaf-4"],
  "reachability": {"leaf-1": true, "leaf-2": true, "leaf-3": true, "leaf-4": true}}`. Ran
  `python -m simulator.scenarios.cli capture-ground-truth --scenario-id star-4` and confirmed
  `topology.json` was written with 5 distinct real container IPs on the scenario-local Docker
  network. Torn down (`docker compose ... down`) after verification; confirmed no containers or
  networks left running.
- Full combined suite (`backend/tests experiments/tests simulator/tests`) — 110/110 passed, no
  regression.

## Explicitly deferred

The other 5 generated scenarios (`simple-chain-4`, `multi-tier-1-2-2-1`, `redundant-4`,
`multi-path-3`, `dynamic-6-seed42`) are real, ready-to-deploy artifacts but were not brought up this
phase — later phases (19 Traffic Replay, 20 Observatory Validation, 21+ capture) will deploy
whichever shape they actually need traffic/observations against, rather than this phase spinning up
every shape speculatively. Network-namespace segmentation (Phase 12's edge/app/data/external tiers)
is not re-derived per generated scenario — each scenario gets one flat scenario-local network,
deliberately kept simple; segmentation is a concern of the one fixed lab this phase doesn't
duplicate.

## Status

This document, together with `simulator/scenarios/{topologies,models,generate,compose,cli}.py`,
`simulator/scenarios/generic_node/app.py`, and `simulator/tests/test_scenarios.py`, satisfies
Phase 18: all 6 required topology archetypes are generated programmatically and parametrically
(not hand-declared), each with a verified real structural property, and are genuinely deployable —
confirmed by actually deploying one and capturing its real, hash-eligible ground truth.
