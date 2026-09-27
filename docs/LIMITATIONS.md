# NETSCOPE-X — Known Limitations

Phase 69 deliverable (spec §"PHASE 69 — FINAL HARDENING AND RELEASE" documentation set), reconciled by
the Phase 108 final cross-phase acceptance audit. Consolidates every limitation accumulated across
Phases 1-108, each cross-referenced to where it was first documented, so nothing is silently dropped or
claimed resolved when it isn't. See `docs/acceptance_testing_phase108.md` for the current
requirement-by-requirement verification this list is drawn from (`docs/acceptance_testing.md` is the
original Phase 69 pass, kept as historical record).

## Environment constraints (this development session)

- **No Docker.** No phase from 21 onward has had access to a running Docker daemon. Every Docker-lab
  dependent capability (real live packet capture, `scripts/validate_observatory`, real multi-container
  traffic generation, the `docker-compose.yml` dev containers) has real, unit-tested code but has never
  been exercised end-to-end against the actual lab. First noted Phase 21
  (`docs/architecture/packet_capture.md`), restated at Phases 32, 36, 37, 63, and again here.
- **No Chrome/Playwright browser.** The spec's §18 frontend testing (real-browser navigation,
  rendering, interaction) cannot run in this session. This is compounded by FR-1.42 below: there is
  currently no built frontend feature UI to test against even if a browser were available.
- Both of the above mean spec Phase 69's "network testing" and "frontend testing" sections are
  addressed here as documented gaps, not fabricated pass/fail results.

## Real, unresolved product gaps (not environment-caused)

- **FR-1.42 — only 3 of 9 frontend screens exist.** `frontend/` had only the Phase 06 placeholder
  scaffold through Phase 96. Phases 97/99/102 built real, API-backed screens for Topology Explorer
  (`Explorer.tsx`), Causal Analysis (`Attribution.tsx`), and Experiment Lab (`ExperimentLab.tsx`).
  Overview, Node Investigation, Timeline (as its own screen), Anomaly Investigation, Simulation, and
  Counterfactual still do not exist. Re-verified Phase 108 — see `docs/acceptance_testing_phase108.md`.
- **4 of 12 API route groups are unwired** (was 5 through Phase 101). `GET /anomalies`,
  `GET /behaviors/{node_id}`, `POST /simulation`, and `POST /counterfactual` all raise
  `NotYetImplemented` (501) even though their backing computation (anomaly detection, role
  classification, failure injection, and counterfactual execution respectively) is real and unit
  tested. `POST /experiments` was wired Phase 102 (`backend/app/experiments_runner.py`, opt-in,
  rate-limited). See `docs/acceptance_testing_phase108.md` FR-1.41 row for the current list and reasoning.
- **SEC-5 — no resource limits on `/capture`, `/simulation`, `/counterfactual`.** Still open through
  Phase 108. Phase 102 added a real limiter, but scoped only to `POST /experiments` (one job at a
  time, per-tenant hourly cap). Not generalized: choosing real limits for the other routes without a
  load-testing basis would itself be an unjustified magic number (NFR-4/NFR-9).
- **NFR-7 — two files have grown past the ~500-line bar Phase 69 used.** `experiments/matrix_runner.py`
  (995 lines) and `scripts/validate_data_contracts.py` (738 lines), grown across phases 68-105 as
  matrix/ablation/contract logic accumulated. Neither is broken or untested; named honestly by the
  Phase 108 audit rather than kept silently "verified". Not split in Phase 108 (a refactor, not an
  audit finding).

## Deliberately deferred (a documented decision, not an oversight)

- **PERF-1 through PERF-7 — no system-level benchmarking has been run.** FR-1.40's own phase note
  (Phase 68) explicitly defers this: "PERF-1..8 benchmarking and provisional-constant recalibration are
  explicitly deferred (FR-1.40 asks to measure, not tune)." Still true through Phase 107. Real,
  component-level numbers now exist for several not-yet-wired subsystems (Phase 85 incremental
  topology, 86 streaming anomaly detection, 88 twin-sync daemon, 90 multi-collector capture, 93 HA
  failover) but none is a system-level PERF-1..7 sign-off on the shipped, wired pipeline.
- **REL-11 — large-dataset degradation is untested.** Ties directly to the PERF deferral above; no
  large-scale run has been attempted through Phase 107.
- **SEC-8 — auth/API-abuse protection exists but is opt-in, off by default.** Was fully deferred
  through Phase 90. Phase 91 (`backend/app/tenancy/`) and Phase 92 (`backend/app/auth/`) built real,
  tested Bearer-credential auth and per-tenant isolation, but both `auth_enabled` and
  `tenancy_enabled` default to `False` (`backend/app/core/config.py`), so a default deployment is
  still unauthenticated; there is no general API-abuse rate limiting beyond Phase 102's
  experiment-run limiter, and no audit logging or credential rotation.
- **`anomaly_detection` is unscored in the Phase 68 experimental matrix**, per Phase 42's own decision
  not to build a synthetic anomaly-injection dataset (a "separate, much larger capability nobody has
  asked for" — `experiments/metrics/anomaly_evaluation.py`'s own docstring).
- **`causal_analysis` measured 0.0 accuracy across every cell of the Phase 68 matrix run.** Traced to
  the synthetic traffic generator (`experiments/synthetic_traffic.py`) producing no genuine
  time-lagged cross-correlation structure for Phase 52's temporal-precedence gate to detect. This is a
  limitation of the *synthetic data*, not a defect in Phases 50-53's causal-candidate logic — see
  `docs/architecture/experimental_matrix.md`.
- **REPRO-5's 8 named datasets are generated on demand, not checked in as standing fixtures.** The
  generation mechanism (`simulator/scenarios/` + `experiments/synthetic_traffic.py`) satisfies the
  requirement's substance; no `_small/_medium/.../_noisy` fixture files are committed to the repo.

## Accepted, low-severity risk

- `npm audit`: one moderate advisory (`GHSA-67mh-4wv8-2f99`, esbuild via vite@5.4.x) affecting only the
  local Vite dev server, not the production build. First noted Phase 06
  (`docs/development/environment.md`); fixing it requires a breaking `vite@8` upgrade not undertaken
  in any phase to date.

## Fixed this phase (listed for traceability, not an open item)

- REL-12 (unavailable capture interface): `simulator/capture/live.py`'s `sniff()` call previously let
  a raw `OSError` crash the caller; now wrapped in a structured `InterfaceUnavailableError`.
- SEC-4 (path traversal): `GET /flows`, `/topology`, `/dependencies`, `/history`, `/causal/{id}`
  previously accepted an unconstrained `capture_id` string used directly as a filesystem path segment;
  now constrained by `CAPTURE_ID_PATTERN`.
