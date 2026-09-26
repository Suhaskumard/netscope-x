"""Phase 97: GET /history/snapshots and /history/snapshots/{version}/topology (real persisted snapshots)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import get_settings
from backend.app.main import app
from backend.archaeology.snapshots import list_snapshots, read_snapshot_graph
from scripts.seed_time_travel_demo import seed

client = TestClient(app)


@pytest.fixture()
def seeded(tmp_path, monkeypatch):
    root = tmp_path / "artifacts"
    monkeypatch.setenv("NETSCOPE_ARTIFACT_ROOT", str(root))
    monkeypatch.setenv("NETSCOPE_UPLOAD_STAGING_DIR", str(tmp_path / "inbox"))
    get_settings.cache_clear()
    info = seed(root)
    yield root, info
    get_settings.cache_clear()


def test_lists_recorded_snapshots_in_version_order(seeded) -> None:
    root, info = seeded
    body = client.get("/api/v1/history/snapshots", params={"capture_id": info["capture_id"]}).json()
    assert [s["version"] for s in body["items"]] == [1, 2, 3, 4] and body["total"] == 4
    assert [s["captured_at"] for s in body["items"]] == sorted(s["captured_at"] for s in body["items"])


def test_snapshot_topology_is_the_recorded_graph_and_differs_over_time(seeded) -> None:
    root, info = seeded
    cid = info["capture_id"]
    counts = []
    for snap in list_snapshots(root, cid):
        got = client.get(f"/api/v1/history/snapshots/{snap.version}/topology", params={"capture_id": cid}).json()
        assert got == read_snapshot_graph(root, cid, snap).model_dump(mode="json")
        counts.append((len(got["nodes"]), len(got["edges"])))
    assert counts == [(2, 1), (3, 2), (5, 4), (5, 4)]  # earlier snapshots really have fewer hosts/links


def test_unknown_version_is_404_envelope_and_unknown_capture_lists_empty(seeded) -> None:
    _, info = seeded
    r = client.get("/api/v1/history/snapshots/99/topology", params={"capture_id": info["capture_id"]})
    assert r.status_code == 404 and r.json()["error"] == "snapshot_not_found"
    assert client.get("/api/v1/history/snapshots", params={"capture_id": "nope"}).json()["total"] == 0
    assert client.get("/api/v1/history/snapshots", params={"capture_id": "../x"}).status_code == 422


def test_tenant_cannot_read_another_tenants_snapshots(tmp_path, monkeypatch) -> None:
    from backend.app.tenancy.paths import tenant_root
    from backend.app.tenancy.store import TenantRegistry

    root = tmp_path / "artifacts"
    monkeypatch.setenv("NETSCOPE_ARTIFACT_ROOT", str(root))
    monkeypatch.setenv("NETSCOPE_UPLOAD_STAGING_DIR", str(tmp_path / "inbox"))
    monkeypatch.setenv("NETSCOPE_TENANCY_ENABLED", "true")
    get_settings.cache_clear()
    reg = TenantRegistry(root)
    key_a, key_b = reg.create_tenant("acme"), reg.create_tenant("globex")
    info = seed(tenant_root(root, "acme"))
    a = {"X-Tenant-Key": key_a}
    b = {"X-Tenant-Key": key_b}
    p = {"capture_id": info["capture_id"]}
    assert client.get("/api/v1/history/snapshots", params=p, headers=a).json()["total"] == 4
    assert client.get("/api/v1/history/snapshots", params=p, headers=b).json()["total"] == 0
    assert client.get("/api/v1/history/snapshots/1/topology", params=p, headers=b).status_code == 404
    get_settings.cache_clear()
