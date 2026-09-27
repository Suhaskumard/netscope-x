# NETSCOPE-X — v0.108.0 Release Notes

This tag marks the state of the project after Phase 108, the final cross-phase acceptance audit
(`docs/acceptance_testing_phase108.md`). **This is not a 1.0/GA claim.** The version number (`0.108.0`)
tracks the phase count, not a readiness level: per the spec's own instruction, a release is cut only
after every requirement's status is recorded honestly, including the ones that are not met. Several
are not met. Read `docs/acceptance_testing_phase108.md` before deploying this anywhere beyond a local
research/lab context.

## What is real and working
- The full NETTRACE -> FLOWMIND -> Archaeology -> Dependency/Causal -> Digital Twin -> Simulation ->
  Counterfactual -> Experimentation pipeline (Phases 21-68), each stage independently tested.
- 8 of 12 API route groups wired to real computation, typed, versioned (`/api/v1`), with a consistent
  error envelope.
- 3 of 9 required frontend screens (Topology Explorer, Causal Analysis, Experiment Lab), each showing
  real API data with no placeholder content.
- Opt-in Bearer-token authentication and per-tenant isolation (`backend/app/auth/`, `backend/app/tenancy/`).
- A one-command reproducibility package (`repro/run.sh`) and a research paper draft
  (`docs/research/paper_draft.md`) whose every cited number traces to a real recorded result.
- Formal statistical significance testing and a real longitudinal drift study of the calibrated constants.

## What is not done — read before relying on this
- **4 API route groups remain unwired** (`GET /anomalies`, `GET /behaviors/{node_id}`,
  `POST /simulation`, `POST /counterfactual`) — their backing logic is real and tested, but not
  reachable through the API.
- **6 of 9 frontend screens do not exist** (Overview, Node Investigation, Timeline, Anomaly
  Investigation, Simulation, Counterfactual).
- **No system-level performance benchmark has ever been run** (PERF-1..7): no measured throughput,
  latency, or memory number exists for the pipeline as deployed.
- **No large-dataset stress test has been run** (REL-11).
- **No resource limits exist on `/capture`, `/simulation`, `/counterfactual`** (SEC-5): a single
  request could submit an arbitrarily large upload.
- **Authentication and tenant isolation are off by default** (SEC-8): a default deployment is
  anonymous and single-tenant, exactly as before Phase 91/92.
- **No real-world network trace has ever been run** through the Phase 103 cross-domain validation
  harness — external validity is unmeasured.

## Verification for this release
- Full test suite: 1023/1023 passing
- `python -m scripts.validate_data_contracts`: 55/55
- `python -m scripts.check_ground_truth_boundary`: clean
- Full detail, evidence, and every requirement's individual status: `docs/acceptance_testing_phase108.md`.

This file and the `VERSION` file were prepared by the Phase 108 audit. No git tag was created —
tagging the actual release is left to the project owner.
