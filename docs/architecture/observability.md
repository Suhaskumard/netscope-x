# NETSCOPE-X — Observability Framework

Phase 07 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 07 — OBSERVABILITY
FRAMEWORK"). Implements NFR-5 from `docs/requirements/system_requirements.md`: structured logs,
request IDs, experiment IDs, module-level logging, error reporting, and performance timing.

Code lives in `backend/app/core/`: `context.py`, `logging.py`, `timing.py`. Verified by
`backend/tests/test_observability.py` (10 tests, all passing — see the Phase 07 completion report for
the actual run output) and wired into the Phase 06 placeholder app (`backend/app/main.py`) via an ASGI
middleware, so this was exercised over a real in-process HTTP request, not just unit-tested in
isolation.

## 1. Structured logs

`backend/app/core/logging.py`'s `JsonFormatter` renders every log record as a single-line JSON object:
`timestamp` (UTC ISO-8601), `level`, `logger` (the module name), `message`, `request_id`,
`experiment_id`, and any `extra_fields` passed by the caller (e.g., `operation`, `duration_ms`,
`status_code`). Example, captured from an actual `/health` request in this session:

```json
{"timestamp": "2026-09-17T17:28:28.936129+00:00", "level": "INFO", "logger": "backend.app.main",
 "message": "request started: GET /health", "request_id": "cbbed8be6b364bfbb30ce6ca589d8508",
 "experiment_id": null}
```

Choosing JSON-per-line (not human-formatted text) is deliberate: it's directly greppable/parseable by
any log aggregation tool without a custom parser, and it's the same format regardless of which module
emits it — there is exactly one log format in the whole system.

## 2. Request IDs

`backend/app/core/context.py`'s `request_id_var` (a `contextvars.ContextVar`) holds the current
request's ID. `request_context()` is a context manager that generates a new UUID4 hex ID (or accepts
one) and binds it for the duration of the `with` block, restoring the previous value afterward. The
middleware in `backend/app/main.py` wraps every incoming HTTP request in `request_context()`, so every
log line emitted anywhere during that request's handling — including in nested function calls that
never explicitly receive a request ID — automatically carries it. The middleware also echoes the ID
back as an `X-Request-ID` response header, so a client (or a browser dev-tools inspection during later
frontend testing phases) can correlate a specific HTTP response with its exact server-side log lines.

## 3. Experiment IDs

`experiment_id_var` and `experiment_context(experiment_id)` work identically to the request-ID
mechanism, but are bound around an experiment's execution rather than an HTTP request (spec §20
reproducibility: every experiment run should be traceable through logs by its `experiment_id`, which
matches the `Experiment.experiment_id` field already defined in the Phase 04 data contracts). This
will be used starting in Phase 68's experiment-runner code — no experiment-running code exists yet, so
this phase only proves the context-propagation mechanism itself (`test_experiment_context_sets_and_restores`).

## 4. Module-level logging

`get_logger(name)` is the single entry point every module should use — always called as
`get_logger(__name__)` so log output is attributable to its actual source module (e.g.,
`backend.app.main`, and later `nettrace.flows`, `flowmind.anomaly`, etc.), never logged through the
bare root logger. `get_logger` also lazily calls `configure_logging()` (idempotent — safe to call from
many modules; only configures the root handler once), so any module can start logging immediately
without a separate app-startup-ordering dependency.

## 5. Error reporting

`log_exception(logger, message, **extra_fields)` logs at ERROR level with `exc_info=True`, so the
`JsonFormatter` includes a full `exception` field (type, message, stack trace) in the same structured
JSON format as every other log line — there is no separate "crash log" format or bare
`traceback.print_exc()` path anywhere in the framework. Any module can call
`logger.exception(...)`/`log_exception(...)` from within an `except` block and get the same structured
output.

## 6. Performance timing

`backend/app/core/timing.py` provides two forms:
- `Timer(operation, logger=...)` — a context manager; `with Timer("flow_reconstruction"): ...` measures
  wall-clock duration via `time.perf_counter()` and logs `{"operation": ..., "duration_ms": ...}` on
  exit.
- `@timed(operation=None)` — a decorator form for timing an entire function call, defaulting the
  operation name to the function's qualified name.

This is the concrete mechanism the future PERF-1..7 measurements (packet processing throughput, flow
processing time, graph construction time, API latency, etc. — `docs/requirements/system_requirements.md`)
will be built on: every pipeline stage wraps its work in a `Timer`/`@timed`, and the resulting
structured `duration_ms` fields are what later phases aggregate into actual benchmark numbers — not
estimated or asserted.

The middleware in `backend/app/main.py` already times every HTTP request end-to-end as a live example.

## Verification performed this phase

- `pytest backend/tests/test_observability.py` — 10/10 passed, covering: request-context set/restore,
  context propagation into a nested function without explicit passing, experiment-context set/restore,
  module-logger naming, JSON-formatter validity and required fields, a real logging call through the
  context filter, exception capture with stack trace, `Timer` producing a non-negative duration,
  `@timed` preserving a wrapped function's return value, and a full FastAPI `TestClient` request to
  `/health` asserting both the `X-Request-ID` response header and a matching structured log record.
- `pytest backend/tests` (full suite, 13 tests including the Phase 06 environment smoke tests) — all
  passed, confirming no regression.
- Manually invoked the app in-process and visually inspected the emitted JSON log lines (shown above)
  to confirm the format is actually what this document claims, not merely what the code intends.

## Known limitations

- No log shipping / aggregation backend (e.g., to a file, ELK, or a cloud log service) is configured —
  logs currently go to stdout only, which is sufficient for local development and Docker `docker logs`
  but will need revisiting if/when the system runs somewhere logs need central collection. Not decided
  now, per spec §6's "choose the minimum... necessary" principle — no infrastructure added without a
  concrete need.
- `request_context()`/`experiment_context()` rely on Python's `contextvars`, which correctly propagate
  across `await` points within a single async task (verified via the `TestClient` integration test)
  but do NOT automatically propagate across a manually spawned thread or process — any future
  multiprocessing/worker code (e.g., Phase 21+ capture workers) will need to explicitly pass and
  re-bind the IDs across that boundary; this is a known constraint, not yet encountered because no such
  code exists yet.

## Status

This document, together with `backend/app/core/{context,logging,timing}.py` and
`backend/tests/test_observability.py`, satisfies Phase 07: structured logs, request IDs, experiment
IDs, module-level logging, error reporting, and performance timing are all implemented and verified by
actually running the test suite and the app itself (not asserted without execution, per spec Rule 2).
