"""Generic scenario node (spec Phase 18).

Every generated scenario (simple chain, star, multi-tier, redundant, multi-path, dynamic service
network) is deployed using this SAME image -- the one reusable building block none of the 6
bespoke services in simulator/docker/ provide today (each of those hardcodes its specific peer
hostnames). This node instead reads its role and its upstream dependencies from environment
variables set per-service in the generated docker-compose.yml (simulator/scenarios/compose.py),
and reports real, live reachability to each of them -- the same kind of check
simulator/docker/api.py hand-writes for its two fixed dependencies (redis, database), but
data-driven instead of hardcoded.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

NODE_ROLE = os.environ.get("NODE_ROLE", "unknown")
UPSTREAM_HOSTS = [h.strip() for h in os.environ.get("UPSTREAM_HOSTS", "").split(",") if h.strip()]
PORT = 8080


def _check_reachable(host: str) -> bool:
    try:
        with urllib.request.urlopen(f"http://{host}:{PORT}/", timeout=2) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 -- BaseHTTPRequestHandler's naming convention
        body = json.dumps(
            {
                "node_role": NODE_ROLE,
                "upstream_hosts": UPSTREAM_HOSTS,
                "reachability": {host: _check_reachable(host) for host in UPSTREAM_HOSTS},
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass  # keep container logs quiet; this is a controlled-lab utility, not a production service


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    server.serve_forever()
