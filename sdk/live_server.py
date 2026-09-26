"""Starts a REAL `uvicorn backend.app.main:app` subprocess for the SDK tests and `scripts/run_sdk_e2e.py`.

No TestClient and no mocked transport: the SDKs talk to it over a real TCP socket.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterator, Optional

REPO = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def write_real_pcap(path: Path, hosts: int = 4, rounds: int = 12) -> None:
    """A real pcap (scapy): a chain h1->h2->h3->... with request/response TCP traffic at increasing times."""
    from scapy.all import IP, TCP, wrpcap

    path.parent.mkdir(parents=True, exist_ok=True)
    packets = []
    t = 1_767_225_600.0  # 2026-01-01T00:00:00Z
    for r in range(rounds):
        for h in range(1, hosts):
            a, b = f"10.0.0.{h}", f"10.0.0.{h + 1}"
            for src, dst, sp, dp in ((a, b, 40000 + h, 80), (b, a, 80, 40000 + h)):
                p = IP(src=src, dst=dst) / TCP(sport=sp, dport=dp, flags="PA")
                p.time = t
                t += 0.01
                packets.append(p)
        t += 0.5
    wrpcap(str(path), packets)


@contextmanager
def live_server(artifact_root: Path, inbox: Path, extra_env: Optional[Dict[str, str]] = None) -> Iterator[str]:
    port = free_port()
    artifact_root.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update({"NETSCOPE_ARTIFACT_ROOT": str(artifact_root), "NETSCOPE_UPLOAD_STAGING_DIR": str(inbox),
                "PYTHONPATH": str(REPO), "PYTHONUNBUFFERED": "1"})
    env.update(extra_env or {})
    log = open(artifact_root.parent / f"server-{port}.log", "wb")  # never a PIPE: an unread pipe fills and blocks the server
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", str(port),
         "--log-level", "warning"],
        cwd=REPO, env=env, stdout=log, stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 60
        while True:
            if proc.poll() is not None:
                log.flush()
                raise RuntimeError("server exited early:\n" + (artifact_root.parent / f"server-{port}.log").read_text(errors="replace")[-3000:])
            try:
                urllib.request.urlopen(base + "/openapi.json", timeout=1).read()
                break
            except Exception:  # noqa: BLE001 - not up yet
                if time.time() > deadline:
                    raise RuntimeError("server did not become ready")
                time.sleep(0.2)
        yield base
    finally:
        log.close()
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
