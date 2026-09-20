# NETSCOPE-X — Architecture and Data Contracts

Phase 04 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 04 — ARCHITECTURE AND DATA
CONTRACTS"). Defines the 13 required schema areas (packet, flow, node, edge, topology, behavioral
fingerprint, anomaly, snapshot, dependency, failure, simulation, experiment, metric) as Pydantic v2
models in `backend/app/models/`, and documents each one's purpose, key fields, and invariants.

All schemas are validated by `scripts/validate_data_contracts.py`, which constructs a valid and an
invalid instance of every schema and asserts the invalid case is rejected by Pydantic. Run:

```
.venv/Scripts/python.exe -m scripts.validate_data_contracts
```

Last run: 38/38 checks passed (see Phase 04 completion report for the executed output).

## Design principle: schemas encode the spec's non-negotiable rules

Where the master spec states a hard rule, the corresponding schema enforces it structurally, not just
by convention — invalid states are unrepresentable rather than merely discouraged:

- **No arbitrary confidence values** (spec Phase 31): `Edge` requires `evidence` (min length 1) and
  `observation_count` (>= 1) alongside `confidence` — a confidence score with no backing evidence
  cannot be constructed.
- **Anomalies must carry evidence** (spec Phase 41): `Anomaly.evidence` has `min_length=1`.
- **Communication is not dependency** (spec Phase 50; RQ5): `CommunicationRelationship` and
  `DependencyEdge` are two separate types with different fields — there is no implicit
  cast/coercion path from one to the other.
- **Causal claims need evidence, confidence, counter-evidence, and limitations** (spec Phase 56):
  `CausalEvidenceReport` requires all four; `limitations` specifically has `min_length=1` — a causal
  claim with zero stated limitations cannot be recorded, forcing explicit acknowledgment of
  uncertainty every time.
- **Counterfactuals never mutate the baseline** (spec Phase 65): `CounterfactualScenario` requires
  `isolated_graph_id != baseline_graph_id` by validator.
- **No fake metrics** (spec §21): `MetricResult.experiment_id` is required — a metric not tied to an
  actual experiment run cannot be constructed.
- **Full reproducibility field set** (spec §20, REPRO-1): every field on `Experiment` (seed, dataset
  version, code version, configuration, environment, timestamp) is required, not optional.

## Schema reference

### 1. Packet — `backend/app/models/packet.py`
Normalized packet observation (spec Phase 22). Fields: `packet_id`, `capture_id`, `timestamp`,
`src_ip`/`dst_ip` (validated IP addresses), `src_port`/`dst_port` (0–65535), `protocol`, `size_bytes`,
`direction`, optional `tcp_flags`. Frozen (immutable) — a packet observation is a historical fact and
should never be mutated after capture. Serves FR-1.1, FR-1.2.

### 2. Flow — `backend/app/models/flow.py`
Reconstructed bidirectional five-tuple flow (spec Phase 23–28). Includes `TCPState` enum
(syn_sent/established/closing/closed/reset/partial), optional `fingerprinted_protocol` (None means
"not confidently fingerprinted," never a disguised guess), and an embedded `FlowFeatures` sub-model
(packet/byte counts, duration, burstiness, inter-arrival time, forward-byte ratio, destination/port
diversity, persistence flag). Invariants: `last_seen >= first_seen`; `tcp_state` only valid when
`protocol == TCP`. Serves FR-1.3–FR-1.8.

### 3–4. Node / Edge — `backend/app/models/topology.py`
`Node`: inferred node identity, one-or-more observed IPs, first/last-observed timestamps. `Edge`:
inferred relationship between two nodes with required `confidence`, `evidence`, `observation_count`,
timestamps, and `protocols`. Invariant: no self-loops. `TopologyGraph` wraps a node/edge set for a
point in time and validates every edge references a node actually present in that graph. Serves
FR-1.9–FR-1.11. Deliberately excludes any ground-truth field — ground truth is a separate,
evaluation-only artifact per spec §4 and is out of scope for this pipeline-facing schema set.

### 5. Behavioral fingerprint / role classification — `backend/app/models/behavior.py`
`BehavioralFingerprint`: per-node signature over an `ObservationWindow` (short/medium/long).
`RoleClassification`: a `ServiceRole -> probability` mapping (`Dict[ServiceRole, float]`) rather than
a single label, with a validator enforcing the probabilities sum to ~1.0 (tolerance 1e-3) — this is
the concrete mechanism behind the "Database: 72%, Cache: 21%, Unknown: 7%" example in spec Phase 37.
Serves FR-1.12–FR-1.14.

### 6. Anomaly — `backend/app/models/anomaly.py`
`AnomalyDimension` (volume/destinations/ports/protocols/timing/topology/behavior) and `AnomalyClass`
(transient_anomaly vs. concept_drift, per spec Phase 39) are both modeled as enums so the two
distinct concepts from RQ4 can't be conflated. `evidence` (list, min length 1) and `evidence_values`
(structured key/value pairs, e.g. historical vs. current destination counts) together implement spec
Phase 41's explainability example. Serves FR-1.16–FR-1.19.

### 7. Snapshot — `backend/app/models/snapshot.py`
`NetworkSnapshot`: a versioned reference to a `TopologyGraph` at a point in time. `GraphChangeEvent`:
a single detected change (`ChangeType`: node/edge added/removed, attribute changed) between two
snapshots, with required `evidence` and a validator ensuring the change's target field
(`affected_node_id`/`affected_edge_id`/`attribute_name`) matches its declared `change_type`. Serves
FR-1.20–FR-1.24.

### 8. Dependency — `backend/app/models/dependency.py`
See "Design principle" above for the communication-vs-dependency split. `DependencyEdge` carries
`strength`, `frequency`, `persistence_seconds`, `directionality_score`, and
`temporal_precedence_score` (spec Phase 51–52), with a no-self-dependency invariant.
`CausalEvidenceReport` is the schema behind spec Phase 56's required report format. Serves
FR-1.25–FR-1.30.

### 9. Failure — `backend/app/models/failure.py`
`FailureScenario`: one of six failure types (spec Phase 59), with a validator requiring the target
field appropriate to that type (e.g., `node_failure` requires `target_node_id`;
`packet_loss` requires `packet_loss_ratio`). `PropagationImpact`: a single affected node at a given
`ImpactOrder` (primary/secondary/tertiary), with a validator enforcing that only non-primary impacts
carry a `caused_by_node_id` — this is the structural encoding of spec Phase 54's
primary→secondary→tertiary propagation chain. `ResilienceIndicators` covers spec Phase 62's six
measured indicators. Serves FR-1.28, FR-1.32–FR-1.35.

### 10. Simulation — `backend/app/models/simulation.py`
`SimulationRun`: one digital-twin execution against a `FailureScenario`. `CounterfactualAction` enum
implements spec Phase 64's six-verb scenario language (REMOVE_NODE, REMOVE_EDGE, INCREASE_LATENCY,
REDUCE_BANDWIDTH, INCREASE_TRAFFIC, ADD_ROUTE). `CounterfactualScenario` enforces
`isolated_graph_id != baseline_graph_id` (spec Phase 65's "never mutate the original baseline",
enforced structurally) via `_isolated_differs_from_baseline`, and — as of Phase 64 — every action's
own required fields via a second validator, `_action_requires_correct_fields` (e.g. REMOVE_NODE
requires `target_node_id`; ADD_ROUTE requires both the new `source_node_id` field and
`target_node_id` as its two distinct route endpoints, forbidding `target_edge_id` and a self-loop).
Unlike `FailureScenario`'s own Phase 04→59 split (the schema validated 4/6 failure types, Phase 59
patched the remaining two ambiguous types at execution time), Phase 64 is this schema's sole owner
before Phase 65 consumes it, so it enforces every action's requirements — including the
`REDUCE_BANDWIDTH` ambiguous-target case — in this one pass rather than deferring a gap. See
`docs/architecture/counterfactual_scenario_language.md` for the full per-action table. Serves
FR-1.31, FR-1.36–FR-1.38.

### 11. Experiment — `backend/app/models/experiment.py`
Implements REPRO-1 directly: every reproducibility field from spec §20 is a required (not optional)
field. `results` defaults to an empty dict because an experiment may be recorded before it completes,
but `random_seed`, `dataset_version`, `code_version`, `configuration`, `environment`, and `timestamp`
must always be present. Serves REPRO-1, REPRO-2.

### 12. Metric — `backend/app/models/metric.py`
One shared `MetricResult` schema reused across all seven `MetricContext` values (topology
reconstruction, role inference, anomaly detection, temporal, causal, PathForge, counterfactual) rather
than one schema per context — avoids duplicating the same precision/recall/F1/etc. fields seven times,
per spec §7's anti-overengineering principle. `experiment_id` is required, tying every metric to an
actual run (spec §21). Serves FR-1.39, FR-1.40, and the Phase 68 evaluation matrix.

## Explicitly deferred to later phases

- **Ground-truth schemas** (topology/role/dependency labels used only for evaluation, never for
  inference) — introduced when the laboratory and ground-truth generator exist (Phase 11, 16–17), to
  avoid speculative design now.
- **API request/response envelopes** (pagination, error format) — spec Phase 09, not this phase; these
  will wrap, not replace, the schemas defined here.
- **Persistence/storage mapping** (how these Pydantic models map to on-disk or database storage) — spec
  §6 says to choose the minimum persistence architecture necessary once there's a concrete access
  pattern to justify it; premature to decide now.
- **Dataset schemas** (`dataset_small`, `dataset_medium`, etc. metadata) — spec §19, introduced with
  the dataset-generation phases (14–19).

## Status

This document, together with `backend/app/models/`, satisfies Phase 04. All 13 required schema areas
are present and were validated by actually running `scripts/validate_data_contracts.py` (38/38 checks
passed) — not asserted without execution, per spec Rule 2.
