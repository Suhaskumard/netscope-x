"""Phase 92 authentication/authorization tests: every /api/v1 route enumerated from the live app."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from scapy.all import IP, TCP, wrpcap

from backend.app.auth.store import CredentialStore
from backend.app.core.config import get_settings
from backend.app.main import app
from backend.app.tenancy.paths import tenant_inbox
from backend.app.tenancy.store import TenantRegistry

client = TestClient(app)


def _api_routes():
    out = []
    for r in app.routes:
        if isinstance(r, APIRoute) and r.path.startswith("/api/v1"):
            path = r.path.replace("{", "").replace("}", "")  # path params -> literal
            path = path.replace("capture_id", "x").replace("node_id", "x").replace("dependency_id", "x")
            for m in r.methods - {"HEAD", "OPTIONS"}:
                out.append((m.lower(), path))
    return out


ROUTES = _api_routes()


def _bearer(t):
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture()
def auth(tmp_path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "artifacts"
    monkeypatch.setenv("NETSCOPE_ARTIFACT_ROOT", str(root))
    monkeypatch.setenv("NETSCOPE_UPLOAD_STAGING_DIR", str(tmp_path / "inbox"))
    monkeypatch.setenv("NETSCOPE_AUTH_ENABLED", "true")
    get_settings.cache_clear()
    store = CredentialStore(root)
    yield root, store
    get_settings.cache_clear()


def test_route_enumeration_is_nonempty() -> None:
    assert len(ROUTES) >= 12
    assert ("post", "/api/v1/capture") in ROUTES


@pytest.mark.parametrize("method,path", ROUTES)
def test_unauthenticated_rejected_on_every_route(auth, method, path) -> None:
    _, store = auth
    tok = store.create("r", "reader")
    for headers in ({}, {"Authorization": "Basic abc"}, {"Authorization": "Bearer"}, _bearer("nope"), _bearer(tok[:-1])):
        r = getattr(client, method)(path, headers=headers)
        assert r.status_code == 401, (method, path, headers)
        assert r.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize("method,path", [(m, p) for m, p in ROUTES if m != "get"])
def test_reader_forbidden_on_write_routes(auth, method, path) -> None:
    _, store = auth
    tok = store.create("r", "reader")
    assert getattr(client, method)(path, headers=_bearer(tok)).status_code == 403


@pytest.mark.parametrize("method,path", [(m, p) for m, p in ROUTES if m == "get"])
def test_reader_passes_auth_on_read_routes(auth, method, path) -> None:
    _, store = auth
    tok = store.create("r", "reader")
    assert client.get(path, headers=_bearer(tok)).status_code not in (401, 403)


def test_operator_passes_auth_on_write_routes(auth) -> None:
    _, store = auth
    tok = store.create("o", "operator")
    for method, path in ROUTES:
        if method != "get":
            assert getattr(client, method)(path, headers=_bearer(tok)).status_code not in (401, 403)


def test_revoked_and_expired_credentials_rejected(auth) -> None:
    _, store = auth
    revoked = store.create("rev", "operator")
    store.revoke("rev")
    expired = store.create("exp", "operator", expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    valid = store.create("ok", "operator", expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
    assert client.get("/api/v1/experiments", headers=_bearer(revoked)).status_code == 401
    assert client.get("/api/v1/experiments", headers=_bearer(expired)).status_code == 401
    assert client.get("/api/v1/experiments", headers=_bearer(valid)).status_code == 200


def test_tokens_stored_hashed(auth) -> None:
    root, store = auth
    tok = store.create("a", "reader")
    assert tok not in (root / "_auth" / "credentials.json").read_text()


def test_authenticated_behaves_identically_to_unauthenticated_mode(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NETSCOPE_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("NETSCOPE_UPLOAD_STAGING_DIR", str(tmp_path / "inbox"))
    (tmp_path / "inbox").mkdir()
    wrpcap(str(tmp_path / "inbox" / "a.pcap"), [IP(src="10.0.0.1", dst="10.0.0.2") / TCP(sport=1, dport=80)] * 3)

    def run(headers):
        made = client.post("/api/v1/capture", json={"source": "pcap_upload", "pcap_filename": "a.pcap"}, headers=headers)
        cid = made.json()["capture_id"]
        outs = [made.status_code, made.json()["packet_count"]]
        for path in (f"/api/v1/flows?capture_id={cid}", f"/api/v1/topology?capture_id={cid}", "/api/v1/experiments",
                     "/api/v1/flows?capture_id=missing", "/api/v1/anomalies"):
            r = client.get(path, headers=headers)
            body = r.json()
            body.pop("request_id", None)
            body.pop("generated_at", None)  # wall-clock, differs per call
            outs.append((r.status_code, str(body).replace(cid, "CID")))
        return outs

    monkeypatch.delenv("NETSCOPE_AUTH_ENABLED", raising=False)
    get_settings.cache_clear()
    off = run({})
    monkeypatch.setenv("NETSCOPE_AUTH_ENABLED", "true")
    get_settings.cache_clear()
    tok = CredentialStore(tmp_path / "artifacts").create("o", "operator")
    on = run(_bearer(tok))
    get_settings.cache_clear()
    assert on == off


def test_credential_tenant_binding_overrides_header(tmp_path, monkeypatch) -> None:
    root = tmp_path / "artifacts"
    monkeypatch.setenv("NETSCOPE_ARTIFACT_ROOT", str(root))
    monkeypatch.setenv("NETSCOPE_AUTH_ENABLED", "true")
    monkeypatch.setenv("NETSCOPE_TENANCY_ENABLED", "true")
    get_settings.cache_clear()
    reg = TenantRegistry(root)
    reg.create_tenant("alpha")
    beta_key = reg.create_tenant("beta")
    wrpcap(str(tenant_inbox(root, "alpha") / "a.pcap"), [IP(src="10.0.0.1", dst="10.0.0.2") / TCP(sport=1, dport=80)] * 3)
    store = CredentialStore(root)
    a_tok = store.create("a", "operator", tenant_id="alpha")
    unbound = store.create("u", "operator")
    r = client.post("/api/v1/capture", json={"source": "pcap_upload", "pcap_filename": "a.pcap"},
                    headers={**_bearer(a_tok), "X-Tenant-Key": beta_key})  # header ignored: still alpha
    assert r.status_code == 202
    assert (root / "tenants" / "alpha" / "captures" / r.json()["capture_id"]).exists()
    assert client.get("/api/v1/experiments", headers=_bearer(unbound)).status_code == 401  # not bound to a tenant
    get_settings.cache_clear()
