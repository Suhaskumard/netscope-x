"""Traffic replay engine (spec Phase 19).

Takes a recorded JSON-Lines workload log -- either a Phase 14 pattern-generator
log (`generate.py`) or a Phase 15 protocol-generator log (`generate_protocol.py`)
-- and deterministically re-derives the sequence and relative timing of the
requests it represents, then re-executes them for real.

The "deterministic" guarantee is scoped precisely like Phase 14's schedule
guarantee: `load_recording(path)` is pure arithmetic over already-recorded data
(no clock, no randomness), so loading the same file twice always yields
byte-identical `ReplayEvent` sequences. Real-time *execution* -- actual sleep
resolution, actual request latency/outcome -- is not reproducible, and this
module never claims otherwise (same honesty scoping as `generate.py`).

Offsets are derived from each record's `sent_at` timestamp (present in both log
formats), not from `scheduled_offset_seconds` (present only in pattern logs) --
replay reproduces what was actually observed happening on the wire, not the
original pre-execution plan, since those two diverge under real jitter.

Run (from inside the lab, e.g. the `client` container for a Phase-14-style HTTP
recording, or `api-1` for a Phase-15 protocol recording that used redis/database/
external-service -- see docs/architecture/traffic_replay.md):
    python3 -m simulator.traffic.replay --recording /tmp/normal.jsonl \\
        --out /tmp/normal.replay.jsonl
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from simulator.traffic.generate import _send_request
from simulator.traffic.generate_protocol import DEFAULT_PORTS, _send


@dataclass(frozen=True)
class ReplayEvent:
    offset_seconds: float
    sequence: int
    kind: str  # "http" | "protocol"
    params: Dict[str, Any]


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value)


def load_recording(path: Path) -> List[ReplayEvent]:
    """Parses a Phase 14 or Phase 15 JSON-Lines log into a replay schedule.

    Pure: no sockets, no clock, no randomness. Offsets are derived from each
    record's `sent_at` field relative to the first record's `sent_at`. Raises
    `ValueError` (naming the offending line) on a malformed or unrecognized
    record -- never silently skips a line.
    """
    events: List[ReplayEvent] = []
    base_time: Optional[datetime] = None

    with path.open("r", encoding="utf-8") as f:
        for line_number, raw_line in enumerate(f, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON ({exc})") from exc

            if "sent_at" not in record:
                raise ValueError(f"{path}:{line_number}: record missing required field 'sent_at'")
            if "sequence" not in record:
                raise ValueError(f"{path}:{line_number}: record missing required field 'sequence'")

            try:
                sent_at = _parse_timestamp(record["sent_at"])
            except ValueError as exc:
                raise ValueError(f"{path}:{line_number}: invalid 'sent_at' timestamp ({exc})") from exc

            if base_time is None:
                base_time = sent_at
            offset_seconds = (sent_at - base_time).total_seconds()

            if "pattern" in record and "target" in record:
                kind = "http"
                params: Dict[str, Any] = {"target": record["target"]}
            elif "protocol" in record and "host" in record:
                kind = "protocol"
                protocol = record["protocol"]
                if protocol not in DEFAULT_PORTS:
                    raise ValueError(
                        f"{path}:{line_number}: unknown protocol {protocol!r}; "
                        f"expected one of {sorted(DEFAULT_PORTS)}"
                    )
                params = {
                    "protocol": protocol,
                    "host": record["host"],
                    "port": record.get("port", DEFAULT_PORTS[protocol]),
                    "name": record.get("name", "example.lab"),
                }
            else:
                raise ValueError(
                    f"{path}:{line_number}: record is neither a recognizable Phase 14 pattern-log "
                    f"entry (needs 'pattern'+'target') nor a Phase 15 protocol-log entry "
                    f"(needs 'protocol'+'host'): {record!r}"
                )

            events.append(
                ReplayEvent(
                    offset_seconds=offset_seconds,
                    sequence=record["sequence"],
                    kind=kind,
                    params=params,
                )
            )

    return events


def run(
    recording_path: Path,
    out_path: Path,
    target_override: Optional[str] = None,
    speed: float = 1.0,
) -> int:
    """Replays a recording in real time. Returns the number of requests sent."""
    if speed <= 0:
        raise ValueError(f"speed must be positive, got {speed}")

    events = load_recording(recording_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    run_start = time.perf_counter()
    sent = 0
    with out_path.open("w", encoding="utf-8") as f:
        for replay_seq, event in enumerate(events):
            now = time.perf_counter() - run_start
            sleep_for = (event.offset_seconds / speed) - now
            if sleep_for > 0:
                time.sleep(sleep_for)

            if event.kind == "http":
                target = target_override or event.params["target"]
                result = _send_request(target)
                record = {
                    "kind": "http",
                    "target": target,
                    "replay_of_sequence": event.sequence,
                    "replay_sequence": replay_seq,
                    "replayed_at": datetime.now(timezone.utc).isoformat(),
                    **result,
                }
            else:
                protocol = event.params["protocol"]
                host = event.params["host"]
                port = event.params["port"]
                name = event.params["name"]
                result = _send(protocol, host, port, name)
                record = {
                    "kind": "protocol",
                    "protocol": protocol,
                    "host": host,
                    "port": port,
                    "replay_of_sequence": event.sequence,
                    "replay_sequence": replay_seq,
                    "replayed_at": datetime.now(timezone.utc).isoformat(),
                    **result,
                }

            f.write(json.dumps(record))
            f.write("\n")
            f.flush()
            sent += 1
    return sent


def main() -> None:
    parser = argparse.ArgumentParser(description="NETSCOPE-X deterministic traffic replay engine")
    parser.add_argument("--recording", required=True, type=Path, help="Phase 14/15 JSON-Lines log to replay.")
    parser.add_argument("--out", required=True, type=Path, help="Output JSON-Lines replay log path.")
    parser.add_argument(
        "--target",
        default=None,
        help="Overrides the target URL for all HTTP events in the recording (protocol events unaffected).",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="Time-compression factor; 2.0 replays twice as fast as recorded. Default 1.0.",
    )
    args = parser.parse_args()

    sent = run(args.recording, args.out, target_override=args.target, speed=args.speed)
    print(f"{sent} requests replayed from {args.recording} -> {args.out}")


if __name__ == "__main__":
    main()
