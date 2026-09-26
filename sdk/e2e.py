"""Real end-to-end SDK run against a live server (spec Phase 96). Shared by `scripts/run_sdk_e2e.py` and the tests.

Nothing is mocked: a real uvicorn process, real sockets, a real pcap. Each SDK's answers are compared with (a) a raw
`httpx` request to the same server and (b) the backend functions called directly on the same artifacts.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from sdk.live_server import REPO, live_server, write_real_pcap

sys.path.insert(0, str(REPO / "sdk" / "python"))
from netscope_client import (  # noqa: E402
    AuthenticationError, AuthorizationError, NetscopeClient, NotFoundError, NotImplementedOnServer, ValidationError,
)

WINDOW = ("2020-01-01T00:00:00Z", "2030-01-01T00:00:00Z")
NODE = shutil.which("node")


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class Report:
    checks: List[Check] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append(Check(name, bool(ok), detail))

    @property
    def passed(self) -> int:
        return sum(c.ok for c in self.checks)

    def format(self) -> str:
        lines = [f"{'PASS' if c.ok else 'FAIL'}  {c.name}" + (f"  [{c.detail}]" if c.detail and not c.ok else "")
                 for c in self.checks]
        lines.append(f"\n{self.passed}/{len(self.checks)} checks passed")
        return "\n".join(lines)


_VOLATILE = {"generated_at", "computed_at"}  # stamped with the wall clock on every recompute


def stable(o: Any) -> Any:
    """Drops wall-clock stamps the server recomputes per request; everything else must match exactly."""
    if isinstance(o, dict):
        return {k: stable(v) for k, v in o.items() if k not in _VOLATILE}
    if isinstance(o, list):
        return [stable(v) for v in o]
    return o


def _raw(base: str, path: str, headers: Optional[Dict[str, str]] = None, **params: Any) -> httpx.Response:
    return httpx.get(f"{base}/api/v1{path}", params=params, headers=headers or {}, timeout=60)


def run_js(base: str, pcap: str = "", **env: str) -> Dict[str, Any]:
    e = dict(os.environ, NS_BASE=base, NS_PCAP=pcap, **env)
    r = subprocess.run([NODE, str(REPO / "sdk" / "javascript" / "e2e.mjs")], env=e, capture_output=True, text=True,
                       timeout=180)
    if r.returncode != 0:
        raise RuntimeError(f"JS SDK run failed:\n{r.stderr[-2000:]}")
    return json.loads(r.stdout)


def open_mode(work: Path, rep: Report) -> None:
    """Auth and tenancy off: exactly today's behaviour."""
    write_real_pcap(work / "inbox" / "t.pcap")
    with live_server(work / "art", work / "inbox") as base:
        py = NetscopeClient(base)
        acc = py.upload_pcap("t.pcap")
        cid = acc["capture_id"]
        rep.add("py: capture accepted with packets", acc["status"] == "accepted" and acc["packet_count"] == 72, str(acc))

        raw_acc = httpx.post(f"{base}/api/v1/capture", json={"source": "pcap_upload", "pcap_filename": "t.pcap"})
        rep.add("raw httpx POST /capture matches SDK response shape",
                raw_acc.status_code == 202 and set(raw_acc.json()) == set(acc))

        flows = py.flows(cid)
        rf = _raw(base, "/flows", capture_id=cid).json()
        rep.add("py: flows == raw httpx", flows == rf and flows["total"] > 0)
        rep.add("py: paginate(flows) yields every flow", len(list(py.paginate("flows", cid, page_size=2))) == flows["total"])
        topo = py.topology(cid)
        rep.add("py: topology == raw httpx (ignoring generated_at)",
                stable(topo) == stable(_raw(base, "/topology", capture_id=cid).json()) and bool(topo["edges"]))
        deps = py.dependencies(cid)
        rep.add("py: dependencies == raw httpx", deps == _raw(base, "/dependencies", capture_id=cid).json())
        if deps["items"]:
            did = deps["items"][0]["dependency_id"]
            rep.add("py: causal == raw httpx (ignoring computed_at)",
                    stable(py.causal(did, cid)) == stable(_raw(base, f"/causal/{did}", capture_id=cid).json()))
        hist = py.history(cid, *WINDOW)
        rep.add("py: history == raw httpx", hist == _raw(base, "/history", capture_id=cid, start=WINDOW[0], end=WINDOW[1]).json())
        rep.add("py: experiments/metrics == raw httpx",
                py.experiments() == _raw(base, "/experiments").json() and py.metrics() == _raw(base, "/metrics").json())

        # values equal the backend called directly on the artifacts the server wrote
        from backend.nettrace.reconstruct import reconstruct_flows

        direct = reconstruct_flows(work / "art", cid)
        rep.add("py: flow count == backend reconstruct_flows on the same artifacts", len(direct) == flows["total"])

        for name, fn, cls in (
            ("404 -> NotFoundError", lambda: py.flows("no_such_capture"), NotFoundError),
            ("422 -> ValidationError", lambda: py.flows("../bad"), ValidationError),
            ("501 -> NotImplementedOnServer", lambda: py.anomalies(), NotImplementedOnServer),
            ("causal 404 -> NotFoundError", lambda: py.causal("nope", cid), NotFoundError),
        ):
            try:
                fn()
                rep.add(f"py: {name}", False, "no exception")
            except cls as exc:
                rep.add(f"py: {name} (error/request_id populated)", bool(exc.error and exc.request_id), str(exc))
            except Exception as exc:  # noqa: BLE001
                rep.add(f"py: {name}", False, repr(exc))

        if NODE:
            js = run_js(base, pcap="t.pcap")
            rep.add("js: flows == python SDK on the JS-created capture",
                    js["flows"]["total"] == flows["total"] and js["topology"]["edges"] and
                    len(js["topology"]["edges"]) == len(topo["edges"]))
            rep.add("js: paginate(flows) yields every flow", len(js["flowsAll"]) == js["flows"]["total"])
            jc = NetscopeClient(base)
            rep.add("js: results equal python SDK for the same capture",
                    js["flows"] == jc.flows(js["captureId"]) and js["dependencies"] == jc.dependencies(js["captureId"])
                    and stable(js["topology"]) == stable(jc.topology(js["captureId"])))
            rep.add("js: error classes map to same statuses",
                    js["errors"] == {"notFound": "NotFoundError:404:capture_not_found",
                                     "validation": "ValidationError:422:validation_error",
                                     "notImplemented": "NotImplementedOnServer:501:not_implemented",
                                     "causalMissing": "NotFoundError:404:dependency_not_found"}, str(js["errors"]))
        else:
            rep.add("js: node available", False, "node not found on PATH")


def secured_mode(work: Path, rep: Report) -> None:
    """Auth + tenancy on: credentials, roles and tenant isolation through the SDKs."""
    from backend.app.auth.store import CredentialStore
    from backend.app.tenancy.store import TenantRegistry

    art = work / "art"
    tenants = TenantRegistry(art)
    tenants.create_tenant("acme")
    tenants.create_tenant("globex")
    store = CredentialStore(art)
    tok_a = store.create("a-op", "operator", tenant_id="acme")
    tok_a_reader = store.create("a-rd", "reader", tenant_id="acme")
    tok_b = store.create("b-op", "operator", tenant_id="globex")
    from backend.app.tenancy.paths import tenant_inbox

    write_real_pcap(tenant_inbox(art, "acme") / "t.pcap")
    env = {"NETSCOPE_AUTH_ENABLED": "true", "NETSCOPE_TENANCY_ENABLED": "true"}
    with live_server(art, work / "inbox", env) as base:
        anon = NetscopeClient(base)
        try:
            anon.experiments()
            rep.add("secured: no token -> AuthenticationError", False, "no exception")
        except AuthenticationError as exc:
            rep.add("secured: no token -> AuthenticationError", exc.status == 401)
        try:
            NetscopeClient(base, token="wrong").experiments()
            rep.add("secured: bad token -> AuthenticationError", False)
        except AuthenticationError:
            rep.add("secured: bad token -> AuthenticationError", True)

        a, b = NetscopeClient(base, token=tok_a), NetscopeClient(base, token=tok_b)
        cid = a.upload_pcap("t.pcap")["capture_id"]
        rep.add("secured: tenant acme reads its own capture", a.flows(cid)["total"] > 0)
        try:
            NetscopeClient(base, token=tok_a_reader).upload_pcap("t.pcap")
            rep.add("secured: reader POST -> AuthorizationError", False, "no exception")
        except AuthorizationError as exc:
            rep.add("secured: reader POST -> AuthorizationError", exc.status == 403)
        rep.add("secured: reader GET allowed", NetscopeClient(base, token=tok_a_reader).flows(cid)["total"] > 0)
        try:
            b.flows(cid)
            rep.add("secured: tenant globex cannot read acme's capture", False, "read succeeded")
        except NotFoundError:
            rep.add("secured: tenant globex cannot read acme's capture (NotFoundError)", True)
        rep.add("secured: globex sees none of acme's experiments/captures", b.experiments()["total"] == 0)

        if NODE:
            js = run_js(base, pcap="t.pcap", NS_TOKEN=tok_a)
            rep.add("js secured: acme token works end to end", js["flows"]["total"] > 0)
            try:
                run_js(base, NS_TOKEN=tok_b, NS_CAPTURE_ID=cid)
                rep.add("js secured: globex token cannot read acme capture", False, "read succeeded")
            except RuntimeError as exc:
                rep.add("js secured: globex token cannot read acme capture", "NotFoundError" in str(exc))
            try:
                run_js(base, pcap="t.pcap")
                rep.add("js secured: no token rejected", False, "succeeded")
            except RuntimeError as exc:
                rep.add("js secured: no token rejected", "AuthenticationError" in str(exc))


def run_all(scratch: Path) -> Report:
    rep = Report()
    for name, fn in (("open", open_mode), ("secured", secured_mode)):
        work = scratch / name
        work.mkdir(parents=True, exist_ok=True)
        fn(work, rep)
    return rep
