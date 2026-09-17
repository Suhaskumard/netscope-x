# NETSCOPE-X — API Architecture

Phase 09 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 09 — API ARCHITECTURE" and
§"API DESIGN PRINCIPLES"). Code: `backend/app/api/`. Verified by `backend/tests/test_api.py` (18
tests, all passing).

## Scope: real contracts, honest "not implemented yet"

Every endpoint below is a real, routed, validated FastAPI endpoint — request bodies and query
parameters are genuinely parsed and validated by Pydantic, and the generated OpenAPI schema documents
every one of them. None of them yet return real data, because the pipeline stages that would produce
that data (NETTRACE, FLOWMIND, Archaeology, Causal, PathForge, Counterfactual, Experiments) start at
Phase 21. Every handler raises `NotYetImplemented`, which the error-handling layer converts into a
structured `501 Not Implemented` response — this is the honest state, not a fabricated one (spec Rule
2/3: never fabricate execution, never disguise mock data as real output).

## Cross-cutting design

- **Versioning** (NFR-6): every domain route is mounted under `/api/v1` (`backend/app/api/router.py`).
  `/health` stays unversioned as an infra-level endpoint, not a domain one.
- **Consistent errors**: exactly one error shape, `ErrorResponse {error, detail, request_id}`
  (`backend/app/api/schemas.py`), used for all three failure modes registered in
  `backend/app/api/errors.py`:
  - `NotYetImplemented` → 501, `error="not_implemented"`.
  - `RequestValidationError` (Pydantic input validation failure) → 422, `error="validation_error"` —
    re-rendered in the same envelope instead of FastAPI's default `{"detail": [...]}` shape, so a
    client never has to branch on two different error formats.
  - Any unhandled `Exception` → 500, `error="internal_error"`. The real exception is logged with full
    detail via `backend.app.core.logging.log_exception` (Phase 07), but the client response never
    contains the raw exception text or a stack trace — only a generic message and the `request_id` for
    support correlation (spec: "avoid leaking internal exceptions").
- **Pagination**: `PageParams`/`PaginatedResponse[T]` (`backend/app/api/schemas.py`) used by every
  list-shaped endpoint (`/flows`, `/anomalies`, `/history`, `/dependencies`, `/experiments`,
  `/metrics`) — `limit` (1-500, default 50) and `offset` (>=0, default 0) as validated query params.
- **Typed schemas**: every request/response type is a real Pydantic model. Where a Phase 04 data
  contract already fits an endpoint's shape, it's reused directly (e.g. `GET /topology` →
  `TopologyGraph`) rather than duplicated — this is the same "single source of truth for cross-module
  data shapes" principle from `docs/architecture/data_contracts.md`.

## Endpoint reference

| Method | Path | Request | Response (on success, once implemented) | Backing phase |
|---|---|---|---|---|
| POST | `/api/v1/capture` | `CaptureRequest` (capture.py-local) | `CaptureAccepted` (202) | Phase 21 |
| GET | `/api/v1/flows?capture_id=...` | query + `PageParams` | `PaginatedResponse[Flow]` | Phase 23 |
| GET | `/api/v1/topology?capture_id=...` | query | `TopologyGraph` | Phase 32 |
| GET | `/api/v1/behaviors/{node_id}` | path param | `NodeBehavior` (fingerprint + role, behaviors.py-local) | Phase 35-37 |
| GET | `/api/v1/anomalies?node_id=...` | query + `PageParams` | `PaginatedResponse[Anomaly]` | Phase 40-41 |
| GET | `/api/v1/history?start=...&end=...` | query + `PageParams` | `PaginatedResponse[GraphChangeEvent]` | Phase 49 |
| GET | `/api/v1/dependencies?capture_id=...` | query + `PageParams` | `PaginatedResponse[DependencyEdge]` | Phase 51 |
| GET | `/api/v1/causal/{dependency_id}` | path param | `CausalEvidenceReport` | Phase 56 |
| POST | `/api/v1/simulation` | `FailureScenario` | `SimulationRun` (202) | Phase 59-61 |
| POST | `/api/v1/counterfactual` | `CounterfactualScenario` | `CounterfactualScenario` (202) | Phase 64-66 |
| GET/POST | `/api/v1/experiments` | `PageParams` / `Experiment` | `PaginatedResponse[Experiment]` / `Experiment` (202) | Phase 67-68 |
| GET | `/api/v1/metrics?context=...` | query + `PageParams` | `PaginatedResponse[MetricResult]` | Phase 68 |

Every row's FR traceability: FR-1.41 (spec Phase 09 API surface) plus the specific FR for that
pipeline stage, listed in `docs/requirements/system_requirements.md` §1.

## Known simplifications (explicitly not hidden)

- `POST /counterfactual` and `POST /simulation` currently accept the full domain object
  (`CounterfactualScenario`/`FailureScenario`) as the request body, including fields a real
  implementation might assign server-side (e.g. IDs). A dedicated slimmer "create" request DTO may be
  introduced alongside the real implementation in Phase 59-66 if server-side ID assignment is adopted
  — noted here rather than presented as a final design.
- `CaptureRequest`/`CaptureAccepted` and `NodeBehavior` are endpoint-local schemas (not in
  `backend/app/models`) because they don't correspond to a single Phase 04 domain object — this is a
  deliberate choice, not an oversight: API-shape concerns (what a client posts to start a capture)
  are kept separate from domain data contracts (what a packet/flow/node *is*).
- No authentication/authorization is implemented on any route yet, consistent with SEC-8's deferred
  status (`docs/requirements/system_requirements.md`) — this remains a controlled-lab/local-research
  tool for now.

## Verification performed this phase

- `pytest backend/tests/test_api.py` — 18/18 passed: all 12 endpoint groups return a structured 501
  with a `request_id` matching the `X-Request-ID` response header; a malformed `POST /capture` body
  and a missing required query param on `GET /flows` both return the same 422 `ErrorResponse` envelope
  (not FastAPI's raw default format); the generated OpenAPI schema documents all 12 required paths;
  `/health` remains unaffected.
- `pytest backend/tests` (full suite, 40 tests) — all passed, no regression from Phases 06-08.
- Manually fetched `/openapi.json` via `TestClient` and printed every registered path — confirmed all
  12 required groups plus `/health` are present, nothing missing or accidentally duplicated.

## Status

This document, together with `backend/app/api/`, satisfies Phase 09: API contracts for all 12 required
endpoint groups exist, are real (routed, validated, documented), and follow the API design principles
(validated input, consistent errors, typed schemas, no leaked internal exceptions, pagination,
meaningful status codes, documented schemas) — verified by actually running the test suite, not
asserted without execution.
