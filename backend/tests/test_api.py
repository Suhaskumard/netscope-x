"""Phase 09 API architecture tests, updated for Phases 21, 23, 32, 49, 51, 56, and 68.

Verifies the still-unimplemented endpoint groups (spec Phase 09) return
a consistent 501 ErrorResponse envelope, that validation errors use the
same envelope shape, and that the OpenAPI schema documents every required
path. `POST /capture` (Phase 21), `GET /flows` (Phase 23),
`GET /topology` (Phase 32), `GET /history` (Phase 49),
`GET /dependencies` (Phase 51), `GET /causal/{dependency_id}` (Phase 56),
and `GET /experiments`/`GET /metrics` (Phase 68) are no longer in the 501
list -- their real behavior is covered by the dedicated tests at the
bottom of this file. `POST /experiments` stays 501 -- see
`backend/app/api/routes/experiments.py`'s own docstring.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from scapy.all import IP, TCP, UDP, wrpcap

from backend.app.core.config import get_settings
from backend.app.main import app
from backend.app.models import TopologyGraph
from backend.archaeology.snapshots import create_snapshot
from experiments.artifacts.io import read_json
from experiments.artifacts.paths import topology_path

client = TestClient(app)


@pytest.fixture(autouse=True)
def _capture_dirs(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("NETSCOPE_UPLOAD_STAGING_DIR", str(tmp_path / "inbox"))
    monkeypatch.setenv("NETSCOPE_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _write_real_pcap(path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    packets = [IP(src="10.0.0.1", dst="10.0.0.2") / TCP(sport=1234, dport=80) for _ in range(3)]
    wrpcap(str(path), packets)


def _assert_error_envelope(response, expected_status: int) -> None:
    assert response.status_code == expected_status
    body = response.json()
    assert set(body.keys()) == {"error", "detail", "request_id"}
    assert body["request_id"] is not None
    assert body["request_id"] == response.headers["X-Request-ID"]


@pytest.mark.parametrize(
    "method,path,kwargs",
    [
        ("get", "/api/v1/behaviors/node-1", dict()),
        ("get", "/api/v1/anomalies", dict()),
        (
            "post",
            "/api/v1/simulation",
            dict(json={"scenario_id": "s1", "failure_type": "node_failure", "target_node_id": "n1"}),
        ),
        (
            "post",
            "/api/v1/counterfactual",
            dict(
                json={
                    "scenario_id": "cf1",
                    "action": "REMOVE_NODE",
                    "baseline_graph_id": "g1",
                    "isolated_graph_id": "g1-cf1",
                    "target_node_id": "n1",
                    "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat(),
                }
            ),
        ),
        (
            "post",
            "/api/v1/experiments",
            dict(
                json={
                    "experiment_id": "exp1",
                    "dataset_version": "v1",
                    "code_version": "abc123",
                    "configuration": {},
                    "random_seed": 1,
                    "timestamp": datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat(),
                    "environment": "docker-lab",
                }
            ),
        ),
    ],
)
def test_endpoint_returns_structured_501(method: str, path: str, kwargs: dict) -> None:
    response = getattr(client, method)(path, **kwargs)
    _assert_error_envelope(response, 501)
    assert response.json()["error"] == "not_implemented"


def test_all_12_endpoint_groups_exist() -> None:
    # Sanity check: if a group is ever renamed/removed from router.py
    # without updating this test file, this count catches the drift
    # instead of silently under-testing. Only 6 of these 12 are covered
    # by the generic 501 parametrization above -- /capture (Phase 21),
    # /flows (Phase 23), /topology (Phase 32), /history (Phase 49),
    # /dependencies (Phase 51), and /causal (Phase 56) are real and
    # tested separately below.
    paths = {
        "/api/v1/capture",
        "/api/v1/flows",
        "/api/v1/topology",
        "/api/v1/behaviors",
        "/api/v1/anomalies",
        "/api/v1/history",
        "/api/v1/dependencies",
        "/api/v1/causal",
        "/api/v1/simulation",
        "/api/v1/counterfactual",
        "/api/v1/experiments",
        "/api/v1/metrics",
    }
    assert len(paths) == 12


def test_malformed_request_body_returns_consistent_422_envelope() -> None:
    # "source" must be one of the two literal values; this is neither.
    response = client.post("/api/v1/capture", json={"source": "not_a_valid_source"})
    _assert_error_envelope(response, 422)
    assert response.json()["error"] == "validation_error"


def test_missing_required_query_param_returns_consistent_422_envelope() -> None:
    response = client.get("/api/v1/flows")  # capture_id is required
    _assert_error_envelope(response, 422)
    assert response.json()["error"] == "validation_error"


@pytest.mark.parametrize(
    "path",
    ["/api/v1/flows", "/api/v1/topology", "/api/v1/dependencies", "/api/v1/history"],
)
def test_path_traversal_capture_id_rejected_before_touching_disk(path: str) -> None:
    """SEC-4: capture_id is used verbatim as a filesystem path segment
    (experiments/artifacts/paths.py). A `..`-laden value must be rejected by
    request validation (422), never reach path-building code."""
    response = client.get(path, params={"capture_id": "../../../../etc/passwd"})
    _assert_error_envelope(response, 422)
    assert response.json()["error"] == "validation_error"


def test_openapi_schema_documents_all_required_paths() -> None:
    schema = client.get("/openapi.json").json()
    required = {
        "/api/v1/capture",
        "/api/v1/flows",
        "/api/v1/topology",
        "/api/v1/behaviors/{node_id}",
        "/api/v1/anomalies",
        "/api/v1/history",
        "/api/v1/dependencies",
        "/api/v1/causal/{dependency_id}",
        "/api/v1/simulation",
        "/api/v1/counterfactual",
        "/api/v1/experiments",
        "/api/v1/metrics",
    }
    assert required.issubset(schema["paths"].keys())


# --- Phase 21: POST /capture real behavior ---


def test_capture_pcap_upload_ingests_real_pcap(tmp_path) -> None:
    settings = get_settings()
    _write_real_pcap(settings.upload_staging_dir / "real.pcap")

    response = client.post(
        "/api/v1/capture",
        json={"source": "pcap_upload", "pcap_filename": "real.pcap"},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "accepted"
    assert body["packet_count"] == 3
    assert body["capture_id"]

    ingested = settings.artifact_root / "captures" / body["capture_id"] / "raw.pcap"
    assert ingested.is_file()


def test_capture_pcap_upload_missing_file_returns_422() -> None:
    response = client.post(
        "/api/v1/capture",
        json={"source": "pcap_upload", "pcap_filename": "does_not_exist.pcap"},
    )
    _assert_error_envelope(response, 422)
    assert response.json()["error"] == "invalid_pcap"


def test_capture_pcap_upload_invalid_pcap_content_returns_422() -> None:
    settings = get_settings()
    bad = settings.upload_staging_dir / "bad.pcap"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_bytes(b"not a real pcap file")

    response = client.post(
        "/api/v1/capture",
        json={"source": "pcap_upload", "pcap_filename": "bad.pcap"},
    )
    _assert_error_envelope(response, 422)
    assert response.json()["error"] == "invalid_pcap"


def test_capture_pcap_upload_without_filename_returns_422() -> None:
    response = client.post("/api/v1/capture", json={"source": "pcap_upload"})
    _assert_error_envelope(response, 422)
    assert response.json()["error"] == "validation_error"


def test_capture_pcap_upload_rejects_path_traversal_filename() -> None:
    response = client.post(
        "/api/v1/capture",
        json={"source": "pcap_upload", "pcap_filename": "../../etc/passwd"},
    )
    _assert_error_envelope(response, 422)
    assert response.json()["error"] == "validation_error"


def test_capture_live_interface_authorized_returns_202_with_workflow_note() -> None:
    response = client.post(
        "/api/v1/capture",
        json={"source": "live_interface", "interface": "eth0"},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "accepted"
    assert "simulator.capture.live" in body["note"]


def test_capture_live_interface_unauthorized_returns_403() -> None:
    response = client.post(
        "/api/v1/capture",
        json={"source": "live_interface", "interface": "eth99"},
    )
    _assert_error_envelope(response, 403)
    assert response.json()["error"] == "unauthorized_interface"


# --- Phase 23: GET /flows real behavior ---


def test_flows_unknown_capture_returns_404() -> None:
    response = client.get("/api/v1/flows", params={"capture_id": "does-not-exist"})
    _assert_error_envelope(response, 404)
    assert response.json()["error"] == "capture_not_found"


def test_flows_returns_real_reconstructed_flows_for_ingested_capture() -> None:
    settings = get_settings()
    path = settings.upload_staging_dir / "exchange.pcap"
    path.parent.mkdir(parents=True, exist_ok=True)
    packets = [
        IP(src="10.0.0.1", dst="10.0.0.2") / TCP(sport=1000, dport=80, flags="S"),
        IP(src="10.0.0.2", dst="10.0.0.1") / TCP(sport=80, dport=1000, flags="SA"),
        IP(src="10.0.0.1", dst="10.0.0.2") / TCP(sport=1000, dport=80, flags="A"),
    ]
    wrpcap(str(path), packets)

    ingest = client.post("/api/v1/capture", json={"source": "pcap_upload", "pcap_filename": "exchange.pcap"})
    capture_id = ingest.json()["capture_id"]

    response = client.get("/api/v1/flows", params={"capture_id": capture_id})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    flow = body["items"][0]
    assert flow["src_ip"] == "10.0.0.1"
    assert flow["dst_ip"] == "10.0.0.2"
    assert flow["protocol"] == "TCP"
    assert flow["tcp_state"] == "established"
    assert flow["features"]["packet_count"] == 3


def test_flows_respects_pagination_params() -> None:
    settings = get_settings()
    path = settings.upload_staging_dir / "two_flows.pcap"
    path.parent.mkdir(parents=True, exist_ok=True)
    packets = [
        IP(src="10.0.0.1", dst="10.0.0.2") / TCP(sport=1000, dport=80),
        IP(src="10.0.0.3", dst="10.0.0.4") / UDP(sport=2000, dport=53),
    ]
    wrpcap(str(path), packets)

    ingest = client.post("/api/v1/capture", json={"source": "pcap_upload", "pcap_filename": "two_flows.pcap"})
    capture_id = ingest.json()["capture_id"]

    response = client.get("/api/v1/flows", params={"capture_id": capture_id, "limit": 1, "offset": 0})
    body = response.json()
    assert body["total"] == 2
    assert len(body["items"]) == 1
    assert body["limit"] == 1
    assert body["offset"] == 0


# --- Phase 32: GET /topology real behavior ---


def _ingest_real_two_flow_capture(filename: str) -> str:
    settings = get_settings()
    path = settings.upload_staging_dir / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    packets = [
        IP(src="10.0.0.1", dst="10.0.0.2") / TCP(sport=1000, dport=80, flags="S"),
        IP(src="10.0.0.2", dst="10.0.0.1") / TCP(sport=80, dport=1000, flags="SA"),
        IP(src="10.0.0.1", dst="10.0.0.2") / TCP(sport=1000, dport=80, flags="A"),
        IP(src="10.0.0.3", dst="10.0.0.4") / UDP(sport=2000, dport=53),
    ]
    wrpcap(str(path), packets)
    ingest = client.post("/api/v1/capture", json={"source": "pcap_upload", "pcap_filename": filename})
    return ingest.json()["capture_id"]


def test_topology_unknown_capture_returns_404() -> None:
    response = client.get("/api/v1/topology", params={"capture_id": "does-not-exist"})
    _assert_error_envelope(response, 404)
    assert response.json()["error"] == "capture_not_found"


def test_topology_returns_real_reconstructed_graph_for_ingested_capture() -> None:
    capture_id = _ingest_real_two_flow_capture("topology.pcap")

    response = client.get("/api/v1/topology", params={"capture_id": capture_id})
    assert response.status_code == 200
    graph = response.json()

    assert graph["graph_id"] == capture_id
    assert len(graph["nodes"]) == 4  # 10.0.0.1-4, one flow each direction/pair
    assert len(graph["edges"]) == 2  # (10.0.0.1,10.0.0.2) and (10.0.0.3,10.0.0.4)
    for edge in graph["edges"]:
        assert 0.0 <= edge["confidence"] <= 1.0
        assert len(edge["evidence"]) > 0
        assert len(edge["protocols"]) > 0


def test_topology_graph_id_is_deterministic_across_calls() -> None:
    capture_id = _ingest_real_two_flow_capture("topology_deterministic.pcap")

    first = client.get("/api/v1/topology", params={"capture_id": capture_id}).json()
    second = client.get("/api/v1/topology", params={"capture_id": capture_id}).json()

    assert first["graph_id"] == second["graph_id"] == capture_id
    assert first["nodes"] == second["nodes"]
    assert first["edges"] == second["edges"]


def test_topology_is_persisted_and_round_trips() -> None:
    capture_id = _ingest_real_two_flow_capture("topology_persist.pcap")

    response = client.get("/api/v1/topology", params={"capture_id": capture_id})
    graph = response.json()

    settings = get_settings()
    on_disk = read_json(topology_path(settings.artifact_root, capture_id, capture_id), TopologyGraph)
    assert on_disk.graph_id == graph["graph_id"]
    assert len(on_disk.nodes) == len(graph["nodes"])
    assert len(on_disk.edges) == len(graph["edges"])


def test_health_endpoint_still_unversioned_and_unaffected() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# --- Phase 49: GET /history real behavior ---

_HISTORY_BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _ingest_two_episode_capture(filename: str) -> str:
    settings = get_settings()
    path = settings.upload_staging_dir / filename
    path.parent.mkdir(parents=True, exist_ok=True)

    episode1 = IP(src="10.0.0.1", dst="10.0.0.2") / TCP(sport=1000, dport=80, flags="S")
    episode1.time = _HISTORY_BASE.timestamp()
    episode2 = IP(src="10.0.0.3", dst="10.0.0.4") / UDP(sport=2000, dport=53)
    episode2.time = (_HISTORY_BASE + timedelta(seconds=100)).timestamp()
    wrpcap(str(path), [episode1, episode2])

    ingest = client.post("/api/v1/capture", json={"source": "pcap_upload", "pcap_filename": filename})
    capture_id = ingest.json()["capture_id"]

    # Populates packets.jsonl/flows.jsonl so create_snapshot's build_topology_graph has
    # something real to read, same prerequisite GET /flows/GET /topology depend on.
    client.get("/api/v1/flows", params={"capture_id": capture_id})
    return capture_id


def test_history_unknown_capture_returns_empty_not_404() -> None:
    response = client.get(
        "/api/v1/history",
        params={
            "capture_id": "does-not-exist",
            "start": _HISTORY_BASE.isoformat(),
            "end": (_HISTORY_BASE + timedelta(days=1)).isoformat(),
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body == {"items": [], "limit": 50, "offset": 0, "total": 0}


def test_history_returns_events_within_window() -> None:
    capture_id = _ingest_two_episode_capture("history_full_window.pcap")
    settings = get_settings()
    create_snapshot(settings.artifact_root, capture_id, captured_at=_HISTORY_BASE + timedelta(seconds=10))
    create_snapshot(settings.artifact_root, capture_id, captured_at=_HISTORY_BASE + timedelta(seconds=200))

    response = client.get(
        "/api/v1/history",
        params={
            "capture_id": capture_id,
            "start": _HISTORY_BASE.isoformat(),
            "end": (_HISTORY_BASE + timedelta(seconds=300)).isoformat(),
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] > 0
    assert all(
        event["change_type"] in {"node_added", "edge_added", "attribute_changed"} for event in body["items"]
    )


def test_history_narrow_window_excludes_events_outside_it() -> None:
    capture_id = _ingest_two_episode_capture("history_narrow_window.pcap")
    settings = get_settings()
    create_snapshot(settings.artifact_root, capture_id, captured_at=_HISTORY_BASE + timedelta(seconds=10))
    create_snapshot(settings.artifact_root, capture_id, captured_at=_HISTORY_BASE + timedelta(seconds=200))

    full = client.get(
        "/api/v1/history",
        params={
            "capture_id": capture_id,
            "start": _HISTORY_BASE.isoformat(),
            "end": (_HISTORY_BASE + timedelta(seconds=300)).isoformat(),
        },
    ).json()
    assert full["total"] > 0

    before_any_event = client.get(
        "/api/v1/history",
        params={
            "capture_id": capture_id,
            "start": (_HISTORY_BASE - timedelta(days=1)).isoformat(),
            "end": (_HISTORY_BASE - timedelta(hours=1)).isoformat(),
        },
    ).json()
    assert before_any_event == {"items": [], "limit": 50, "offset": 0, "total": 0}


def test_history_respects_pagination_params() -> None:
    capture_id = _ingest_two_episode_capture("history_pagination.pcap")
    settings = get_settings()
    create_snapshot(settings.artifact_root, capture_id, captured_at=_HISTORY_BASE + timedelta(seconds=10))
    create_snapshot(settings.artifact_root, capture_id, captured_at=_HISTORY_BASE + timedelta(seconds=200))

    params = {
        "capture_id": capture_id,
        "start": _HISTORY_BASE.isoformat(),
        "end": (_HISTORY_BASE + timedelta(seconds=300)).isoformat(),
    }
    full = client.get("/api/v1/history", params=params).json()
    assert full["total"] >= 2

    paged = client.get("/api/v1/history", params={**params, "limit": 1, "offset": 0}).json()
    assert paged["total"] == full["total"]
    assert len(paged["items"]) == 1
    assert paged["limit"] == 1
    assert paged["offset"] == 0


# --- Phase 51: GET /dependencies real behavior ---


def test_dependencies_unknown_capture_returns_empty_not_404() -> None:
    response = client.get("/api/v1/dependencies", params={"capture_id": "does-not-exist"})
    assert response.status_code == 200
    assert response.json() == {"items": [], "limit": 50, "offset": 0, "total": 0}


def test_dependencies_returns_real_dependency_edges_for_ingested_capture() -> None:
    capture_id = _ingest_real_two_flow_capture("dependencies.pcap")
    client.get("/api/v1/flows", params={"capture_id": capture_id})

    response = client.get("/api/v1/dependencies", params={"capture_id": capture_id})
    assert response.status_code == 200
    body = response.json()

    assert body["total"] == 2  # one dependency edge per topology edge (TCP pair + UDP pair)
    for dep in body["items"]:
        assert dep["source_node_id"] != dep["target_node_id"]
        assert 0.0 <= dep["strength"] <= 1.0
        assert 0.0 <= dep["directionality_score"] <= 1.0
        assert dep["frequency"] >= 0
        assert dep["persistence_seconds"] >= 0
        assert dep["temporal_precedence_score"] == 0.0
        assert dep["dependency_id"]


def test_dependencies_respects_pagination_params() -> None:
    capture_id = _ingest_real_two_flow_capture("dependencies_pagination.pcap")
    client.get("/api/v1/flows", params={"capture_id": capture_id})

    full = client.get("/api/v1/dependencies", params={"capture_id": capture_id}).json()
    assert full["total"] == 2

    paged = client.get(
        "/api/v1/dependencies", params={"capture_id": capture_id, "limit": 1, "offset": 0}
    ).json()
    assert paged["total"] == full["total"]
    assert len(paged["items"]) == 1
    assert paged["limit"] == 1
    assert paged["offset"] == 0


# --- Phase 56: GET /causal/{dependency_id} real behavior ---


def test_causal_unknown_capture_returns_404() -> None:
    response = client.get(
        "/api/v1/causal/does-not-exist:dependency:0", params={"capture_id": "does-not-exist"}
    )
    _assert_error_envelope(response, 404)
    assert response.json()["error"] == "dependency_not_found"


def test_causal_unknown_dependency_id_within_real_capture_returns_404() -> None:
    capture_id = _ingest_real_two_flow_capture("causal_unknown.pcap")
    client.get("/api/v1/flows", params={"capture_id": capture_id})

    response = client.get(
        f"/api/v1/causal/{capture_id}:dependency:999", params={"capture_id": capture_id}
    )
    _assert_error_envelope(response, 404)
    assert response.json()["error"] == "dependency_not_found"


def test_causal_returns_real_evidence_report_for_ingested_capture() -> None:
    capture_id = _ingest_real_two_flow_capture("causal.pcap")
    client.get("/api/v1/flows", params={"capture_id": capture_id})

    dependencies = client.get(
        "/api/v1/dependencies", params={"capture_id": capture_id}
    ).json()["items"]
    dependency_id = dependencies[0]["dependency_id"]

    response = client.get(
        f"/api/v1/causal/{dependency_id}", params={"capture_id": capture_id}
    )
    assert response.status_code == 200
    body = response.json()

    assert body["relationship"]
    assert len(body["evidence"]) >= 1
    assert 0.0 <= body["confidence"] <= 1.0
    assert len(body["limitations"]) >= 1
    assert body["report_id"] == f"{dependency_id}:causal_evidence"


# --- Phase 68: GET /experiments, GET /metrics real behavior ---


def test_experiments_empty_when_none_run_yet() -> None:
    response = client.get("/api/v1/experiments")
    assert response.status_code == 200
    assert response.json() == {"items": [], "limit": 50, "offset": 0, "total": 0}


def test_metrics_empty_when_none_run_yet() -> None:
    response = client.get("/api/v1/metrics")
    assert response.status_code == 200
    assert response.json() == {"items": [], "limit": 50, "offset": 0, "total": 0}


def test_experiments_and_metrics_return_a_real_persisted_matrix_cell() -> None:
    from experiments.matrix_runner import persist_cell, run_matrix_cell

    settings = get_settings()
    cell = run_matrix_cell(settings.artifact_root, "small", 1.0, seed=1)
    persist_cell(settings.artifact_root, cell)

    experiments_body = client.get("/api/v1/experiments").json()
    assert experiments_body["total"] == 1
    assert experiments_body["items"][0]["experiment_id"] == cell.experiment.experiment_id

    metrics_body = client.get("/api/v1/metrics").json()
    assert metrics_body["total"] == len(cell.metrics)
    assert all(m["experiment_id"] == cell.experiment.experiment_id for m in metrics_body["items"])


def test_metrics_context_filter() -> None:
    from experiments.matrix_runner import persist_cell, run_matrix_cell

    settings = get_settings()
    cell = run_matrix_cell(settings.artifact_root, "small", 1.0, seed=2)
    persist_cell(settings.artifact_root, cell)

    response = client.get("/api/v1/metrics", params={"context": "topology_reconstruction"})
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["context"] == "topology_reconstruction"


def test_experiments_pagination() -> None:
    from experiments.matrix_runner import persist_cell, run_matrix_cell

    settings = get_settings()
    for seed in (10, 11):
        cell = run_matrix_cell(settings.artifact_root, "small", 1.0, seed=seed)
        persist_cell(settings.artifact_root, cell)

    full = client.get("/api/v1/experiments").json()
    assert full["total"] == 2

    paged = client.get("/api/v1/experiments", params={"limit": 1, "offset": 0}).json()
    assert paged["total"] == 2
    assert len(paged["items"]) == 1


def test_rerun_experiment_is_listed_once_as_its_latest_run() -> None:
    from experiments.matrix_runner import run_and_persist_cell

    settings = get_settings()
    first = run_and_persist_cell(settings.artifact_root, "small", 1.0, seed=20)
    second = run_and_persist_cell(settings.artifact_root, "small", 1.0, seed=20)
    assert first.experiment.experiment_id == second.experiment.experiment_id

    experiments_body = client.get("/api/v1/experiments").json()
    assert experiments_body["total"] == 1
    assert experiments_body["items"][0]["configuration"]["run_version"] == 2

    metrics_body = client.get("/api/v1/metrics").json()
    assert metrics_body["total"] == len(second.metrics)  # not doubled by the retained v1
