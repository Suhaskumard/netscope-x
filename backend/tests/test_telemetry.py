"""Phase 94: the platform emits real OpenTelemetry traces/metrics about itself and they can be queried back."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import get_settings
from backend.app.main import app
from backend.app.telemetry import query, setup as telemetry
from experiments.matrix_runner import run_full_matrix


@pytest.fixture(autouse=True)
def _reset():
    telemetry.shutdown_telemetry()
    yield
    telemetry.shutdown_telemetry()


def test_disabled_mode_emits_nothing_and_does_not_fail(tmp_path) -> None:
    assert not telemetry.enabled()
    with telemetry.tracer().start_as_current_span("x"):
        telemetry.count("c", 1)
        telemetry.record("h", 1.0)
    telemetry.flush()
    assert list(tmp_path.iterdir()) == []


def test_spans_and_metrics_roundtrip(tmp_path) -> None:
    telemetry.configure_telemetry(tmp_path)
    with telemetry.tracer().start_as_current_span("parent", attributes={"k": "v"}):
        with telemetry.tracer().start_as_current_span("child"):
            pass
    for _ in range(3):
        telemetry.count("things", 2, kind="a")
    telemetry.record("lat", 5.0, kind="a")
    telemetry.record("lat", 7.0, kind="a")
    telemetry.flush()

    parent = query.spans(tmp_path, name="parent", k="v")[0]
    child = query.spans(tmp_path, name="child")[0]
    assert child.parent_id == parent.span_id and child.trace_id == parent.trace_id
    assert child.start >= parent.start and child.end <= parent.end
    assert query.metric_points(tmp_path, "things", kind="a")[0].value == 6
    h = query.metric_points(tmp_path, "lat")[0]
    assert (h.count, h.sum) == (2, 12.0)


def test_http_request_emits_span_and_counter(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NETSCOPE_ARTIFACT_ROOT", str(tmp_path / "a"))
    get_settings.cache_clear()
    telemetry.configure_telemetry(tmp_path / "t")
    client = TestClient(app)
    assert client.get("/api/v1/experiments").status_code == 200
    assert client.get("/api/v1/anomalies").status_code == 501
    telemetry.flush()
    s = query.spans(tmp_path / "t", name="GET /api/v1/experiments")[0]
    assert s.attributes["http.status_code"] == 200 and s.attributes["http.route"] == "/api/v1/experiments"
    assert query.metric_points(tmp_path / "t", "netscope.http.requests", status_code=501)[0].value == 1
    get_settings.cache_clear()


def test_real_matrix_run_is_traced_and_queryable(tmp_path) -> None:
    tdir = tmp_path / "telemetry"
    telemetry.configure_telemetry(tdir, service_name="netscope-x-matrix")
    results = run_full_matrix(
        tmp_path / "data", topology_levels=["small"], completeness_levels=[1.0, 0.5],
        run_ablations=False, run_sensitivity_sweep=False,
    )
    telemetry.flush()
    assert len(results) == 2

    all_spans = query.spans(tdir)
    (root,) = query.spans(tdir, name="matrix.run")
    assert root.attributes["cells"] == 2
    cells = query.children(all_spans, root)
    assert len(cells) == 2 and {c.name for c in cells} == {"matrix.cell"}
    assert {c.attributes["completeness"] for c in cells} == {1.0, 0.5}
    for cell in cells:
        stages = {s.name: s for s in query.children(all_spans, cell)}
        assert set(stages) == {"matrix.cell.run", "matrix.cell.persist"}
        assert 0 < stages["matrix.cell.run"].duration_ms <= cell.duration_ms <= root.duration_ms
    assert sum(c.duration_ms for c in cells) <= root.duration_ms

    assert query.metric_points(tdir, "netscope.matrix.cells", topology_level="small")[0].value == 2
    h = query.metric_points(tdir, "netscope.matrix.cell.duration_ms")[0]
    assert h.count == 2 and h.sum == pytest.approx(sum(c.duration_ms for c in cells), rel=0.2)
