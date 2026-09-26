"""Platform self-observability via OpenTelemetry (spec Phase 94).

`configure_telemetry(out_dir)` builds SDK tracer/meter providers. Spans go to `<out_dir>/traces.jsonl` as they
end; `flush()` appends a cumulative metrics snapshot to `<out_dir>/metrics.jsonl`. If the optional
`opentelemetry-exporter-otlp-proto-http` package is installed and an endpoint is given, spans and metrics are also
exported over OTLP/HTTP. Without `configure_telemetry` every call below is a cheap no-op (the OTel API's no-op
tracer/meter), so instrumented code is unchanged when telemetry is off.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Optional

from opentelemetry import metrics as _metrics_api
from opentelemetry import trace as _trace_api
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult

_SCOPE = "netscope-x"


class JsonlSpanExporter(SpanExporter):
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()

    def export(self, spans) -> SpanExportResult:
        with self._lock, self._path.open("a", encoding="utf-8") as f:
            for span in spans:
                f.write(span.to_json(indent=None) + "\n")
        return SpanExportResult.SUCCESS


class _State:
    def __init__(self, out_dir: Path, service_name: str, otlp_endpoint: Optional[str]) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        self.out_dir = out_dir
        resource = Resource.create({"service.name": service_name})
        self.reader = InMemoryMetricReader()
        readers = [self.reader]
        self.tracer_provider = TracerProvider(resource=resource)
        self.tracer_provider.add_span_processor(SimpleSpanProcessor(JsonlSpanExporter(out_dir / "traces.jsonl")))
        self.otlp = False
        if otlp_endpoint:
            try:  # optional dependency
                from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
                from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
                from opentelemetry.sdk.trace.export import BatchSpanProcessor

                self.tracer_provider.add_span_processor(
                    BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint.rstrip("/") + "/v1/traces"))
                )
                readers.append(PeriodicExportingMetricReader(
                    OTLPMetricExporter(endpoint=otlp_endpoint.rstrip("/") + "/v1/metrics")))
                self.otlp = True
            except ImportError:
                pass
        self.meter_provider = MeterProvider(resource=resource, metric_readers=readers)
        self.tracer = self.tracer_provider.get_tracer(_SCOPE)
        self.meter = self.meter_provider.get_meter(_SCOPE)
        self.instruments: dict[str, object] = {}


_state: Optional[_State] = None


def configure_telemetry(out_dir: Path, service_name: str = "netscope-x", otlp_endpoint: Optional[str] = None) -> _State:
    global _state
    shutdown_telemetry()
    _state = _State(Path(out_dir), service_name, otlp_endpoint or os.environ.get("NETSCOPE_OTLP_ENDPOINT"))
    return _state


def configure_from_env() -> Optional[_State]:
    """Enable telemetry when NETSCOPE_TELEMETRY_DIR is set (used by the API process)."""
    directory = os.environ.get("NETSCOPE_TELEMETRY_DIR")
    return configure_telemetry(Path(directory)) if directory else None


def enabled() -> bool:
    return _state is not None


def tracer():
    return _state.tracer if _state else _trace_api.get_tracer(_SCOPE)


def _instrument(kind: str, name: str, unit: str):
    if _state is None:
        return None
    inst = _state.instruments.get(name)
    if inst is None:
        make = _state.meter.create_counter if kind == "counter" else _state.meter.create_histogram
        inst = _state.instruments[name] = make(name, unit=unit)
    return inst


def count(name: str, value: int = 1, **attrs) -> None:
    inst = _instrument("counter", name, "1")
    if inst is not None:
        inst.add(value, attrs)


def record(name: str, value: float, unit: str = "ms", **attrs) -> None:
    inst = _instrument("histogram", name, unit)
    if inst is not None:
        inst.record(value, attrs)


def flush() -> None:
    """Append a cumulative metrics snapshot to metrics.jsonl (spans are already written as they end)."""
    if _state is None:
        return
    data = _state.reader.get_metrics_data()
    if data is not None:
        line = {"exported_at": time.time(), "data": json.loads(data.to_json())}
        with (_state.out_dir / "metrics.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(line) + "\n")


def shutdown_telemetry() -> None:
    global _state
    if _state is not None:
        flush()
        _state.tracer_provider.shutdown()
        _state.meter_provider.shutdown()
        _state = None
