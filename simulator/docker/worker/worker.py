"""Minimal lab worker (spec Phase 11).

A background network participant (no exposed port), with real dependency
edges to redis and database -- periodically checks both and logs a
heartbeat, so the topology includes a node that only ever initiates
connections outward.
"""

from __future__ import annotations

import os
import socket
import time

REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
DATABASE_HOST = os.environ.get("DATABASE_HOST", "database")
DATABASE_PORT = int(os.environ.get("DATABASE_PORT", "5432"))
INTERVAL_SECONDS = float(os.environ.get("WORKER_INTERVAL_SECONDS", "5"))


def check_tcp(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


if __name__ == "__main__":
    while True:
        redis_ok = check_tcp(REDIS_HOST, REDIS_PORT)
        db_ok = check_tcp(DATABASE_HOST, DATABASE_PORT)
        print(f"worker heartbeat: redis_reachable={redis_ok} database_reachable={db_ok}", flush=True)
        time.sleep(INTERVAL_SECONDS)
