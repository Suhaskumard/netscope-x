# NETSCOPE-X — Phase 69 Acceptance Testing

Phase 69 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 69 — FINAL HARDENING AND
RELEASE"). This is a verification/report pass against `docs/requirements/system_requirements.md`
(Phase 03) — it adds no new pipeline stage or algorithm. Every row below was checked against the
actual module and test file cited, not restated from the requirement text or the spec. Status values:

- **verified** — the requirement's real implementation exists, is covered by a real (non-mocked)
  test, and that test was re-run in this phase as part of the full suite.
- **verified-partial** — real implementation exists and is tested, but with a stated, narrower scope
  than the requirement's literal wording (the gap is named, not hidden).
- **not satisfied** — no real implementation exists yet for this requirement's substance, or it exists
  but has no real path to the outside world (e.g. an unwired API route). Named honestly rather than
  marked "deferred" to avoid implying it was a deliberate, scoped-out decision.
- **not executable in this environment** — the requirement's implementation is real, but verifying it
  requires infrastructure (Docker lab, a real browser) not available in this session; see
  `docs/LIMITATIONS.md`.

## 1. Functional requirements

| FR | Status | Implementation | Verifying test(s) |
|---|---|---|---|
| FR-1.1 (ingest PCAP + controlled live capture) | verified-partial | `backend/nettrace/capture/ingest.py`, `simulator/capture/live.py` | `backend/tests/test_nettrace_capture.py`, `simulator/tests/test_capture.py`. PCAP ingestion is fully verified; live capture's interface-allowlist and now-structured `InterfaceUnavailableError` path are unit-verified, but a real Scapy `sniff()` against a live Docker lab interface has never run in any session — see `docs/architecture/packet_capture.md` "Known limitations". |
| FR-1.2 (packet normalization schema) | verified | `backend/nettrace/normalize.py` | `backend/tests/test_nettrace_normalize.py` |
| FR-1.3 (bidirectional 5-tuple flows) | verified | `backend/nettrace/reconstruct.py` | `backend/tests/test_nettrace_reconstruct.py` |
| FR-1.4 (TCP state tracking) | verified | `backend/nettrace/reconstruct.py` | `backend/tests/test_nettrace_reconstruct.py` (handshake, retransmission, partial-session, duplicate-SYN/FIN cases) |
| FR-1.5 (UDP session modeling) | verified | `backend/nettrace/reconstruct.py` | `backend/tests/test_nettrace_reconstruct.py` |
| FR-1.6 (protocol fingerprinting, no overclaiming) | verified | `backend/nettrace/fingerprint.py` | `backend/tests/test_nettrace_fingerprint.py` |
| FR-1.7 (encrypted-traffic metadata, no decryption) | verified | `backend/nettrace/tls_metadata.py` | `backend/tests/test_nettrace_tls_metadata.py` |
| FR-1.8 (per-flow features) | verified | `backend/flowmind/features/` | `backend/tests/test_flowmind_node_features.py` |
| FR-1.9 (nodes/edges from evidence only, no ground truth at inference) | verified | `backend/nettrace/topology/` | `backend/tests/test_nettrace_topology_discovery.py`, `backend/tests/test_nettrace_topology_edges.py`; boundary enforced structurally by `scripts/check_ground_truth_boundary.py` (re-run clean this phase) |
| FR-1.10 (edges carry confidence/evidence/count/timestamps/protocols) | verified | `backend/nettrace/topology/graph.py` | `backend/tests/test_nettrace_topology_graph.py` |
| FR-1.11 (complete probabilistic topology graph + ground-truth comparison) | verified | `backend/nettrace/topology/graph.py`, `experiments/metrics/topology_comparison.py` | `backend/tests/test_nettrace_topology_graph.py`, `experiments/tests/test_topology_comparison.py` |
| FR-1.12 (reusable behavioral features, multi-window) | verified | `backend/flowmind/features/`, `backend/flowmind/windows.py` | `backend/tests/test_flowmind_node_features.py`, `backend/tests/test_flowmind_windows.py` |
| FR-1.13 (per-node behavioral fingerprints) | verified | `backend/flowmind/fingerprints/node_fingerprint.py` | `backend/tests/test_flowmind_fingerprints.py` |
| FR-1.14 (service role inference, calibrated distribution) | verified-partial | `backend/flowmind/classification/role_classifier.py` | `backend/tests/test_flowmind_role_classifier.py`. Real classifier, real test coverage; **not reachable via the API** — `GET /behaviors/{node_id}` still raises `NotYetImplemented` (see §"API surface" below). |
| FR-1.15 (behavioral baseline) | verified | `backend/flowmind/baseline.py` | `backend/tests/test_flowmind_baseline.py` |
| FR-1.16 (anomaly vs. drift distinction) | verified | `backend/flowmind/drift.py` | `backend/tests/test_flowmind_drift.py` |
| FR-1.17 (multi-dimensional anomaly detection) | verified-partial | `backend/flowmind/anomaly/` | `backend/tests/test_flowmind_anomaly.py`, `backend/tests/test_flowmind_anomaly_explain.py`. Real detector, real tests; **not reachable via the API** — `GET /anomalies` still raises `NotYetImplemented`. |
| FR-1.18 (anomaly evidence, never a bare label) | verified | `backend/flowmind/anomaly/` | `backend/tests/test_flowmind_anomaly_explain.py` |
| FR-1.19 (FLOWMIND precision/recall/F1/FPR/FNR/latency) | verified | `experiments/metrics/anomaly_evaluation.py` | `experiments/tests/test_anomaly_evaluation.py`. Phase 68's full matrix run leaves `anomaly_detection` unscored by its own documented Phase 42 decision (no injected-anomaly dataset exists) — the metric code itself is real and unit-tested, only the full-matrix sweep excludes this context. |
| FR-1.20 (time-indexed graph G(t)) | verified | `backend/app/models/snapshot.py`, `backend/archaeology/snapshots.py` | `backend/tests/test_archaeology_snapshots.py` |
| FR-1.21 (versioned snapshots + structural diff) | verified | `backend/archaeology/snapshots.py`, `backend/archaeology/diff.py` | `backend/tests/test_archaeology_snapshots.py`, `backend/tests/test_archaeology_diff.py` |
| FR-1.22 (per-node behavioral evolution + event timeline) | verified | `backend/archaeology/behavior_evolution.py`, `backend/archaeology/timeline.py` | `backend/tests/test_archaeology_behavior_evolution.py`, `backend/tests/test_archaeology_timeline.py` |
| FR-1.23 (change attribution, no unsupported causal claims) | verified | `backend/archaeology/attribution.py` | `backend/tests/test_archaeology_attribution.py` |
| FR-1.24 (historical investigation queries) | verified | `backend/app/api/routes/history.py`, `backend/archaeology/` | `backend/tests/test_api.py` (`GET /history`) |
| FR-1.25 (communication != dependency) | verified | `backend/dependency/communication.py` | `backend/tests/test_dependency_communication.py` |
| FR-1.26 (dependency strength estimation) | verified | `backend/dependency/strength.py` | `backend/tests/test_dependency_strength.py` |
| FR-1.27 (temporal precedence, correlation != causation) | verified | `backend/dependency/temporal_precedence.py`, `backend/dependency/causal_candidates.py` | `backend/tests/test_dependency_temporal_precedence.py`, `backend/tests/test_dependency_causal_candidates.py` |
| FR-1.28 (multi-order impact graph) | verified | `backend/dependency/failure_propagation.py` | `backend/tests/test_dependency_failure_propagation.py` |
| FR-1.29 (graph criticality metrics + rationale) | verified | `backend/dependency/criticality.py` | `backend/tests/test_dependency_criticality.py` |
| FR-1.30 (causal evidence report per dependency/propagation) | verified | `backend/dependency/causal_evidence.py` | `backend/tests/test_dependency_causal_evidence.py`, `backend/tests/test_api.py` (`GET /causal/{dependency_id}`) |
| FR-1.31 (digital twin build + sync) | verified | `backend/digital_twin/` | `backend/tests/test_digital_twin.py`, `backend/tests/test_digital_twin_sync.py` |
| FR-1.32 (controlled failure injection, 6 types) | verified | `backend/simulation/failure_injection.py` | `backend/tests/test_failure_injection.py` |
| FR-1.33 (paths/costs/route changes/disconnection) | verified | `backend/simulation/path_engine.py` | `backend/tests/test_path_engine.py` |
| FR-1.34 (connected failure->routing->service pipeline) | verified | `backend/simulation/failure_propagation_pipeline.py` | `backend/tests/test_failure_propagation_pipeline.py` |
| FR-1.35 (resilience indicators) | verified | `backend/simulation/resilience_indicators.py` | `backend/tests/test_resilience_indicators.py` |
| FR-1.36 (counterfactual scenario language, 6 actions) | verified | `backend/app/models/simulation.py` | `python -m scripts.validate_data_contracts` (all 6 `CounterfactualAction` variants, valid + invalid) |
| FR-1.36/1.37 (isolated execution + baseline/counterfactual comparison) | verified-partial | `backend/simulation/counterfactual_engine.py`, `backend/simulation/counterfactual_comparison.py` | `backend/tests/test_counterfactual_engine.py`, `backend/tests/test_counterfactual_comparison.py`. Real engine, real tests, real mutation-safety checks; **not reachable via the API** — `POST /counterfactual` still raises `NotYetImplemented`. |
| FR-1.38 (twin/counterfactual predictions vs. real experiment outcomes) | verified | `experiments/metrics/failure_propagation_validation.py`, `experiments/metrics/counterfactual_validation.py` | `experiments/tests/test_failure_propagation_validation.py`, `experiments/tests/test_counterfactual_validation.py` |
| FR-1.39 (experiment recommendations from structural evidence) | verified | `backend/dependency/experiment_recommendations.py` | `backend/tests/test_experiment_recommendations.py` |
| FR-1.40 (full experimental matrix + ablations) | verified | `experiments/matrix_runner.py` | `experiments/tests/test_matrix_runner.py`; a real 54-cell matrix run completed in ~13s (Phase 68). `causal_analysis` measured 0.0 accuracy in that run — an honestly-reported synthetic-data limitation of the traffic generator, not a defect in Phases 50-53 (see `docs/architecture/experimental_matrix.md`). |
| FR-1.41 (12 versioned, typed API endpoints, consistent errors) | verified-partial | `backend/app/api/router.py`, `backend/app/api/routes/*.py` | `backend/tests/test_api.py`. All 12 route groups exist, are typed, and share one error envelope (`backend/app/api/errors.py`). 5 of 12 remain `NotYetImplemented` (501) by design-to-date: `GET /anomalies`, `GET /behaviors/{node_id}`, `POST /simulation`, `POST /counterfactual`, `POST /experiments` — their backing computation is real (see FR-1.14/1.17/1.32-37/1.40 rows) but no route currently calls it. This is the single largest concrete gap this phase found; wiring these routes is scoped as new integration work, not a Phase 69 verification-pass change (see `docs/LIMITATIONS.md`). |
| FR-1.42 (frontend: 9 required screens, real data) | **not satisfied** | `frontend/src/App.tsx` | none. The frontend has remained the Phase 06 placeholder scaffold (`App.tsx`, `main.tsx` only) through all 68 prior phases — no Overview/Topology Explorer/Node Investigation/Timeline/Anomaly Investigation/Causal Analysis/Simulation/Counterfactual/Experiment Lab screen exists. This is reported plainly rather than as a "deferred, scoped decision" because no phase log names an explicit reason for deferring it. |

## 2. Non-functional requirements

| NFR | Status | Notes |
|---|---|---|
| NFR-1 (modular, testable stages) | verified | Each of NETTRACE/FLOWMIND/Archaeology/Causal/PathForge/Counterfactual/Experiments is its own top-level package (`backend/nettrace`, `backend/flowmind`, `backend/archaeology`, `backend/dependency`, `backend/simulation`, `experiments`) with its own test module(s). |
| NFR-2 (typed interfaces) | verified-partial | Backend: every model in `backend/app/models/` is Pydantic; `python -m scripts.validate_data_contracts` (55/55) re-verified clean this phase. Frontend TypeScript types: N/A — no frontend feature code exists yet to type (ties to FR-1.42). |
| NFR-3 (determinism) | verified | Exercised throughout, e.g. `backend/tests/test_experiment_recommendations.py` asserts exact determinism; `experiments/synthetic_traffic.py` is seeded. |
| NFR-4 (no hardcoded paths/magic numbers) | verified | `backend/app/core/config.py` (`Settings`, env-driven); `experiments/artifacts/paths.py` takes an explicit `root`. Spot-checked: no hardcoded absolute paths found in `backend/`/`experiments/`/`simulator/` production code (`grep` pass, this phase). |
| NFR-5 (structured logging, request/experiment IDs) | verified | `backend/app/core/logging.py`, `backend/app/core/context.py` (`get_request_id`), `backend/app/api/errors.py`'s unhandled-exception handler logs with `log_exception`. |
| NFR-6 (versioned APIs) | verified | `backend/app/api/router.py`: `APIRouter(prefix="/api/v1")`. |
| NFR-7 (no global state / circular imports / giant files) | verified | `python -m scripts.check_ground_truth_boundary` re-verified clean this phase (a static import-boundary guard); no module in the codebase exceeds ~500 lines except `docs/PROJECT_STATE.md` (a log, not code). |
| NFR-8 (no hardcoded topology/classification in inference path) | verified | Enforced structurally by FR-1.9's ground-truth boundary; role classification (`backend/flowmind/classification/role_classifier.py`) is evidence-driven, not a lookup table. |
| NFR-9 (no overengineering; no unjustified infra) | verified | No database/cache/queue exists anywhere in the codebase; `experiments/artifacts/` uses plain JSON/JSONL files on disk throughout (a deliberate, repeatedly-documented choice, e.g. `docs/architecture/research_artifacts.md`). |

## 3. Performance requirements

| PERF | Status | Notes |
|---|---|---|
| PERF-1..7 | **not satisfied** (deliberately deferred) | Per FR-1.40's own phase note, "PERF-1..8 benchmarking and provisional-constant recalibration are explicitly deferred (FR-1.40 asks to measure, not tune)." No throughput/latency/memory/render-time benchmark has been run in any phase to date. |
| PERF-8 (no scalability claim without a benchmark) | verified | Consistent with the above: no scalability claim appears anywhere in `docs/` or `README.md`. |

This phase does not attempt to retroactively produce PERF-1..7 benchmarks: doing so would be new
measurement work, not verification of existing measurement work, and none exists yet to verify. This
is named as a real, unresolved gap in `docs/LIMITATIONS.md`, not silently dropped.

## 4. Reliability requirements

| REL | Status | Verifying test(s) |
|---|---|---|
| REL-1 (corrupted PCAP) | verified | `backend/tests/test_nettrace_capture.py` (also `test_api.py::test_capture_pcap_upload_invalid_pcap_content_returns_422`) |
| REL-2 (malformed packets) | verified | `backend/tests/test_nettrace_normalize.py` |
| REL-3 (missing required fields) | verified | `backend/tests/test_nettrace_normalize.py` |
| REL-4 (incomplete flows) | verified | `backend/tests/test_nettrace_reconstruct.py::test_reconstruct_flows_incomplete_handshake_yields_partial` |
| REL-5 (unknown/unsupported protocols) | verified | `backend/tests/test_nettrace_fingerprint.py` |
| REL-6 (duplicate packets) | verified | `backend/tests/test_nettrace_reconstruct.py` (duplicate SYN/FIN cases) |
| REL-7 (out-of-order packets) | verified | `backend/tests/test_nettrace_reconstruct.py`, `backend/tests/test_path_engine.py` |
| REL-8 (invalid scenario/counterfactual definitions) | verified | `python -m scripts.validate_data_contracts` (every `CounterfactualAction`/`FailureScenario` invalid-input case, 55/55) |
| REL-9 (disconnected graphs after failure) | verified | `backend/tests/test_path_engine.py`, `backend/tests/test_dependency_criticality.py`, `backend/tests/test_counterfactual_engine.py` |
| REL-10 (empty datasets) | verified | Present across most `backend/tests/*.py` modules (empty-input cases) |
| REL-11 (very large datasets degrade, not crash) | **not executable in this environment** | No large-scale dataset stress test has been run against a real deployment; this ties directly to the deferred PERF-1..8 benchmarking above. |
| REL-12 (unavailable network interface during live capture) | verified (new this phase) | `simulator/tests/test_capture.py::test_capture_raises_structured_error_when_authorized_interface_unavailable` — added this phase after finding `simulator/capture/live.py`'s `sniff()` call let a raw `OSError` propagate uncaught; now wrapped in a new `InterfaceUnavailableError` (`backend/nettrace/capture/errors.py`). |

## 5. Security requirements

| SEC | Status | Notes |
|---|---|---|
| SEC-1 (validate all external input) | verified | Every request body is a Pydantic model; every query param uses FastAPI `Query(...)` with explicit constraints. |
| SEC-2 (no shell=True / arbitrary shell execution) | verified | Only production `subprocess` use is `simulator/ground_truth/cli.py` (`docker ps`/`docker inspect`), both list-argument calls, no `shell=True` anywhere in the codebase (`grep` pass, this phase). |
| SEC-3 (uploaded file validation) | verified | `backend/nettrace/capture/ingest.py::validate_pcap_bytes` (type/content); `backend/tests/test_api.py::test_capture_pcap_upload_rejects_path_traversal_filename` covers filename handling. |
| SEC-4 (path traversal prevention) | verified (fixed this phase) | Found and fixed a real gap: `GET /flows`, `/topology`, `/dependencies`, `/history`, `/causal/{id}` accepted `capture_id` as an unconstrained string that is used verbatim as a filesystem path segment (`experiments/artifacts/paths.py`). Added `CAPTURE_ID_PATTERN` (`backend/app/api/schemas.py`) as a FastAPI `Query(pattern=...)` constraint on all five routes. New test: `backend/tests/test_api.py::test_path_traversal_capture_id_rejected_before_touching_disk`. `dependency_id` (path param on `GET /causal/{dependency_id}`) was checked and found safe — it is only ever used for an in-memory equality match, never for path construction. |
| SEC-5 (resource limits on capture/processing/simulation) | **not satisfied** | No request size limit, timeout, or concurrency cap was found on `POST /capture`, `POST /simulation`, or `POST /counterfactual`. A single request could, in principle, be given an arbitrarily large upload or an arbitrarily expensive scenario. Named as a real gap, not fixed this phase (adding limits without a real load-testing basis for the right values risks an arbitrary, undocumented magic number, which NFR-4/NFR-9 both warn against). |
| SEC-6 (capture restricted to authorized lab interfaces) | verified | `backend/nettrace/capture/authorized_interfaces.py`; `simulator/tests/test_capture.py` |
| SEC-7 (no secrets committed) | verified | `git log -p --all -- '*.env' '*secret*' '*credential*'` and a repo-wide grep for common secret patterns (`grep -rIn "api_key\s*=\s*['\"]" `, AWS/GCP key patterns) found nothing; `.gitignore` excludes `.env`. |
| SEC-8 (auth / API-abuse protection) | not satisfied (deliberately deferred) | Restated from `docs/requirements/system_requirements.md`'s own "Known limitations": deliberately out of scope for the current local/lab-only deployment context. |

## 6. Reproducibility requirements

| REPRO | Status | Notes |
|---|---|---|
| REPRO-1 (experiment records: id/dataset/code version/config/seed/timestamp/env/params/results) | verified | `backend/app/models/experiment.py::Experiment` requires every one of these fields (no default), confirmed by `scripts.validate_data_contracts`'s "missing required random_seed" rejection case. |
| REPRO-2 (rerunnable, equivalent results given same seed) | verified | `experiments/synthetic_traffic.py` is seeded; `backend/tests/test_experiment_recommendations.py` and others assert exact determinism. |
| REPRO-3 (ground-truth versioned + hashed) | verified | `experiments/artifacts/paths.py` (`*.sha256` sidecars); `simulator/tests/test_ground_truth_integrity.py` |
| REPRO-4 (ground truth never an inference input) | verified | Enforced by `scripts/check_ground_truth_boundary.py`, re-verified clean this phase. |
| REPRO-5 (each dataset: description/procedure/ground truth/properties/version/checksum) | verified-partial | The mechanism (`experiments/artifacts/`) supports this for every capture actually generated; the spec's named 8 datasets (`_small/_medium/_large/_dynamic/_failure/_anomaly/_incomplete/_noisy`) have not all been generated as standing, checked-in fixtures — they are produced on demand by `simulator/scenarios/` + `experiments/synthetic_traffic.py` generators, which is the mechanism REPRO-5 requires, not a missing capability. |

## Summary

- **42 FRs**: 32 verified, 8 verified-partial, 2 not satisfied (FR-1.41's unwired-routes gap is
  counted once against FR-1.41 itself; the 5 individual FRs behind those routes — FR-1.14, FR-1.17,
  FR-1.36/1.37 — are separately marked verified-partial above since their real logic is tested).
- **9 NFRs**: 8 verified, 1 verified-partial (frontend typing, N/A pending FR-1.42).
- **8 PERFs**: 7 not satisfied (deliberately deferred per FR-1.40's own phase note), 1 (PERF-8)
  verified by absence of any unbacked claim.
- **12 RELs**: 10 verified (1 fixed this phase — REL-12), 1 not executable in this environment
  (REL-11), 0 outright failing.
- **8 SECs**: 6 verified (1 fixed this phase — SEC-4), 2 not satisfied (SEC-5 real gap, SEC-8
  deliberately deferred).
- **5 REPROs**: 4 verified, 1 verified-partial.

Two concrete code changes came out of this verification pass (not new features, both closing a real
gap found while checking an existing requirement): the `InterfaceUnavailableError` wrap (REL-12) and
the `CAPTURE_ID_PATTERN` path-traversal fix (SEC-4). Everything else above is reporting, not new
computation, matching Phase 69's own scope as recorded in `docs/PROJECT_STATE.md`.

## What this phase deliberately did not do

- Did not wire `GET /anomalies`, `GET /behaviors/{node_id}`, `POST /simulation`,
  `POST /counterfactual`, or `POST /experiments` to their real backing modules. Each of those modules
  is independently real and tested; wiring five routes together is a meaningful, reviewable chunk of
  integration work in its own right (request/response shaping, pagination, error-path decisions —
  the same amount of design judgment every prior phase's route-wiring commit, e.g. Phase 51/56,
  applied one route at a time) and is out of scope for a single verification/documentation phase.
- Did not build any part of the FR-1.42 frontend. The gap is real and large (a 9-screen SPA), not a
  hardening-sized task.
- Did not fabricate PERF-1..7 benchmark numbers or REL-11 large-dataset results. Both require running
  the full pipeline under load in a real environment, honestly out of reach in this session.
- Did not add SEC-5 resource limits with unbenchmarked, made-up thresholds.

See `docs/LIMITATIONS.md` for the consolidated limitations list this report draws from.
