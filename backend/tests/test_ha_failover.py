"""Phase 93: real failover between two real uvicorn processes (no mocks).

Instance A writes to root A and mirrors into root B; instance B writes to B and mirrors into A. A is hard-killed
(TerminateProcess/SIGKILL) while a request is mid-replication.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from scapy.all import IP, TCP, wrpcap

REPO = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Instance:
    def __init__(self, name, root: Path, replica: Path, inbox: Path, delay: float) -> None:
        self.name, self.port = name, _free_port()
        self.env = {
            **os.environ,
            "PYTHONPATH": str(REPO),
            "NETSCOPE_ARTIFACT_ROOT": str(root),
            "NETSCOPE_UPLOAD_STAGING_DIR": str(inbox),
            "NETSCOPE_REPLICA_ROOTS": str(replica),
            "NETSCOPE_REPLICATION_COMMIT_DELAY_SECONDS": str(delay),
            "NETSCOPE_LOG_LEVEL": "WARNING",
        }
        self.proc = None

    def start(self) -> None:
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "backend.app.main:app", "--port", str(self.port), "--log-level", "warning"],
            cwd=REPO, env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                urllib.request.urlopen(self.url("/health"), timeout=1).read()
                return
            except OSError:
                time.sleep(0.2)
        raise RuntimeError(f"instance {self.name} did not start")

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def kill(self) -> None:
        self.proc.kill()
        self.proc.wait()

    def get(self, path: str):
        try:
            with urllib.request.urlopen(self.url(path), timeout=30) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def ingest(self, filename: str):
        req = urllib.request.Request(
            self.url("/api/v1/capture"), method="POST", headers={"Content-Type": "application/json"},
            data=json.dumps({"source": "pcap_upload", "pcap_filename": filename}).encode(),
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read())


def _tree(root: Path, sub: str) -> dict[str, str]:
    base = root / sub
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(base.rglob("*")) if p.is_file()}


def _covers(src: dict, dst: dict) -> bool:
    """dst holds every file of src, byte-identical (dst may add regenerable derived files, e.g. flows.jsonl)."""
    return bool(src) and all(dst.get(k) == v for k, v in src.items())


@pytest.fixture()
def pair(tmp_path):
    a_root, b_root = tmp_path / "A", tmp_path / "B"
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    for name, n in (("one.pcap", 3), ("two.pcap", 4), ("three.pcap", 5)):
        wrpcap(str(inbox / name), [IP(src="10.0.0.1", dst="10.0.0.2") / TCP(sport=1234, dport=80) for _ in range(n)])
    a = Instance("A", a_root, b_root, inbox, delay=0.6)
    b = Instance("B", b_root, a_root, inbox, delay=0.0)
    a.start()
    b.start()
    yield a, b, a_root, b_root
    for i in (a, b):
        if i.proc and i.proc.poll() is None:
            i.kill()


def test_kill_mid_request_loses_no_data_and_corrupts_nothing(pair) -> None:
    a, b, a_root, b_root = pair

    # 1. An acknowledged write on A is already on B when A answers.
    status, body = a.ingest("one.pcap")
    assert status == 202
    c1 = body["capture_id"]
    assert _covers(_tree(a_root, f"captures/{c1}"), _tree(b_root, f"captures/{c1}"))
    flows_before = b.get(f"/api/v1/flows?capture_id={c1}")
    assert flows_before[0] == 200

    # 2. A second write on A is killed while it is replicating.
    outcome: dict = {}

    def slow():
        try:
            outcome["result"] = a.ingest("two.pcap")
        except Exception as exc:  # connection dropped by the kill
            outcome["error"] = exc

    t = threading.Thread(target=slow)
    t.start()
    # Kill the moment the first file of the in-flight capture lands on B: A is mid-commit, second file not yet copied.
    deadline = time.time() + 30
    while time.time() < deadline:
        landed = [p for p in (b_root / "captures").glob("*/raw.pcap") if p.parent.name != c1]
        if landed:
            break
        time.sleep(0.005)
    a.kill()
    t.join(30)
    assert "result" not in outcome, "the killed request must not have been acknowledged"

    # 3. B (the surviving instance) still serves everything that was acknowledged, byte-identically.
    assert b.get(f"/api/v1/flows?capture_id={c1}") == flows_before
    assert _covers(_tree(a_root, f"captures/{c1}"), _tree(b_root, f"captures/{c1}"))

    # 4. Nothing on B is half-written: no temp files, and every file that exists on B equals A's primary copy.
    assert not list(b_root.rglob("*.tmp-repl"))
    inflight = [d.name for d in (a_root / "captures").iterdir() if d.name != c1]
    assert len(inflight) == 1
    c2 = inflight[0]
    a_files, b_files = _tree(a_root, f"captures/{c2}"), _tree(b_root, f"captures/{c2}")
    assert all(a_files[k] == v for k, v in b_files.items())
    assert set(b_files) == {f"captures/{c2}/raw.pcap"}, "kill should land between the two replicated files"

    # 5. B keeps accepting work while A is down.
    status, body = b.ingest("three.pcap")
    assert status == 202 and b.get(f"/api/v1/flows?capture_id={body['capture_id']}")[0] == 200

    # 6. Restarting A repairs: both roots converge and the interrupted capture is complete and servable on both.
    a.start()
    assert _covers(_tree(a_root, f"captures/{c2}"), _tree(b_root, f"captures/{c2}"))
    assert set(_tree(b_root, f"captures/{c2}")) >= {f"captures/{c2}/raw.pcap", f"captures/{c2}/manifest.json"}
    assert b.get(f"/api/v1/flows?capture_id={c2}")[0] == 200
    assert a.get(f"/api/v1/flows?capture_id={body['capture_id']}")[0] == 200  # B's write reached A too
