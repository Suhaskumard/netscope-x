"""Phase 96 client SDK tests. The end-to-end run uses a REAL uvicorn process and real sockets (no TestClient, no mocks)."""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from sdk.e2e import NODE, run_all

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sdk" / "python"))
from netscope_client import NetscopeClient, ServerError  # noqa: E402


@pytest.mark.skipif(NODE is None, reason="node not on PATH: the JavaScript SDK cannot be exercised")
def test_both_sdks_against_a_real_running_server(tmp_path) -> None:
    report = run_all(tmp_path)
    failed = [c for c in report.checks if not c.ok]
    assert not failed, report.format()
    assert len(report.checks) >= 28


class _Flaky(BaseHTTPRequestHandler):
    hits = {"GET": 0, "POST": 0}
    fail_first = 2

    def _reply(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        _Flaky.hits["GET"] += 1
        if _Flaky.hits["GET"] <= _Flaky.fail_first:
            self._reply(503, {"error": "unavailable", "detail": "warming up", "request_id": "r1"})
        else:
            self._reply(200, {"items": [], "limit": 50, "offset": 0, "total": 0})

    def do_POST(self) -> None:  # noqa: N802
        _Flaky.hits["POST"] += 1
        self._reply(503, {"error": "unavailable", "detail": "down", "request_id": "r2"})

    def log_message(self, *a) -> None:  # noqa: D401
        pass


def test_python_sdk_retries_idempotent_reads_only() -> None:
    _Flaky.hits = {"GET": 0, "POST": 0}
    srv = HTTPServer(("127.0.0.1", 0), _Flaky)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        c = NetscopeClient(f"http://127.0.0.1:{srv.server_port}", retries=2, backoff=0.01)
        assert c.experiments()["total"] == 0 and _Flaky.hits["GET"] == 3  # two 503s retried, third succeeds
        with pytest.raises(ServerError) as exc:
            c.upload_pcap("x.pcap")
        assert _Flaky.hits["POST"] == 1 and exc.value.request_id == "r2"  # writes are never retried
    finally:
        srv.shutdown()
