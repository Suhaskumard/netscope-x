# NETSCOPE-X

NETSCOPE-X is a research platform for reconstructing and understanding network behavior from traffic, topology, behavioral signals, and failure telemetry. It models the network as a living system: infer nodes and links, learn service roles, detect drift and anomalies, trace historical change, estimate dependencies, and simulate the consequences of failures or counterfactual interventions.

This repository brings together packet analysis, graph reconstruction, behavioral modeling, temporal archaeology, causal reasoning, digital-twin synthesis, and reproducible experiment evaluation in one codebase. 

## At a glance

- Research focus: network reconstruction, dependency inference, and failure-impact analysis
- Core stack: Python, FastAPI, Pydantic, NetworkX, Scapy, Docker, and React/Vite/Tailwind
- Operating model: capture → normalize → infer topology → model behavior → detect drift → estimate dependencies → simulate outcomes
- Primary use case: observability-driven network intelligence for research, controlled experiments, and failure analysis

## Current status snapshot

| Area | Status |
| --- | --- |
| Packet capture and normalization | Implemented |
| Flow reconstruction and topology inference | Implemented |
| Behavioral fingerprints and role inference | Implemented |
| Drift and anomaly detection | Implemented |
| Temporal archaeology and historical diffing | Implemented |
| Dependency, causal reasoning, and criticality analysis | Implemented |
| Digital twin and simulation modules | Implemented as library components |
| Frontend UI | Scaffolded placeholder |
| API route coverage | Partial |

## Project goals

- Reconstruct network topology from packet captures and traffic evidence
- Infer service roles and behavioral fingerprints for observed entities
- Detect anomalies and concept drift across time windows
- Build temporal snapshots and historical change views of the network
- Estimate dependencies and causal candidates from observed interaction patterns
- Simulate failures, routing changes, and counterfactual scenarios
- Evaluate results against ground truth in reproducible experiments

## Why this project exists

This is not a generic dashboard or chatbot. NETSCOPE-X is a grounded network intelligence system built for observability, inference, experimentation, and verification. The repository is intentionally organized around a research workflow that separates:

- packet capture and normalization
- flow reconstruction and topology inference
- behavioral analysis and anomaly detection
- archaeology and historical change tracking
- dependency and causal reasoning
- simulation and counterfactual analysis
- experiment evaluation and validation

## Architecture overview

The repository is divided into a small set of specialized areas:

- backend/app: API layer, shared models, config, and service entry points
- backend/nettrace: packet capture, normalization, flow reconstruction, and topology discovery
- backend/flowmind: behavioral fingerprints, role inference, drift detection, and anomaly logic
- backend/archaeology: snapshots, diffs, timelines, and attribution over time
- backend/dependency: communication, dependency strength, temporal precedence, and causal evidence
- backend/digital_twin: digital twin construction and synchronization
- backend/simulation: failure injection, path analysis, propagation, and counterfactual execution
- experiments: evaluation scripts, synthetic traffic generation, and matrix-based runs
- simulator: Docker-based lab environments and traffic generators for controlled scenarios
- frontend: React/Vite/Tailwind-based UI scaffold

## Repository structure

```text
NETSCOPE-X/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── routes/
│   │   │   ├── schemas.py
│   │   │   ├── errors.py
│   │   │   └── router.py
│   │   ├── core/
│   │   │   ├── config.py
│   │   │   ├── context.py
│   │   │   ├── logging.py
│   │   │   └── timing.py
│   │   ├── models/
│   │   │   ├── network.py
│   │   │   ├── simulation.py
│   │   │   ├── experiment.py
│   │   │   └── ...
│   │   └── main.py
│   ├── archaeology/
│   │   ├── snapshots.py
│   │   ├── diff.py
│   │   ├── timeline.py
│   │   ├── attribution.py
│   │   └── behavior_evolution.py
│   ├── dependency/
│   │   ├── communication.py
│   │   ├── strength.py
│   │   ├── temporal_precedence.py
│   │   ├── causal_candidates.py
│   │   ├── failure_propagation.py
│   │   ├── criticality.py
│   │   ├── causal_evidence.py
│   │   └── experiment_recommendations.py
│   ├── digital_twin/
│   │   ├── twin.py
│   │   └── sync.py
│   ├── flowmind/
│   │   ├── features/
│   │   ├── fingerprints/
│   │   ├── classification/
│   │   ├── baseline/
│   │   ├── drift/
│   │   ├── anomaly/
│   │   └── ...
│   ├── nettrace/
│   │   ├── capture/
│   │   ├── topology/
│   │   ├── normalize.py
│   │   ├── reconstruct.py
│   │   ├── fingerprint.py
│   │   └── tls_metadata.py
│   ├── simulation/
│   │   ├── failure_injection.py
│   │   ├── path_engine.py
│   │   ├── failure_propagation_pipeline.py
│   │   ├── resilience_indicators.py
│   │   ├── counterfactual_engine.py
│   │   └── counterfactual_comparison.py
│   ├── tests/
│   ├── Dockerfile
│   └── __init__.py
│
├── experiments/
│   ├── artifacts/
│   ├── metrics/
│   ├── synthetic_traffic.py
│   ├── observation_sampling.py
│   ├── matrix_runner.py
│   └── tests/
│
├── frontend/
│   ├── src/
│   ├── package.json
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   └── Dockerfile
│
├── simulator/
│   ├── docker/
│   ├── traffic/
│   ├── scenarios/
│   ├── ground_truth/
│   ├── capture/
│   └── tests/
│
├── docs/
│   ├── research/
│   ├── requirements/
│   ├── architecture/
│   ├── development/
│   ├── API.md
│   ├── ARCHITECTURE.md
│   ├── DEVELOPMENT.md
│   ├── TESTING.md
│   ├── EXPERIMENTS.md
│   ├── LIMITATIONS.md
│   ├── DEPLOYMENT.md
│   ├── PROJECT_STATE.md
│   └── acceptance_testing.md
│
├── scripts/
│   ├── setup.sh
│   ├── validate_data_contracts.py
│   ├── validate_observatory.py
│   ├── check_ground_truth_boundary.py
│   └── ...
│
├── docker-compose.yml
├── requirements.txt
├── requirements-dev.txt
├── README.md
└── NETSCOPE (1).pdf
```

## Quick start

### Prerequisites

- Python 3.12
- Node 22
- Docker (recommended for local lab and container workflows)

### Setup

```bash
bash scripts/setup.sh
```

This bootstraps the Python environment, installs the pinned dependencies, and prepares the frontend tooling.

### Run the backend locally

```bash
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

### Run the test suite

```bash
pytest backend/tests experiments/tests simulator/tests
```

### Validate contracts and boundaries

```bash
python -m scripts.validate_data_contracts
python -m scripts.check_ground_truth_boundary
```

### Start local services

```bash
docker compose up --build
```

For the network lab workflow:

```bash
docker compose -f simulator/docker/docker-compose.yml up -d
python -m scripts.validate_observatory
```

## Key workflows

### 1. Capture and normalize traffic

The pipeline begins with packet captures and the modules under backend/nettrace to normalize traffic, reconstruct flows, and generate topology evidence.

### 2. Model behavior and anomalies

The flowmind package computes behavioral fingerprints, extracts features over time, infers service roles, and identifies drift or anomalous behavior.

### 3. Track change over time

The archaeology package builds snapshots, diffs, timelines, and attribution models so the network can be understood as a temporal system.

### 4. Infer dependencies and causality

The dependency package estimates communication patterns, dependency strength, temporal precedence, candidate causal links, and operational criticality.

### 5. Simulate and evaluate

Simulation, digital twin, and experimentation modules let teams test route changes, failure scenarios, counterfactuals, and matrix-based evaluation against known or synthetic ground truth.

## Documentation

The project includes deeper design and operations guidance in the docs folder, including:

- docs/ARCHITECTURE.md
- docs/API.md
- docs/DEVELOPMENT.md
- docs/TESTING.md
- docs/EXPERIMENTS.md
- docs/LIMITATIONS.md
- docs/DEPLOYMENT.md
- docs/PROJECT_STATE.md

## Current status

This repository is a research-grade implementation with active modules across the stack. Some components are fully implemented, while others remain intentionally scaffolded or documented as future work. The project documentation is explicit about what has been verified and what remains theoretical, exploratory, or unimplemented.


## License

This project is intended for research and internal engineering use. Check the repository for any licensing details included in your branch or deployment environment.

## Notes

The project is intentionally rigorous about evidence and verification. Its documentation and tests emphasize what was actually measured versus what remains speculative, aspirational, or future work.
