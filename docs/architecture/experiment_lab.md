# Experiment Lab and live experiment runs (Phase 102)

## Frontend (`?view=experiments`, `frontend/src/ExperimentLab.tsx`, `labApi.ts`)
Lists recorded experiments and shows, for the selected one, the Section 12 areas: experiment, hypothesis, setup, result, metrics and
a comparison against another run. All values are what `GET /experiments/{id}` returns from the persisted record. The record has no
hypothesis field, so the Hypothesis section says "Not recorded" rather than inventing one. A run form (whitelisted selects) starts a
run and shows live progress. The stream is read with `fetch`, not `EventSource`, so the bearer token and tenant header still apply.

## `POST /experiments` (was a 501 stub since Phase 68)
Runs the real `run_and_persist_cell`, so the result is the same persisted record a batch run writes. Safety scope:
- Off unless `NETSCOPE_ENABLE_EXPERIMENT_RUNS=true` (403).
- Whitelist only: topology level, completeness level, ablation and seed 0..999, all validated against `experiments.matrix_runner`
  (422). No arbitrary configuration or paths.
- One run at a time process-wide, and `NETSCOPE_EXPERIMENT_RUNS_PER_HOUR` (default 5) per tenant in a sliding hour; both give 429 with
  `Retry-After`.
- Jobs and their events are tenant-scoped (another tenant gets 404). Job errors report the exception class only.

## Progress streaming
`GET /experiments/jobs/{id}/events` is SSE: `queued`, `started`, `progress` (elapsed-seconds heartbeat every 2 s), then `done` or
`error`; `Last-Event-ID` replays. Progress is coarse by design: the runner is a single blocking call with no internal hooks, so no
per-stage percentage is claimed.

## Verified
`backend/tests/test_experiment_runs.py`: disabled -> 403; a real run streams queued/started/done, persists, appears in the list and
detail equals the stored record; a second concurrent run gets 429; rate limit; whitelist and id validation; compare deltas equal the
stored metrics; tenant isolation. `npm run build` (tsc) passes. Against a live uvicorn + Vite proxy, a run was started, streamed to
`done` and listed.

## NOT verified
The React UI was not exercised in a browser (the Chrome extension was not connected in this session); only its type check/build and
the HTTP flow it uses were verified.

## Limits
Job state is in memory and per process (lost on restart, not shared between workers). Only single cells, not the full matrix.
