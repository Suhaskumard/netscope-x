# NETSCOPE-X — Phase 108 Final Cross-Phase Acceptance Audit

Phase 108 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 108 — FINAL CROSS-PHASE ACCEPTANCE AUDIT"): re-verify every
FR/NFR/PERF/REL/SEC/REPRO in `docs/requirements/system_requirements.md` against its own acceptance criteria across all 108 phases,
in one consolidated audit, recording each requirement's status honestly before any release is cut. This is a verification/reporting
pass, like Phase 69 before it (`docs/acceptance_testing.md`) — it adds no new pipeline stage or algorithm, and it fixes small,
unambiguous gaps it finds along the way rather than papering over them (Phase 69's own precedent: REL-12, SEC-4).

Every row below was checked against the actual current module/route/test file in this session, not restated from Phase 69's table
or from a phase's own log entry. Status taxonomy (same as Phase 69):

- **verified** — real implementation, covered by a real (non-mocked) test, re-run as part of the full suite this phase.
- **verified-partial** — real implementation and test exist, but narrower in scope than the requirement's literal wording (the gap
  is named, not hidden).
- **not satisfied** — no real implementation for this requirement's substance, or none reachable from the outside world.
- **not executable in this environment** — real implementation, but verifying it needs infrastructure (Docker, a real browser) not
  available here.

## What changed since Phase 69 (the 7 gaps it left open)

| Gap | Phase 69 status | Now | Evidence |
|---|---|---|---|
| FR-1.41: 5 unwired routes | not satisfied | **1 of 5 wired** (`POST /experiments`, Phase 102) | `backend/app/experiments_runner.py`; `GET /anomalies`, `GET /behaviors/{node_id}`, `POST /simulation`, `POST /counterfactual` remain 501, each with a stated reason in its own route file |
| FR-1.42: 0 of 9 frontend screens | not satisfied | **3 of 9 built** (Phase 97, 99, 102) | `frontend/src/Explorer.tsx` (Topology Explorer), `Attribution.tsx` (Causal Analysis), `ExperimentLab.tsx` (Experiment Lab) |
| PERF-1..7: never benchmarked | not satisfied (deferred) | **still never run as a system-level acceptance benchmark** | see §3 below; several *component*-level real numbers exist (Phases 85/86/88/90/93) but none is a PERF-1..7 sign-off |
| SEC-5: no resource limits | not satisfied | **still open for `/capture`, `/simulation`, `/counterfactual`**; real limits now exist, but scoped only to `/experiments` | `backend/app/experiments_runner.py` (one job at a time, per-tenant hourly cap, `RunRejected` 429), Phase 102 |
| REL-11: large-dataset stress test | not executable here | **still never run** | no phase 70-107 runs one |
| SEC-8: auth/abuse protection | deliberately deferred | **partially built, opt-in, off by default** | `backend/app/auth/` (Phase 92, Bearer credentials + roles), `backend/app/tenancy/` (Phase 91, per-tenant isolation); both `auth_enabled`/`tenancy_enabled` default `False` (`backend/app/core/config.py`) |
| REPRO-5: 8 datasets generated on demand | verified-partial | **unchanged** | `simulator/scenarios/` + `experiments/synthetic_traffic.py`; Phase 106's reproducibility package re-runs the same suite, it does not check in standing fixtures |

Additionally found and fixed by this audit, not by any prior phase:

- **A missing phase-log entry.** `git log` has a real "Phase 87" commit (`fa2924e`, streaming dependency-strength/causal-candidate
  updates, `backend/dependency/streaming.py`) with no corresponding bullet in `docs/PROJECT_STATE.md` — the log itself had a gap.
  Backfilled in this audit with a real re-run of its benchmark and test suite (see the Phase 87 bullet now in `PROJECT_STATE.md`),
  not a fabricated entry.
- **NFR-7 partial regression.** Phase 69 stated "no module... exceeds ~500 lines except `docs/PROJECT_STATE.md`". That is no longer
  true: `experiments/matrix_runner.py` is now 995 lines and `scripts/validate_data_contracts.py` is 738 lines, grown across phases
  68-105 as more matrix/ablation/contract logic was added. Reported here as a partial regression (§2), not silently kept "verified".

## 1. Functional requirements

Rows unchanged from Phase 69 are marked so and not re-derived from scratch beyond a spot check that the cited file/test still
exists; only the FRs affected by phases 70-107 are re-verified in full detail.

| FR | Status | Implementation | Notes |
|---|---|---|---|
| FR-1.1 (ingest PCAP + controlled live capture) | verified-partial | `backend/nettrace/capture/ingest.py`, `simulator/capture/live.py` | Unchanged since Phase 69. Live `sniff()` against a real interface still never exercised (no Docker lab). |
| FR-1.2 (packet normalization) | verified | `backend/nettrace/normalize.py` | Unchanged. |
| FR-1.3 (bidirectional 5-tuple flows) | verified | `backend/nettrace/reconstruct.py` | Unchanged. |
| FR-1.4 (TCP state tracking) | verified | `backend/nettrace/reconstruct.py` | Unchanged. |
| FR-1.5 (UDP session modeling) | verified | `backend/nettrace/reconstruct.py` | Unchanged. |
| FR-1.6 (protocol fingerprinting) | verified | `backend/nettrace/fingerprint.py` | Unchanged. |
| FR-1.7 (encrypted-traffic metadata) | verified | `backend/nettrace/tls_metadata.py` | Unchanged. |
| FR-1.8 (per-flow features) | verified | `backend/flowmind/features/` | Unchanged. |
| FR-1.9 (nodes/edges from evidence only) | verified | `backend/nettrace/topology/` | `check_ground_truth_boundary` re-run clean this phase. |
| FR-1.10 (edge confidence/evidence/etc.) | verified | `backend/nettrace/topology/graph.py` | Unchanged. |
| FR-1.11 (probabilistic topology graph + comparison) | verified | `backend/nettrace/topology/graph.py`, `experiments/metrics/topology_comparison.py` | Unchanged. |
| FR-1.12 (reusable behavioral features) | verified | `backend/flowmind/features/`, `windows.py` | Unchanged. |
| FR-1.13 (per-node fingerprints) | verified | `backend/flowmind/fingerprints/node_fingerprint.py` | Unchanged. |
| FR-1.14 (role inference, calibrated) | verified-partial | `backend/flowmind/classification/role_classifier.py` | Still not reachable via `GET /behaviors/{node_id}` (still 501) — **unchanged since Phase 69**. Note: Phase 103's real-trace validation and Phase 105's drift study now both exercise this classifier for real (port-labeler agreement, longitudinal role-calibration-error tracking), which is additional real-world-adjacent evidence but does not change the API-reachability gap. |
| FR-1.15 (behavioral baseline) | verified | `backend/flowmind/baseline.py` | Unchanged. |
| FR-1.16 (anomaly vs. drift) | verified | `backend/flowmind/drift.py`/`drift/` | Unchanged. |
| FR-1.17 (multi-dimensional anomaly detection) | verified-partial | `backend/flowmind/anomaly/`, `backend/flowmind/anomaly/streaming.py` (Phase 86) | Still not reachable via `GET /anomalies` (still 501) — **unchanged since Phase 69**. A real streaming variant now exists (Phase 86) with a measured latency/quality tradeoff, but it is not wired either. |
| FR-1.18 (anomaly evidence) | verified | `backend/flowmind/anomaly/` | Unchanged. |
| FR-1.19 (FLOWMIND P/R/F1/FPR/FNR/latency) | verified | `experiments/metrics/anomaly_evaluation.py` | Unchanged; `anomaly_detection` still unscored in the matrix (Phase 42's own decision, restated). |
| FR-1.20 (time-indexed graph) | verified | `backend/archaeology/snapshots.py` | Unchanged. |
| FR-1.21 (versioned snapshots + diff) | verified | `backend/archaeology/snapshots.py`, `diff.py` | Unchanged. |
| FR-1.22 (behavioral evolution + timeline) | verified | `backend/archaeology/behavior_evolution.py`, `timeline.py` | Unchanged. |
| FR-1.23 (change attribution, no unsupported causal claims) | verified | `backend/archaeology/attribution.py` | Extended in spirit by Phase 99's causal attribution (Shapley over the 5 dependency signals, `backend/dependency/attribution.py`, reachable via `GET /causal/{id}/attribution`) and Phase 100's cited investigation reports (`POST /investigation/report`), both of which explicitly avoid claiming causation beyond what evidence supports. Original FR-1.23 scope unchanged. |
| FR-1.24 (historical investigation queries) | verified | `backend/app/api/routes/history.py` | Unchanged. |
| FR-1.25 (communication != dependency) | verified | `backend/dependency/communication.py` | Unchanged. |
| FR-1.26 (dependency strength) | verified | `backend/dependency/strength.py`; real-time variant `backend/dependency/streaming.py` (Phase 87, checked equivalent to batch to floating-point rounding, re-verified this phase) | Unchanged in scope; a streaming implementation now exists but is not wired to any route. |
| FR-1.27 (temporal precedence, no causation-from-correlation) | verified | `backend/dependency/temporal_precedence.py`, `causal_candidates.py` | Unchanged. |
| FR-1.28 (multi-order impact graph) | verified | `backend/dependency/failure_propagation.py` | Unchanged. |
| FR-1.29 (graph criticality metrics) | verified | `backend/dependency/criticality.py` | Unchanged. |
| FR-1.30 (causal evidence report) | verified | `backend/dependency/causal_evidence.py` | Unchanged; Phase 100's investigation report and Phase 101's root-cause ranking both build on this report rather than replacing it. |
| FR-1.31 (digital twin build + sync) | verified | `backend/digital_twin/` | Phase 88 added a continuous sync **daemon** (`backend/digital_twin/daemon.py`) with a measured backpressure/rate-limit/coalescing behavior; it is a superset capability, not wired to the API, and does not change this FR's already-"verified" status. |
| FR-1.32 (controlled failure injection) | verified | `backend/simulation/failure_injection.py` | Unchanged. |
| FR-1.33 (paths/costs/route changes/disconnection) | verified | `backend/simulation/path_engine.py` | Unchanged. |
| FR-1.34 (connected failure->routing->service pipeline) | verified | `backend/simulation/failure_propagation_pipeline.py` | Unchanged; reused unmodified by Phase 101's root-cause ranking and Phase 105's drift study. |
| FR-1.35 (resilience indicators) | verified | `backend/simulation/resilience_indicators.py` | Phase 89 added a real-time monitoring daemon (`backend/simulation/resilience_monitor.py`) reusing these formulas; not wired to any route. Status unchanged. |
| FR-1.36 (counterfactual scenario language) | verified | `backend/app/models/simulation.py` | Unchanged; `validate_data_contracts` re-run clean this phase (55/55). |
| FR-1.36/1.37 (isolated execution + comparison) | verified-partial | `backend/simulation/counterfactual_engine.py`, `counterfactual_comparison.py` | Still not reachable via `POST /counterfactual` (still 501) — **unchanged since Phase 69**. `POST /counterfactual/ask` (Phase 98, natural-language) and `POST /investigation/root-cause` (Phase 101) both call the real engine directly and ARE reachable, so the underlying engine is exercised through the API for two specific use cases even though the generic `POST /counterfactual` endpoint itself is not. |
| FR-1.38 (predictions vs. real experiment outcomes) | verified | `experiments/metrics/failure_propagation_validation.py`, `counterfactual_validation.py` | Unchanged. |
| FR-1.39 (experiment recommendations) | verified | `backend/dependency/experiment_recommendations.py` | Unchanged. |
| FR-1.40 (full experimental matrix + ablations) | verified | `experiments/matrix_runner.py` | Extended substantially: Phase 72 (multi-seed variance), 74 (low-volume sweep), 75 (run versioning), 82 (constant calibration), 104 (formal significance testing), 105 (longitudinal drift study, an evolving-topology variant of the matrix) all build on this module for real. Status remains verified; see NFR-7 note above re: file size. |
| FR-1.41 (12 versioned, typed API endpoints) | verified-partial | `backend/app/api/router.py`, `routes/*.py` | **Changed since Phase 69**: 8 of 12 route groups are now real (was 7 of 12); `POST /experiments` wired Phase 102. `GET /anomalies`, `GET /behaviors/{node_id}`, `POST /simulation`, `POST /counterfactual` remain 501, each with an explicit reason in its own file (read this phase, quoted in the "What changed" table above). This remains the largest concrete gap. |
| FR-1.42 (frontend: 9 required screens) | verified-partial | `frontend/src/*.tsx` | **Changed since Phase 69**: was "not satisfied" (0 screens); now 3 of 9 real screens exist — Topology Explorer (`Explorer.tsx`, Phase 97, with snapshot time-travel and diff overlay), Causal Analysis (`Attribution.tsx`, Phase 99), Experiment Lab (`ExperimentLab.tsx`, Phase 102). Overview, Node Investigation, Timeline (as a dedicated screen), Anomaly Investigation, Simulation, and Counterfactual screens still do not exist. Upgraded from "not satisfied" to "verified-partial" because a real, working, API-backed subset now exists — not because the requirement is close to done. |

## 2. Non-functional requirements

| NFR | Status | Notes |
|---|---|---|
| NFR-1 (modular, testable stages) | verified | Every new subsystem since Phase 69 (tenancy, auth, HA replication, telemetry, NetFlow ingestion, SDKs, streaming variants) is its own module/package with its own test file(s); still true. |
| NFR-2 (typed interfaces) | verified-partial | Backend Pydantic models: `validate_data_contracts` 55/55, re-run this phase. Frontend TypeScript: now real and used (`frontend/src/api.ts`, `labApi.ts`, `.tsx` components are typed), closing the "N/A" half of Phase 69's verdict for the 3 screens that exist; still N/A for the 6 screens that don't. |
| NFR-3 (determinism) | verified | Exercised throughout, including Phase 104's seeded bootstrap and Phase 105's seeded topology evolution, both checked deterministic by their own tests. |
| NFR-4 (no hardcoded paths/magic numbers) | verified | `backend/app/core/config.py` grew substantially (tenancy, auth, HA, experiment-run limits) but every new field remains a named, documented `Settings` field, not a literal. Spot-checked this phase. |
| NFR-5 (structured logging) | verified | Unchanged; Phase 94 added OpenTelemetry spans/metrics on top (`backend/app/core/telemetry.py`), a superset. |
| NFR-6 (versioned APIs) | verified | Unchanged (`APIRouter(prefix="/api/v1")`). |
| NFR-7 (no global state / circular imports / giant files) | **verified-partial (regressed)** | `check_ground_truth_boundary` (import-boundary guard) re-run clean this phase. But the "no file exceeds ~500 lines" claim from Phase 69 no longer holds: `experiments/matrix_runner.py` is 995 lines and `scripts/validate_data_contracts.py` is 738 lines. Neither is broken or untested, but both have grown past the bar Phase 69 itself used to call this "verified". Named honestly rather than silently kept "verified" as in Phase 69. Not split in this phase: doing so is a refactor, not an audit finding. |
| NFR-8 (no hardcoded topology/classification) | verified | Unchanged; still enforced structurally via the ground-truth boundary. |
| NFR-9 (no overengineering/unjustified infra) | verified-partial | Still no database/cache/queue anywhere. Phase 93's HA replication (`docker-compose.ha.yml`, replicated artifact roots) and Phase 90's multi-collector capture add real infrastructure-adjacent code; both are explicitly scoped, documented, and not wired into the default single-process path — a judgment call, not a violation, but worth naming since NFR-9 is exactly the rule that would flag unjustified infrastructure. |

## 3. Performance requirements

| PERF | Status | Notes |
|---|---|---|
| PERF-1..7 | **not satisfied** | Still never run as a system-level acceptance benchmark through Phase 107. Real, honestly-reported *component*-level numbers now exist for individual not-yet-wired subsystems: Phase 85 incremental topology (5.4-9.6x speedup vs full rebuild), Phase 86 streaming anomaly detection (small topology keeps up at 200-100,000 pps, large topology does not keep up at any tested rate), Phase 88 twin-sync (large topology ~1.9-2.3s/sync, falls behind a fast producer), Phase 90 multi-collector cost scaling, Phase 93 HA failover latency. None of these substitutes for a PERF-1..7 sign-off on the shipped, wired pipeline, which still does not exist. |
| PERF-8 (no scalability claim without a benchmark) | verified | Every performance number found in `docs/PROJECT_STATE.md` since Phase 69 is attached to a specific, cited benchmark run; no unbacked scalability claim was found in this pass. |

## 4. Reliability requirements

| REL | Status | Notes |
|---|---|---|
| REL-1..10, REL-12 | verified | Unchanged since Phase 69; re-run as part of the full suite this phase. |
| REL-11 (very large datasets degrade, not crash) | **not executable in this environment** | Still never run through Phase 107. Same gap as Phase 69. |

## 5. Security requirements

| SEC | Status | Notes |
|---|---|---|
| SEC-1 (validate all external input) | verified | Unchanged; every new route (experiments, investigation, root-cause) uses Pydantic bodies and constrained query/path params, checked this phase. |
| SEC-2 (no shell=True) | verified | Unchanged; re-grepped this phase, still only `simulator/ground_truth/cli.py`'s list-argument `docker` calls. |
| SEC-3 (uploaded file validation) | verified | Unchanged. |
| SEC-4 (path traversal) | verified | Unchanged; `CAPTURE_ID_PATTERN` reused correctly by every route added since Phase 69 (checked `investigation.py`, `experiments.py`, `causal.py` this phase). |
| SEC-5 (resource limits) | **not satisfied** | Still open for `POST /capture`, `POST /simulation`, `POST /counterfactual` (the latter two also still 501, so the question is moot until they're wired). Phase 102 added a real, tested limiter (one job at a time, per-tenant hourly cap, 429 + `Retry-After`) but scoped only to `POST /experiments`. Not generalized to the other routes in this phase — doing so with unbenchmarked thresholds would repeat the exact mistake Phase 69 declined to make. |
| SEC-6 (authorized capture interfaces only) | verified | Unchanged. |
| SEC-7 (no secrets committed) | verified | Re-grepped this phase (common key patterns, `.env*`); nothing found; `.gitignore` still excludes `.env*`. |
| SEC-8 (auth / API-abuse protection) | **verified-partial (changed since Phase 69)** | Was "deliberately deferred". Now real: `backend/app/auth/` (Phase 92) enforces Bearer credentials with roles (reader/operator), expiry and revocation, on every `/api/v1` route (401/403) when `auth_enabled=true`; `backend/app/tenancy/` (Phase 91) enforces per-tenant isolation via `X-Tenant-Key` when `tenancy_enabled=true`. Both are real, tested (cross-tenant reads 404, invalid/missing credentials rejected), and **off by default** (`backend/app/core/config.py`), so an out-of-the-box deployment is still unauthenticated. No general API-abuse rate limiting exists beyond Phase 102's experiment-run limiter, and there is no audit logging or credential rotation. Upgraded from "deferred" to "verified-partial" because real, working, tested mechanisms now exist — not because SEC-8 is closed. |

## 6. Reproducibility requirements

| REPRO | Status | Notes |
|---|---|---|
| REPRO-1 (experiment record fields) | verified | Unchanged; `Experiment` model still requires every field with no default. |
| REPRO-2 (rerunnable, equivalent given same seed) | verified | Unchanged; Phase 106's reproducibility package (`repro/run.sh`, `scripts/run_reproducibility_check.py`) now formalizes this as a one-command check against a committed `repro/expected_results.json`, a real strengthening of this requirement's evidence, though it re-runs the same suite rather than independently re-deriving results (its own stated limit). |
| REPRO-3 (ground truth versioned + hashed) | verified | Unchanged. |
| REPRO-4 (ground truth never an inference input) | verified | `check_ground_truth_boundary` re-run clean this phase, including all files added in phases 70-107. |
| REPRO-5 (8 named datasets: description/procedure/truth/properties/version/checksum) | verified-partial | Unchanged since Phase 69: still generated on demand by `simulator/scenarios/` + `experiments/synthetic_traffic.py`, not checked in as standing fixtures. Phase 103's real-trace validation harness adds a *different* kind of dataset (user-supplied real pcaps) that is explicitly out of scope for REPRO-5's synthetic-dataset list. |

## Summary

- **42 FRs**: 32 verified (unchanged), 9 verified-partial (was 8 — FR-1.42 moved from "not satisfied" into this bucket), 1 remaining
  gap counted once against FR-1.41 itself (4 of 5 routes still unwired; each backing FR — 1.14, 1.17, 1.36/1.37 — separately marked
  verified-partial as it was in Phase 69).
- **9 NFRs**: 6 verified, 3 verified-partial (NFR-2 improved by real frontend typing; NFR-7 named as a partial regression — file-size
  growth; NFR-9 named for judgment-call infra additions, not a violation).
- **8 PERFs**: 7 not satisfied (unchanged), 1 (PERF-8) verified.
- **12 RELs**: 11 verified, 1 not executable in this environment (REL-11, unchanged).
- **8 SECs**: 6 verified, 1 not satisfied (SEC-5, unchanged in substance), 1 verified-partial (SEC-8, upgraded from "deferred" —
  real mechanisms now exist, off by default).
- **5 REPROs**: 4 verified, 1 verified-partial (unchanged).

Net change since Phase 69: **2 gaps partially closed with real, working code** (FR-1.41's `POST /experiments`, FR-1.42's 3 of 9
screens), **1 gap partially mitigated by a different, opt-in mechanism** (SEC-8), **1 documentation gap found and fixed** (the
missing Phase 87 log entry), **1 new partial regression named** (NFR-7 file-size growth), and **4 gaps unchanged**
(PERF-1..7, SEC-5 for capture/simulation/counterfactual, REL-11, REPRO-5).

## What this phase deliberately did not do

- Did not wire the remaining 4 routes (`GET /anomalies`, `GET /behaviors/{node_id}`, `POST /simulation`, `POST /counterfactual`) —
  each is a meaningful integration-work chunk in its own right, same reasoning Phase 69 gave.
- Did not build the remaining 6 frontend screens.
- Did not fabricate PERF-1..7 numbers or a REL-11 large-dataset run.
- Did not generalize SEC-5 resource limits to `/capture` with unbenchmarked, made-up thresholds.
- Did not enable `auth_enabled`/`tenancy_enabled` by default — that is a deployment decision for whoever operates this system, not
  something an audit phase should flip silently.
- Did not split `experiments/matrix_runner.py` or `scripts/validate_data_contracts.py` — refactoring is out of scope for a
  verification pass; the finding is named so it can be planned as real work.
- Did not cut a git tag or push anything. `VERSION` and `docs/RELEASE_NOTES.md` (this phase's release artifacts) state the honest,
  partial-completion status; tagging the actual release is left to the project owner, consistent with this session's practice of
  not committing or tagging without being asked.

See `docs/LIMITATIONS.md` (reconciled this phase) and `docs/acceptance_testing.md` (Phase 69's original audit, kept as historical
record) for further detail.
