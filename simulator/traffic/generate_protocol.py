"""Protocol workload generator CLI (spec Phase 15).

Runs a fixed-count loop of one real protocol sender (simulator/traffic/protocols.py)
at a configurable interval, logging one JSON-Lines record per attempt -- same
convention as Phase 14's generate.py.

Run (from a container that can reach the target -- see
docs/architecture/protocol_generation.md for which container reaches which
protocol's target, per the Phase 12 network segmentation):
    python3 -m simulator.traffic.generate_protocol --protocol dns \\
        --host dns --count 5 --interval 1 --out /tmp/dns.jsonl
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from simulator.traffic import protocols as P

DEFAULT_PORTS = {
    "http": 80,
    "tcp": 80,
    "dns": 53,
    "cache": 6379,
    "database": 5432,
    "tls": 443,
}


def _send(protocol: str, host: str, port: int, name: str) -> Dict[str, Any]:
    if protocol == "http":
        return P.http_get(f"http://{host}:{port}/")
    if protocol == "tcp":
        return P.tcp_raw_connect(host, port)
    if protocol == "dns":
        return P.dns_query(name, host, port)
    if protocol == "cache":
        return P.redis_ping(host, port)
    if protocol == "database":
        return P.postgres_ssl_request(host, port)
    if protocol == "tls":
        return P.tls_handshake(host, port)
    raise ValueError(f"unknown protocol: {protocol!r}; expected one of {sorted(DEFAULT_PORTS)}")


def run(
    protocol: str,
    host: str,
    port: int,
    name: str,
    count: int,
    interval: float,
    out_path: Path,
) -> int:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sent = 0
    with out_path.open("w", encoding="utf-8") as f:
        for seq in range(count):
            result = _send(protocol, host, port, name)
            record = {
                "protocol": protocol,
                "host": host,
                "port": port,
                "sequence": seq,
                "sent_at": datetime.now(timezone.utc).isoformat(),
                **result,
            }
            f.write(json.dumps(record))
            f.write("\n")
            f.flush()
            sent += 1
            if seq < count - 1:
                time.sleep(interval)
    return sent


def main() -> None:
    parser = argparse.ArgumentParser(description="NETSCOPE-X protocol workload generator")
    parser.add_argument("--protocol", required=True, choices=sorted(DEFAULT_PORTS))
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=None, help="Defaults per-protocol if omitted.")
    parser.add_argument("--name", default="example.lab", help="Query name -- only used by --protocol dns.")
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    port = args.port if args.port is not None else DEFAULT_PORTS[args.protocol]
    sent = run(args.protocol, args.host, port, args.name, args.count, args.interval, args.out)
    print(f"{sent} {args.protocol} requests sent to {args.host}:{port} -> {args.out}")


if __name__ == "__main__":
    main()
