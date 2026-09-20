# NETSCOPE-X — Known Limitations

Phase 69 deliverable (spec §"PHASE 69 — FINAL HARDENING AND RELEASE" documentation set). Consolidates
every limitation accumulated across Phases 1-69, each cross-referenced to where it was first
documented, so nothing is silently dropped or claimed resolved when it isn't. See
`docs/acceptance_testing.md` for the full requirement-by-requirement verification this list is drawn
from.

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

- **FR-1.42 — no frontend feature UI exists.** `frontend/` remains the Phase 06 placeholder scaffold
  (`App.tsx`, `main.tsx`) through Phase 68. None of the 9 required screens (Overview, Topology
  Explorer, Node Investigation, Timeline, Anomaly Investigation, Causal Analysis, Simulation,
  Counterfactual, Experiment Lab) has been built. All 68 prior phases focused on backend/research
  plumbing; frontend was never picked up as a phase's scope in this run.
- **5 of 12 API route groups are unwired.** `GET /anomalies`, `GET /behaviors/{node_id}`,
  `POST /simulation`, `POST /counterfactual`, and `POST /experiments` all raise `NotYetImplemented`
  (501) even though their backing computation (anomaly detection, role classification, failure
  injection, counterfactual execution, and experiment construction respectively) is real and unit
  tested. See `docs/acceptance_testing.md` FR-1.41 row for the full list and reasoning for why this
  phase did not wire them.
- **SEC-5 — no resource limits.** `POST /capture`, `POST /simulation`, and `POST /counterfactual` have
  no request size limit, timeout, or concurrency cap. Not fixed this phase: choosing real limits
  without a load-testing basis would itself be an unjustified magic number (NFR-4/NFR-9).

## Deliberately deferred (a documented decision, not an oversight)

- **PERF-1 through PERF-7 — no benchmarking has been run.** FR-1.40's own phase note (Phase 68)
  explicitly defers this: "PERF-1..8 benchmarking and provisional-constant recalibration are
  explicitly deferred (FR-1.40 asks to measure, not tune)." No throughput, latency, memory, or
  render-time number appears anywhere in this repository's docs, and none should be trusted if it
  ever does without a citation to a real benchmark run.
- **REL-11 — large-dataset degradation is untested.** Ties directly to the PERF deferral above; no
  large-scale run has been attempted.
- **SEC-8 — no authentication/API-abuse protection.** Documented as an explicit, revisitable decision
  in `docs/requirements/system_requirements.md` since Phase 03: the current scope is a controlled
  lab/local-research context.
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
