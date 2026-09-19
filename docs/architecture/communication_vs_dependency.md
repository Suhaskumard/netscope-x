# NETSCOPE-X — Communication vs. Dependency Distinction

Phase 50 deliverable. FR-1.25: *"The system shall explicitly distinguish 'A communicates with B'
from 'A depends on B' — communication alone shall never automatically imply dependency (spec Phase
50; RQ5)."* RQ5 (`docs/research/research_questions.md:134-145`) frames this as the foundation for
everything section 1.6 (Phases 50-56) builds: dependency inference (51), temporal precedence
(52-53), failure propagation (54), criticality (55), and causal evidence reporting (56) all depend
on this distinction holding, or their claims would be no more grounded than raw traffic volume.

Code: new `backend/dependency/` package, new `backend/dependency/communication.py`
(`derive_communication_relationships`).

## No new schema — the type separation is Phase 04's, already enforced

`backend/app/models/dependency.py`'s own module docstring already names this exact separation "the
central design point (spec Phase 50, RQ5)": `CommunicationRelationship` (`source_node_id`,
`target_node_id`, `frequency`, `persistence_seconds`) and `DependencyEdge` (`strength`,
`directionality_score`, `temporal_precedence_score`, ...) are two distinct Pydantic models with no
shared base class and no conversion method between them. `docs/architecture/data_contracts.md:26-28`
already documents this as a structural guarantee: "there is no implicit cast/coercion path from one
to the other." Phase 50 does not touch either schema — it makes `CommunicationRelationship` real for
the first time by actually computing it from evidence, which is the one piece that was still
missing.

## The building blocks were already built — Phase 50 is pure aggregation over them

`discover_nodes` (Phase 29) and `discover_edges` (Phase 30-31) already compute exactly the
"A communicates with B" evidence FR-1.25 needs: an `Edge` is defined as *"an inferred communication
relationship between two nodes"*, carrying `observation_count`, `first_observed`, `last_observed`,
and evidence-backed `confidence` — all real, non-fabricated aggregates over a capture's flows.
`derive_communication_relationships` calls both unmodified and maps each resulting `Edge` to one
`CommunicationRelationship`:

- `persistence_seconds = edge.last_observed - edge.first_observed` (seconds).
- `frequency = edge.observation_count / persistence_seconds` (observations/sec) — the natural rate
  interpretation of "how often do these two nodes communicate."

No new inference, no new confidence formula, no new comparison logic — the same "combine, don't
reinvent" pattern Phase 32's `build_topology_graph` already used to combine Phase 29's nodes and
Phase 30-31's edges.

## Candidate pruning: by already-inferred topology edges, per the committed algorithm design

`docs/architecture/algorithm_selection.md` section 6 ("Dependency inference") already commits to
this exact design: *"candidate pairs are pruned first by the (already-inferred) topology edges, so
this is not run on all O(V²) node pairs."* `derive_communication_relationships` follows this
literally — it never considers a node pair that `discover_edges` didn't already surface, rather than
independently re-deriving candidate pairs from raw flows.

## Documented edge case: zero-duration flows fall back to raw count, never divide by zero

An `Edge`'s `observation_count` is always `>= 1` (schema-enforced), but `persistence_seconds` can be
exactly `0` — every contributing flow shares the same `first_seen == last_seen` instant, e.g. a
single flow whose measured duration rounds to zero. A rate is not meaningful over a zero-length
window, so `frequency` falls back to `float(observation_count)` in that case rather than raising
`ZeroDivisionError` or reporting an unbounded/`inf` rate. This is an honest, documented edge case —
the same style as Phase 45's own "removals structurally real but practically vacuous" note — not a
silently assumed-away concern.

## What Phase 50 deliberately does NOT do

- **No strength, directionality, or temporal-precedence scoring.** `CommunicationRelationship` has
  no field for any of these — Phase 51 (`DependencyEdge.strength`) and Phase 52-53
  (`temporal_precedence_score`) are the phases that add scoring, over this phase's output, once they
  exist. There is no code path here that could accidentally produce a dependency-shaped claim,
  because the schema this phase returns structurally cannot carry one.
- **No API wiring.** There is no `GET /communications` route, and none is planned — `GET
  /dependencies` (`backend/app/api/routes/dependencies.py`) already declares its own backing
  implementation as *"spec Phase 51 (Dependency Strength)"* and stays an untouched 501 stub. This
  phase builds the capability Phase 51 will consume, the same build-now-wire-later precedent as
  Phase 44's `NetworkSnapshot` (unwired until Phase 47) and Phase 35's `fingerprints.jsonl` (unwired
  until Phase 36-37).
- **No causal claim of any kind.** `CausalEvidenceReport` (Phase 56) is many phases away; this phase
  produces plain observed-communication records only.

## Worked example

The same two-episode capture used throughout Phases 43-49 (A↔B at `t=0`, C↔D at `t=100s`):

```
derive_communication_relationships(root, "cap-1") ==
[
  CommunicationRelationship(source_node_id="cap-1:node:0", target_node_id="cap-1:node:1",
                             frequency=<observation_count>/<persistence_seconds>,
                             persistence_seconds=<last_observed - first_observed>),
  CommunicationRelationship(source_node_id="cap-1:node:2", target_node_id="cap-1:node:3",
                             frequency=<observation_count>/<persistence_seconds>,
                             persistence_seconds=<last_observed - first_observed>),
]
```

One relationship per already-inferred edge, in the same order `discover_edges` returns them
(sorted by `first_observed`, then node ids) — no re-sorting introduced here.

## Verification actually performed this phase

- `pytest backend/tests/test_dependency_communication.py -v` — **7/7 passed**: no packets/no flows
  produces `[]`; a single exchange's relationship matches its corresponding `Edge`'s
  `source_node_id`/`target_node_id`/`persistence_seconds`/`frequency` exactly; two independent
  episodes produce two relationships matching `discover_edges`'s own two-edge output; a
  zero-duration flow (`first_seen == last_seen`) correctly falls back to `frequency ==
  observation_count`, never a `ZeroDivisionError`; `as_of` bounding excludes later communication,
  passed straight through to both `discover_nodes` and `discover_edges`; every relationship's
  `frequency`/`persistence_seconds` are non-negative on real computed output; every returned
  relationship's field set is exactly `{source_node_id, target_node_id, frequency,
  persistence_seconds}` — structurally incapable of carrying a dependency-shaped claim.
- Full repo suite (`pytest backend/tests experiments/tests simulator/tests`, run from repo root) —
  **410/410 passed** (up from 403/403), no regressions.
- `python -m scripts.validate_data_contracts` — **38/38 passed**, no regression (no schema changes
  this phase; `CommunicationRelationship`/`DependencyEdge` were already validated there since
  Phase 04).
- `python -m scripts.check_ground_truth_boundary` — clean.
- A real, manual end-to-end run (no Docker needed): rebuilt the same two-episode capture, called
  `derive_communication_relationships` directly, and confirmed each returned relationship's
  `frequency`/`persistence_seconds` exactly matched a hand-computed value from the corresponding
  `discover_edges` output.

## Status

The communication/dependency type distinction (spec Phase 50, FR-1.25, RQ5) is implemented and
unit-verified. `derive_communication_relationships` produces real, evidenced
`CommunicationRelationship` records by aggregating over Phase 30-31's already-inferred topology
edges — no new schema, no new inference, and no code path capable of smuggling a dependency claim
into a communication-only type. `GET /dependencies` remains explicitly scoped to Phase 51, which
will be the first consumer of this phase's output.
