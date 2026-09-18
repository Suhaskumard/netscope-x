"""Observatory validation (spec Phase 20).

Before any packet-capture-based inference work begins (spec Phase 21, NETTRACE),
this script re-verifies -- as a single automated, repeatable gate instead of the
one-off manual checks Phases 11-13/15 already performed and wrote up as prose in
docs/architecture/network_laboratory.md and protocol_generation.md -- that the
live multi-tier lab (simulator/docker/docker-compose.yml) actually behaves the
way it is declared to:

  - expected services:     the declared lab (simulator/ground_truth/topology.py)
                            matches docker-compose.yml's real service list.
  - expected connectivity: positive (client->gateway reaches redis/database/
                            external-service through the real dependency chain)
                            AND negative (client/gateway/load-balancer cannot
                            reach out-of-boundary services directly -- Phase 12's
                            own definition of "boundaries actually enforced").
  - expected routes:       the gateway's two real upstream routes
                            (load-balancer/load-balancer-2, Phase 13) are both
                            actually being used.
  - expected traffic:      the lab can still genuinely generate and answer real
                            protocol traffic (Phase 15's senders), not just that
                            containers are running.

This script is inherently Docker-dependent (it must run commands inside the
live lab's network namespaces, exactly like Phase 12/13's manual verification
did) -- there is no existing precedent in this project for a Docker-dependent
pytest fixture, so this stays a standalone script, following the same
argument-free / [PASS]-[FAIL] / non-zero-exit-on-failure convention as
scripts/validate_data_contracts.py and scripts/check_ground_truth_boundary.py.
The pure parsing/decision logic each check reduces to is factored into small
functions covered by simulator/tests/test_observatory_validation.py without
Docker.

Run (with the lab already up -- `docker compose -f simulator/docker/docker-compose.yml up -d`):
    .venv/Scripts/python.exe -m scripts.validate_observatory
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

import yaml

from simulator.ground_truth.generate import check_services_match_compose

COMPOSE_PATH = Path(__file__).resolve().parents[1] / "simulator" / "docker" / "docker-compose.yml"

results: List[Tuple[str, bool, str]] = []


def _record(label: str, ok: bool, detail: str) -> None:
    results.append((label, ok, detail))


# --------------------------------------------------------------- pure helpers --

def _evaluate_reachability_payload(payload: dict) -> Tuple[bool, List[str]]:
    """Given a parsed api.py-shaped JSON dict, returns (all_true, failed_field_names)."""
    fields = ["redis_reachable", "database_reachable", "external_reachable"]
    failed = [f for f in fields if not payload.get(f)]
    return (not failed, failed)


def _parse_upstream_header(curl_head_output: str) -> Optional[str]:
    """Extracts the X-Gateway-Upstream header value from raw `curl -I` output text."""
    match = re.search(r"^X-Gateway-Upstream:\s*(\S+)", curl_head_output, re.IGNORECASE | re.MULTILINE)
    return match.group(1).strip() if match else None


def _summarize_protocol_attempt(record: dict) -> bool:
    """Decides pass/fail for one generate_protocol.py-shaped JSON record, using the
    same fields each protocol sender already reports as its own success signal."""
    if record.get("error"):
        return False
    if "ok" in record:
        return bool(record["ok"])
    if "status_code" in record:
        return record["status_code"] == 200
    if "rcode" in record:
        return record["rcode"] == 0
    return False


# ------------------------------------------------------------------- docker I/O --

def _compose_exec(service: str, args: List[str], timeout: float = 10.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_PATH), "exec", "-T", service, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def load_compose_service_names() -> set[str]:
    with COMPOSE_PATH.open("r", encoding="utf-8") as f:
        compose = yaml.safe_load(f)
    return set(compose["services"].keys())


# ------------------------------------------------------------------------ checks --

def check_expected_services() -> None:
    try:
        check_services_match_compose(load_compose_service_names())
        _record("expected services", True, "ground-truth role declarations match docker-compose.yml")
    except ValueError as exc:
        _record("expected services", False, str(exc))


def check_positive_connectivity() -> None:
    proc = _compose_exec("client", ["curl", "-s", "http://gateway/"])
    if proc.returncode != 0:
        _record("expected connectivity (positive)", False, f"curl failed: {proc.stderr.strip()}")
        return
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        _record("expected connectivity (positive)", False, f"non-JSON response: {exc}: {proc.stdout!r}")
        return
    ok, failed = _evaluate_reachability_payload(payload)
    if ok:
        _record("expected connectivity (positive)", True, f"client->gateway reachability report: {payload}")
    else:
        _record("expected connectivity (positive)", False, f"unreachable fields: {failed} (payload={payload})")


NEGATIVE_CHECKS = [
    ("client", "http://redis:6379/"),
    ("client", "http://database:5432/"),
    ("client", "http://external-service/"),
    ("gateway", "http://redis:6379/"),
    ("load-balancer", "http://redis:6379/"),
]


def check_negative_connectivity() -> None:
    failures = []
    for service, url in NEGATIVE_CHECKS:
        proc = _compose_exec(service, ["curl", "--max-time", "3", "-s", url])
        # A boundary-enforced target must fail to resolve/connect -- curl exits non-zero.
        if proc.returncode == 0:
            failures.append(f"{service}->{url} unexpectedly succeeded")
    if failures:
        _record("expected connectivity (negative/boundary)", False, "; ".join(failures))
    else:
        _record(
            "expected connectivity (negative/boundary)",
            True,
            f"all {len(NEGATIVE_CHECKS)} out-of-boundary targets correctly unreachable",
        )


def check_expected_routes(attempts: int = 6) -> None:
    upstreams = []
    for _ in range(attempts):
        proc = _compose_exec("client", ["curl", "-sI", "http://gateway/"])
        if proc.returncode != 0:
            continue
        upstream = _parse_upstream_header(proc.stdout)
        if upstream:
            upstreams.append(upstream)
    distinct = sorted(set(upstreams))
    if len(distinct) >= 2:
        _record("expected routes", True, f"observed {attempts} requests alternate across upstreams: {distinct}")
    elif len(distinct) == 1:
        _record(
            "expected routes",
            False,
            f"only one upstream observed across {attempts} requests: {distinct} "
            "(load-balancer-2 may be down, or failover already occurred)",
        )
    else:
        _record("expected routes", False, f"no X-Gateway-Upstream header observed in {attempts} attempts")


TRAFFIC_SMOKE_CHECKS = [
    # (container, protocol, host, port)
    ("client", "dns", "dns", 53),
    ("client", "http", "gateway", 80),
    ("api-1", "cache", "redis", 6379),
    ("api-1", "database", "database", 5432),
    ("api-1", "tls", "external-service", 443),
]


def check_expected_traffic() -> None:
    failures = []
    successes = []
    for service, protocol, host, port in TRAFFIC_SMOKE_CHECKS:
        proc = _compose_exec(
            service,
            [
                "python3",
                "-m",
                "simulator.traffic.generate_protocol",
                "--protocol",
                protocol,
                "--host",
                host,
                "--port",
                str(port),
                "--count",
                "1",
                "--interval",
                "0",
                "--out",
                f"/tmp/observatory_{protocol}.jsonl",
            ],
            timeout=15.0,
        )
        if proc.returncode != 0:
            failures.append(f"{service}/{protocol}: generator exited {proc.returncode}: {proc.stderr.strip()}")
            continue
        cat = _compose_exec(service, ["cat", f"/tmp/observatory_{protocol}.jsonl"])
        record = None
        for line in cat.stdout.strip().splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
        if record is None or not _summarize_protocol_attempt(record):
            failures.append(f"{service}/{protocol}: attempt did not report success (record={record})")
        else:
            successes.append(f"{service}/{protocol}")
    if failures:
        _record("expected traffic", False, "; ".join(failures))
    else:
        _record("expected traffic", True, f"real traffic generated and answered for: {successes}")


def main() -> int:
    check_expected_services()
    check_positive_connectivity()
    check_negative_connectivity()
    check_expected_routes()
    check_expected_traffic()

    passed = 0
    failed = 0
    for label, ok, detail in results:
        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        else:
            failed += 1
        print(f"[{status}] {label}: {detail}")
    print(f"\n{passed} passed, {failed} failed, {len(results)} total")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
