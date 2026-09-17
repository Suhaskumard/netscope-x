"""Minimal multi-tier lab API service (spec Phase 11).

Stdlib-only on purpose -- this is a lab fixture, not product code. On
GET /, performs REAL reachability checks against redis, database, and
external-service and reports them as JSON, so the multi-tier dependency
structure is genuinely observable end-to-end rather than merely declared
in the compose file.
"""

from __future__ import annotations

import json
import os
import socket
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

APP_NAME = os.environ.get("APP_NAME", "api")
REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
DATABASE_HOST = os.environ.get("DATABASE_HOST", "database")
DATABASE_PORT = int(os.environ.get("DATABASE_PORT", "5432"))
EXTERNAL_URL = os.environ.get("EXTERNAL_URL", "http://external-service/")


def check_tcp(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def check_http(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 (lab-internal URL only)
            return resp.status == 200
    except Exception:
        return False


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler API)
        payload = {
            "service": APP_NAME,
            "redis_reachable": check_tcp(REDIS_HOST, REDIS_PORT),
            "database_reachable": check_tcp(DATABASE_HOST, DATABASE_PORT),
            "external_reachable": check_http(EXTERNAL_URL),
        }
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        # Keep default stderr access logging (visible via `docker compose logs`)
        # but route through print for consistent container log formatting.
        print(f"[{APP_NAME}] {self.address_string()} - {format % args}", flush=True)


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 5000), Handler).serve_forever()
