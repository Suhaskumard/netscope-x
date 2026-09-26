# NETSCOPE-X — API Reference

Phase 69 documentation deliverable. All 12 route groups are defined per spec Phase 09
(`backend/app/api/router.py`); this document reflects their actual current behavior, not the aspirational
spec surface — see `docs/acceptance_testing.md` FR-1.41 for the verification behind each row.

Base path: `/api/v1`. Every response uses one of two shapes:

- Success: the endpoint's own typed model (see `backend/app/models/`), or `PaginatedResponse[T]`
  (`{items, limit, offset, total}`) for list endpoints.
- Error: `ErrorResponse` (`{error, detail, request_id}`) — one shape for every 4xx/5xx, never a raw
  exception or FastAPI's default validation-error format (`backend/app/api/errors.py`).

## Real, working endpoints

| Method & path | Purpose | Key params | Notes |
|---|---|---|---|
| `POST /capture` | Ingest a PCAP (or record a live-interface capture request) | body: `{source: "pcap_upload"\|"live_interface", pcap_filename?, interface?}` | Returns `202 CaptureAccepted {capture_id, status, packet_count}`. `pcap_upload` validates and copies a real pcap from the upload staging dir; `live_interface` validates the interface against the authorized allowlist (spec §5) before returning. |
| `GET /flows?capture_id=` | Reconstructed 5-tuple flows for a capture | `capture_id` (required, `^[A-Za-z0-9_-]+$`), `limit`, `offset` | Recomputes from `raw.pcap` on every call — no cache (`docs/architecture/flow_reconstruction.md`). |
| `GET /topology?capture_id=` | Probabilistic topology graph | `capture_id` (required, same pattern) | Recomputes fresh on every call; `graph_id` always equals `capture_id`. |
| `GET /dependencies?capture_id=` | Dependency-strength edges | `capture_id` (required, same pattern), `limit`, `offset` | |
| `GET /causal/{dependency_id}?capture_id=` | Causal evidence report for one dependency or propagation edge | `dependency_id` (path), `capture_id` (required, same pattern) | 404 (`DependencyNotFoundError`) if `dependency_id` doesn't match any dependency/candidate computed for that `capture_id`. |
| `GET /causal/{dependency_id}/attribution?capture_id=` | Per-signal Shapley breakdown of the dependency's strength (Phase 99) | `dependency_id` (path), `capture_id` | `signals[]` (raw, standalone probability, contribution, drop-one strength), `sum_of_contributions`, `residual`, plus the Phase 56 report; same 404 as `/causal`. |
| `GET /history?capture_id=&start=&end=` | Topology change events in a time window | `capture_id` (required, same pattern), `start`, `end` (ISO datetimes) | |
| `GET /history/snapshots?capture_id=` | Recorded topology snapshots, version order (Phase 97) | `capture_id`, `limit`, `offset` | Unknown capture -> empty list, like `/history`. |
| `GET /history/snapshots/{version}/topology?capture_id=` | The topology graph exactly as recorded at that snapshot (Phase 97) | `version` (path), `capture_id` | Read back, never recomputed; 404 `snapshot_not_found`. |
| `POST /counterfactual/ask` | Natural-language what-if (Phase 98): `{capture_id, question}` | body | Returns `status` answered / needs_clarification / rejected; answered carries the real scenario, facts, and a verified explanation (`explanation_source` llm or template). 503 `llm_unavailable` without `ANTHROPIC_API_KEY`. |
| `POST /investigation/report` | Cited investigation report for one dependency (Phase 100): `{capture_id, dependency_id, failed_node_id?}` | body | Returns `markdown`, `source` (`llm` verified draft or `template`), `citations[]` (fact id, source path, value, text), `violations`. Works without an LLM key (template). 404 for an unknown dependency or node. |
| `GET /experiments` | List recorded experiments | `limit`, `offset` | Reads real `Experiment` records written by `experiments/matrix_runner.py`. |
| `GET /metrics?context=` | List recorded metric results | `context` (optional `MetricContext` filter), `limit`, `offset` | |

## Endpoints that validate but do not yet compute (`501 not_implemented`)

These accept and validate real input (so a malformed request still gets a correct 422, not a 501) but
their backing pipeline stage is not wired in yet even though it exists and is independently tested —
see `docs/LIMITATIONS.md` for why this phase did not close the gap.

| Method & path | Real backing module (untested via API) |
|---|---|
| `GET /anomalies?node_id=` | `backend/flowmind/anomaly/` |
| `GET /behaviors/{node_id}` | `backend/flowmind/classification/role_classifier.py`, `backend/flowmind/fingerprints/` |
| `POST /simulation` | `backend/simulation/failure_injection.py`, `failure_propagation_pipeline.py` |
| `POST /counterfactual` | `backend/simulation/counterfactual_engine.py`, `counterfactual_comparison.py` |
| `POST /experiments` | `experiments/matrix_runner.py` (live-triggering via API is a separate, riskier concern than the batch `scripts/run_experiment_matrix.py` path) |

## Identifier constraints

`capture_id` is used verbatim as a filesystem path segment (`experiments/artifacts/paths.py`) and is
therefore restricted to `^[A-Za-z0-9_-]+$` (enforced via FastAPI `Query(pattern=...)`,
`backend/app/api/schemas.py::CAPTURE_ID_PATTERN`) — a value outside this charset returns `422
validation_error` before any path is built. Real `capture_id` values are always `uuid4` hex strings
generated by `POST /capture`.

## Error codes

| `error` | HTTP status | Raised by |
|---|---|---|
| `validation_error` | 422 | Any request failing Pydantic/FastAPI validation (missing/malformed field, `capture_id` pattern mismatch) |
| `invalid_pcap` | 422 | `POST /capture` with a file that doesn't parse as a non-empty pcap |
| `unauthorized_interface` | 403 | `POST /capture` (`source=live_interface`) targeting an interface outside the allowlist |
| `capture_not_found` | 404 | `GET /flows`/`/topology` for a `capture_id` with no ingested `raw.pcap` |
| `llm_unavailable` | 503 | `POST /counterfactual/ask` with no LLM key/client or a failed provider call |
| `snapshot_not_found` | 404 | `GET /history/snapshots/{version}/topology` for a version that was never recorded |
| `dependency_not_found` | 404 | `GET /causal/{dependency_id}` for an unmatched id |
| `not_implemented` | 501 | Any of the 5 unwired routes above |
| `internal_error` | 500 | Any unhandled exception; the client sees only a generic message + `request_id`, never the raw exception (spec §15) |

Full machine-readable schema: `GET /openapi.json` on a running instance (`uvicorn backend.app.main:app`).
