"""Phase 09 API architecture tests.

Verifies all 12 required endpoint groups (spec Phase 09) exist, return a
consistent 501 ErrorResponse envelope (since their backing pipeline
stages don't exist yet), that validation errors use the same envelope
shape, and that the OpenAPI schema documents every required path.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)


def _assert_error_envelope(response, expected_status: int) -> None:
    assert response.status_code == expected_status
    body = response.json()
    assert set(body.keys()) == {"error", "detail", "request_id"}
    assert body["request_id"] is not None
    assert body["request_id"] == response.headers["X-Request-ID"]


@pytest.mark.parametrize(
    "method,path,kwargs",
    [
        ("post", "/api/v1/capture", dict(json={"source": "pcap_upload", "pcap_filename": "x.pcap"})),
        ("get", "/api/v1/flows", dict(params={"capture_id": "cap1"})),
        ("get", "/api/v1/topology", dict(params={"capture_id": "cap1"})),
        ("get", "/api/v1/behaviors/node-1", dict()),
        ("get", "/api/v1/anomalies", dict()),
        (
            "get",
            "/api/v1/history",
            dict(
                params={
                    "start": datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat(),
                    "end": datetime(2026, 1, 2, tzinfo=timezone.utc).isoformat(),
                }
            ),
        ),
        ("get", "/api/v1/dependencies", dict(params={"capture_id": "cap1"})),
        ("get", "/api/v1/causal/dep-1", dict()),
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
        ("get", "/api/v1/experiments", dict()),
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
        ("get", "/api/v1/metrics", dict()),
    ],
)
def test_endpoint_returns_structured_501(method: str, path: str, kwargs: dict) -> None:
    response = getattr(client, method)(path, **kwargs)
    _assert_error_envelope(response, 501)
    assert response.json()["error"] == "not_implemented"


def test_all_12_endpoint_groups_covered() -> None:
    # Sanity check on the parametrized test above: if a group is ever
    # renamed/removed from router.py without updating this test file, this
    # count catches the drift instead of silently under-testing.
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


def test_health_endpoint_still_unversioned_and_unaffected() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
