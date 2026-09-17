"""Traffic generator execution + CLI (spec Phase 14).

Takes a deterministic schedule from patterns.py and actually executes it
in real time against a real target: sleeps to each scheduled offset,
issues a real HTTP GET, and appends one JSON-Lines record per executed
request. Only the *schedule* is reproducible (spec Phase 14's acceptance
bar) -- real wall-clock execution timing and the target's real responses
are not, and this module never claims otherwise.

Run (from inside the lab, e.g. the `client` container which has network
access to `gateway`):
    python3 -m simulator.traffic.generate --pattern normal --seed 42 \\
        --duration 10 --target http://gateway/ --out /tmp/normal.jsonl
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from simulator.traffic.patterns import PATTERNS, generate_schedule


def _send_request(url: str, timeout_seconds: float = 5.0) -> Dict[str, Any]:
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=timeout_seconds) as resp:  # noqa: S310 (lab-internal target only)
            status_code = resp.status
            error = None
    except urllib.error.HTTPError as exc:
        status_code = exc.code
        error = None
    except Exception as exc:  # noqa: BLE001 -- record any failure, never crash the run
        status_code = None
        error = f"{type(exc).__name__}: {exc}"
    latency_ms = (time.perf_counter() - start) * 1000.0
    return {"status_code": status_code, "error": error, "latency_ms": latency_ms}


def run(pattern: str, seed: int, duration_seconds: float, target: str, out_path: Path) -> int:
    """Executes the pattern's schedule in real time. Returns the number of requests sent."""
    schedule = generate_schedule(pattern, seed, duration_seconds)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    run_start = time.perf_counter()
    sent = 0
    with out_path.open("w", encoding="utf-8") as f:
        for seq, event in enumerate(schedule):
            now = time.perf_counter() - run_start
            sleep_for = event.offset_seconds - now
            if sleep_for > 0:
                time.sleep(sleep_for)

            result = _send_request(target)
            record = {
                "pattern": pattern,
                "seed": seed,
                "sequence": seq,
                "group_id": event.group_id,
                "retry_of": event.retry_of,
                "scheduled_offset_seconds": event.offset_seconds,
                "sent_at": datetime.now(timezone.utc).isoformat(),
                "target": target,
                **result,
            }
            f.write(json.dumps(record))
            f.write("\n")
            f.flush()
            sent += 1
    return sent


def main() -> None:
    parser = argparse.ArgumentParser(description="NETSCOPE-X reproducible traffic workload generator")
    parser.add_argument("--pattern", required=True, choices=PATTERNS)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--duration", type=float, required=True, help="Duration in seconds.")
    parser.add_argument("--target", required=True, help="URL to send requests to, e.g. http://gateway/")
    parser.add_argument("--out", required=True, type=Path, help="Output JSON-Lines log path.")
    args = parser.parse_args()

    sent = run(args.pattern, args.seed, args.duration, args.target, args.out)
    print(f"{sent} requests sent for pattern={args.pattern!r} seed={args.seed} -> {args.out}")


if __name__ == "__main__":
    main()
