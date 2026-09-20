# NETSCOPE-X — System Architecture

Phase 69 documentation deliverable: a system-level overview linking together the 20 per-module design
docs already written in `docs/architecture/*.md` (one per phase's real algorithmic decision). Read
this first for the shape of the whole system; read the linked per-module doc before changing that
module's logic, since each carries its own algorithm rationale and documented limitations that this
overview does not repeat.

## Pipeline (spec §9)

```
PCAP / live capture
  -> Normalized Packet         (backend/nettrace/normalize.py)                [docs/architecture/packet_normalization.md]
  -> Flow (5-tuple, TCP/UDP)   (backend/nettrace/reconstruct.py)              [docs/architecture/tcp_state_tracking.md, udp_session_modeling.md]
  -> Protocol fingerprint      (backend/nettrace/fingerprint.py)              [docs/architecture/protocol_fingerprinting.md]
  -> Flow features             (backend/flowmind/features/)
  -> Node/Edge candidates      (backend/nettrace/topology/)                   [docs/architecture/node_discovery.md, topology_reconstruction.md]
  -> Probabilistic graph       (backend/nettrace/topology/graph.py)
  -> Behavioral fingerprints   (backend/flowmind/fingerprints/)               [docs/architecture/service_role_inference.md]
  -> Baseline + drift          (backend/flowmind/baseline.py, drift.py)
  -> Anomalies                 (backend/flowmind/anomaly/)
  -> Temporal snapshots        (backend/archaeology/snapshots.py)             [docs/architecture/temporal_graph_model.md]
  -> Diff / timeline           (backend/archaeology/diff.py, timeline.py)     [docs/architecture/topology_event_timeline.md]
  -> Dependency graph          (backend/dependency/)                          [docs/architecture/resilience_indicators.md]
  -> Causal candidates         (backend/dependency/causal_candidates.py)      [docs/architecture/temporal_precedence_analysis.md]
  -> Digital twin              (backend/digital_twin/)
  -> Simulation (failure)      (backend/simulation/failure_injection.py, path_engine.py)
  -> Counterfactual scenario   (backend/simulation/counterfactual_engine.py)
  -> Experimental validation   (experiments/matrix_runner.py)                 [docs/architecture/experimental_matrix.md]
```

Every stage is a real, independently testable module (NFR-1) — see `docs/TESTING.md` for the test
file backing each one, and `docs/acceptance_testing.md` for the full requirement-level traceability.

## API layer

`backend/app/api/` exposes the pipeline's outputs over a versioned REST surface
(`/api/v1/...`, spec Phase 09) — see `docs/API.md`. 7 of 12 route groups are real; 5 validate input
but do not yet call their (real, tested) backing module — see `docs/LIMITATIONS.md`.

## Research/experimentation layer

`experiments/` is separate from `backend/` on purpose: it holds evaluation code that compares
inference output to ground truth (`experiments/metrics/`), the on-disk artifact layout
(`experiments/artifacts/`), synthetic traffic generation for reproducible experiments
(`experiments/synthetic_traffic.py`), and the full experimental matrix (`experiments/matrix_runner.py`
— see `docs/EXPERIMENTS.md`). Ground truth flows one direction only: `experiments/`/`simulator/` may
know it, `backend/`'s inference modules never may (spec §4) — enforced structurally by
`scripts/check_ground_truth_boundary.py`.

## Simulation lab

`simulator/` is the controlled network laboratory NETSCOPE-X observes: Docker Compose topology
(`simulator/docker/`), traffic/protocol generators (`simulator/traffic/`), scenario generation
(`simulator/scenarios/`), ground-truth generation (`simulator/ground_truth/`), and controlled live
capture (`simulator/capture/`). See `docs/DEPLOYMENT.md`.

## Frontend

`frontend/` is a React/TypeScript/Vite/Tailwind scaffold intended to implement the 9 screens named in
spec §12 (Overview, Topology Explorer, Node Investigation, Timeline, Anomaly Investigation, Causal
Analysis, Simulation, Counterfactual, Experiment Lab). As of Phase 69 it remains an unbuilt
placeholder — see `docs/LIMITATIONS.md`, FR-1.42.

## Cross-cutting concerns

- **Typed contracts** (NFR-2): every backend data shape is a Pydantic model in `backend/app/models/`,
  checked round-trip by `scripts/validate_data_contracts.py`.
- **Configuration** (NFR-4): `backend/app/core/config.py::Settings`, entirely environment-variable
  driven (`NETSCOPE_` prefix), no hardcoded paths or unnamed thresholds.
- **Observability** (NFR-5): `backend/app/core/logging.py` (structured logging), `context.py`
  (request-ID correlation) — see `docs/architecture/observability.md`.
- **Error handling** (spec §15): one `ErrorResponse` envelope for every failure mode, mapped in
  `backend/app/api/errors.py` — see `docs/API.md`'s error-code table.
