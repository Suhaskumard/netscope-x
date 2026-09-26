"""Phase 91 multi-tenant isolation tests: two tenants driven through the real API, cross-tenant access tried directly."""

from __future__ import annotations

import hashlib
import json

import pytest
from fastapi.testclient import TestClient
from scapy.all import IP, TCP, wrpcap

from backend.app.core.config import get_settings
from backend.app.main import app
from backend.app.tenancy.ids import validate_tenant_id
from backend.app.tenancy.paths import tenant_inbox, tenant_root
from backend.app.tenancy.store import TenantRegistry

client = TestClient(app)


@pytest.fixture()
def tenants(tmp_path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "artifacts"
    monkeypatch.setenv("NETSCOPE_ARTIFACT_ROOT", str(root))
    monkeypatch.setenv("NETSCOPE_TENANCY_ENABLED", "true")
    get_settings.cache_clear()
    registry = TenantRegistry(root)
    keys = {t: registry.create_tenant(t) for t in ("alpha", "beta")}
    yield root, keys
    get_settings.cache_clear()


def _h(key):
    return {"X-Tenant-Key": key}


def _stage_pcap(root, tenant, name="a.pcap"):
    path = tenant_inbox(root, tenant) / name
    wrpcap(str(path), [IP(src="10.0.0.1", dst="10.0.0.2") / TCP(sport=1234, dport=80) for _ in range(3)])
    return name


def _ingest(root, keys, tenant):
    name = _stage_pcap(root, tenant)
    r = client.post("/api/v1/capture", json={"source": "pcap_upload", "pcap_filename": name}, headers=_h(keys[tenant]))
    assert r.status_code == 202
    return r.json()["capture_id"]


def _tree_hash(path):
    h = hashlib.sha256()
    for p in sorted(path.rglob("*")):
        h.update(str(p.relative_to(path)).encode())
        if p.is_file():
            h.update(p.read_bytes())
    return h.hexdigest()


def test_other_tenant_cannot_read_capture_data(tenants) -> None:
    root, keys = tenants
    cid = _ingest(root, keys, "alpha")
    for path in (f"/api/v1/flows?capture_id={cid}", f"/api/v1/topology?capture_id={cid}"):
        assert client.get(path, headers=_h(keys["alpha"])).status_code == 200
        assert client.get(path, headers=_h(keys["beta"])).status_code == 404
    assert not (tenant_root(root, "beta") / "captures" / cid).exists()


def test_other_tenant_cannot_affect_data(tenants) -> None:
    root, keys = tenants
    cid = _ingest(root, keys, "alpha")
    before = _tree_hash(tenant_root(root, "alpha"))
    # beta tries: ingest alpha's staged file, read/derive alpha's capture id, write its own data
    r = client.post("/api/v1/capture", json={"source": "pcap_upload", "pcap_filename": "a.pcap"}, headers=_h(keys["beta"]))
    assert r.status_code == 422  # not staged in beta's inbox
    client.get(f"/api/v1/topology?capture_id={cid}", headers=_h(keys["beta"]))
    _ingest(root, keys, "beta")
    assert _tree_hash(tenant_root(root, "alpha")) == before


def test_missing_and_invalid_keys_rejected_on_every_route(tenants) -> None:
    _, keys = tenants
    routes = [
        ("get", "/api/v1/flows?capture_id=x"), ("get", "/api/v1/topology?capture_id=x"),
        ("get", "/api/v1/experiments"), ("get", "/api/v1/metrics"), ("get", "/api/v1/anomalies"),
        ("get", "/api/v1/behaviors/n1"), ("get", "/api/v1/dependencies?capture_id=x"),
        ("post", "/api/v1/capture"),
    ]
    for method, path in routes:
        for headers in ({}, _h("wrong"), _h(keys["alpha"][:-1])):
            assert getattr(client, method)(path, headers=headers).status_code == 401, (method, path)


def test_tenant_id_and_path_traversal_rejected(tenants) -> None:
    root, _ = tenants
    for bad in ("../x", "a/b", "", "A", "..", "a" * 80, "x\\y"):
        with pytest.raises(ValueError):
            validate_tenant_id(bad)
        with pytest.raises(ValueError):
            tenant_root(root, bad)
    with pytest.raises(ValueError):
        TenantRegistry(root).create_tenant("alpha")  # duplicate


def test_keys_stored_hashed_only(tenants) -> None:
    root, keys = tenants
    text = (root / "_tenants" / "registry.json").read_text()
    assert all(k not in text for k in keys.values())
    assert set(json.loads(text)) == {"alpha", "beta"}
    assert TenantRegistry(root).resolve_key(keys["beta"]) == "beta"


def test_disabled_mode_unchanged(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NETSCOPE_ARTIFACT_ROOT", str(tmp_path / "a"))
    monkeypatch.delenv("NETSCOPE_TENANCY_ENABLED", raising=False)
    get_settings.cache_clear()
    assert client.get("/api/v1/experiments").status_code == 200
    get_settings.cache_clear()
