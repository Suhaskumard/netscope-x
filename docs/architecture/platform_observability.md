# Platform Self-Observability (Phase 94)

Code: `backend/app/telemetry/` (`setup.py`, `query.py`). OpenTelemetry API/SDK; off unless enabled.

## What is emitted
- **Traces** (`<dir>/traces.jsonl`, one span per line as it ends): one server span per API request
  (`http.method`, `http.route`, `http.status_code`, `request_id`; no tenant id or payload), `replication.commit`
  (Phase 93) spans, and for a matrix run `matrix.run` -> `matrix.cell` (topology_level, completeness, seed, ablation,
  variant, experiment_id, version) -> `matrix.cell.run` / `matrix.cell.persist`.
- **Metrics** (`<dir>/metrics.jsonl`, cumulative snapshot appended on `flush()`/shutdown): `netscope.http.requests`
  (counter; method, route, status_code), `netscope.http.duration_ms` (histogram), `netscope.matrix.cells` (counter),
  `netscope.matrix.cell.duration_ms` (histogram).
- Enable: API process `NETSCOPE_TELEMETRY_DIR=<dir>`; matrix `python -m scripts.run_experiment_matrix --telemetry-dir <dir>`.
  Optional OTLP/HTTP export when `opentelemetry-exporter-otlp-proto-http` is installed and `NETSCOPE_OTLP_ENDPOINT` set.
- Query: `backend.app.telemetry.query.spans(dir, name=, **attrs)`, `children(spans, parent)`, `metric_points(dir, name, **attrs)`.

## Verified (`backend/tests/test_telemetry.py`, 4 tests)
Disabled mode emits nothing; span parent/child and counter/histogram values round-trip; an HTTP request yields a span and
counter (route, status); a real `run_full_matrix` (small topology, 2 completeness levels) produces one root span with one
child per cell and run/persist grandchildren, durations nested and positive, counter == cells run, histogram count/sum
matching the cell spans.

## Limits (not claimed)
- Not run against an OpenTelemetry Collector or backend: the OTLP exporter package is not installed here, so the OTLP path
  is unexercised. "Queryable" means the local JSONL query API above, not Prometheus/Jaeger.
- Metrics are cumulative snapshots written at flush; a long-running API process writes them only at shutdown or an explicit
  `flush()`. Spans are written synchronously per span (small overhead per request).
- Instrumentation covers requests, replication commit and matrix cells; pipeline stages inside a cell (normalize,
  reconstruct, ...) are not individually spanned, and `Timer`/`@timed` still only log.
- Metric attributes include the route template, not path parameters; no sampling.
