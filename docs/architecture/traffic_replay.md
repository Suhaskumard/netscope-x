# NETSCOPE-X — Traffic Replay Engine

Phase 19 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 19 — TRAFFIC REPLAY
ENGINE"): "Support deterministic replay of recorded workloads." Code: `simulator/traffic/replay.py`.
Verified by `simulator/tests/test_replay.py` (10 pure unit tests) and a real run against the live
Phase 11-15 lab: a Phase 14 recording captured, then replayed twice against the live lab.

## Design: derive a schedule from what was actually recorded, then re-execute it

A "recorded workload" is exactly one of the JSON-Lines execution logs Phase 14's `generate.py` or
Phase 15's `generate_protocol.py` already produce against the live lab. `replay.py` does not
re-run the original pattern/protocol generator (that already exists); it reads back the log those
generators wrote and reproduces the *sequence and relative timing* of the requests it represents.

Like `patterns.py`/`generate.py`, this module is split into a pure half and a real-I/O half:

- **`load_recording(path) -> List[ReplayEvent]`** is pure: no sockets, no clock, no randomness.
  It parses each JSON-Lines record and derives `offset_seconds` from that record's `sent_at`
  timestamp relative to the first record's `sent_at` — not from `scheduled_offset_seconds` (which
  only exists in Phase 14 logs, not Phase 15 protocol logs, and which represents the
  *pre-execution plan* rather than what was actually observed happening on the wire under real
  jitter). Because this derivation is pure arithmetic over already-recorded data, calling
  `load_recording(path)` twice on the same file always yields a byte-identical `ReplayEvent`
  sequence — this is the concrete, testable meaning of "deterministic" in this phase's brief.
  Record shape is auto-detected: `"pattern"`+`"target"` → an HTTP event (Phase 14 shape);
  `"protocol"`+`"host"` → a protocol event (Phase 15 shape). A record matching neither shape, or
  with a missing `sent_at`/`sequence` field, or naming an unknown protocol, raises `ValueError`
  naming the offending line number — malformed input is never silently skipped (spec Rule 2/3).
- **`run(recording_path, out_path, target_override=None, speed=1.0)`** is the real-I/O half,
  structured the same way as `generate.run`: sleeps to each derived offset (scaled by `speed`)
  against a `time.perf_counter()` baseline, then actually dispatches the request. It deliberately
  reuses `generate._send_request` (for HTTP events) and `generate_protocol._send` (for protocol
  events) rather than reimplementing request logic — the wire-level correctness of those senders
  was already established and unit-tested in Phase 14/15.

What is **not** claimed to be deterministic: real execution timing (`time.sleep` resolution, OS
scheduling) and real request outcomes (status codes, latencies, network conditions) will vary
run to run, exactly as Phase 14's own docs already scope for the original generator. Replay
reproduces order and *derived* relative timing; it does not guarantee identical wall-clock
outcomes.

## CLI

```
python3 -m simulator.traffic.replay --recording /tmp/normal.jsonl --out /tmp/normal.replay.jsonl \
    [--target http://alternate-target/] [--speed 2.0]
```

- `--recording` (required): an existing Phase 14 or Phase 15 JSON-Lines log.
- `--out` (required): where the replay's own JSON-Lines execution log is written.
- `--target` (optional): overrides the target URL for every HTTP event in the recording (protocol
  events are unaffected, since their host/port come from the protocol topology, not a URL).
- `--speed` (optional, default `1.0`): time-compression factor. `2.0` replays twice as fast as
  recorded; this is an honestly-scoped convenience for fast local verification, not a claim that
  compressed replay reproduces original timing.

## Wiring into the lab

Because a recording can be either an HTTP pattern log or a protocol log, which container replays
it follows the same reachability rule Phase 15 already documented (`docs/architecture/
protocol_generation.md`, "Key finding: protocol reachability is topology-dependent"): a
Phase-14-style HTTP recording is replayed from `client` (reaches `gateway` on `edge`); a
Phase-15-style cache/database/TLS protocol recording is replayed from `api-1` (spans
`app`+`data`+`external`).

```
docker compose -f simulator/docker/docker-compose.yml exec client \
    python3 -m simulator.traffic.replay --recording /tmp/recording.jsonl --out /tmp/replay.jsonl
```

## Verification actually performed this phase

- `pytest simulator/tests/test_replay.py` — 10/10 passed: offset derivation from `sent_at` deltas
  correct for both a synthetic pattern-log fixture and a synthetic protocol-log fixture; loading
  the same recording twice produces an identical event list; malformed JSON, a record missing
  `sent_at`, an unrecognized record shape, and an unknown protocol name each raise `ValueError`
  naming the failing line; blank lines are skipped; `ReplayEvent` is frozen and comparable.
  Combined with the rest of the suite: `pytest backend/tests experiments/tests simulator/tests` —
  120/120 passed (up from 110/110 after Phase 18), no regression.
- **Real integration run** against the live Phase 11-15 lab:
  1. Recorded a real burst-pattern run from `client`: `generate.py --pattern burst --seed 7
     --duration 10 --target http://gateway/` → 14/14 real requests, all `status_code: 200`,
     spanning three burst groups over ~10s.
  2. Replayed that recording twice from `client` (`replay1.jsonl`, `replay2.jsonl`) — 14/14 real
     requests sent both times, all `status_code: 200`.
  3. Compared the two replay logs field-by-field, excluding wall-clock-only fields
     (`replayed_at`, `latency_ms`): **identical** — same order, same `replay_of_sequence`
     values, same `target`, same `status_code` sequence. This is the concrete demonstration of
     "deterministic replay," not an assertion.
  4. Compared recorded inter-arrival offsets (`sent_at` deltas in the original recording) against
     replay-1's actual inter-arrival offsets (`replayed_at` deltas): the two tracked each other
     within roughly 2-18ms across all 14 requests (e.g. recorded offset 3.168s vs. replayed
     offset 3.151s for the same request) — real, observed jitter, not fabricated, and consistent
     with `time.sleep` resolution rather than a bug.
  5. Lab torn down (`docker compose ... down`) after verification — nothing left running between
     sessions, consistent with every prior lab-using phase.

## Known limitations

- Replay timing accuracy is bounded by the same `time.sleep` resolution limitation Phase 14
  already documented for its own schedule execution — sub-millisecond precision is not attempted
  or claimed.
- `--speed` compression is a convenience, not a validated timing-fidelity feature: no claim is
  made that a compressed replay preserves the same relative burstiness a downstream anomaly
  detector (Phase 40+) would observe: this remains an open question for future evaluation phases.
- A recording that mixes both HTTP and protocol records in a single file (not produced by either
  existing generator today, but structurally possible) would need to run from a container that
  can reach both kinds of target; `replay.py` does not attempt to route different `kind`s of
  event to different containers within a single run — the operator picks one container per run,
  same as Phase 15's own generator.
- No new Pydantic schema or `experiments/artifacts/` path convention was introduced for replay
  logs; they stay outside that scheme, consistent with how Phase 14/15's own generator logs are
  written directly to an arbitrary `--out` path rather than through the artifact-root layout.

## Status

This document, together with `simulator/traffic/replay.py` and `simulator/tests/test_replay.py`,
satisfies Phase 19: recorded Phase 14/15 workloads can be deterministically re-scheduled (proven
by identical repeated loads and identical repeated replay executions, excluding wall-clock-only
fields) and genuinely re-executed against the live lab.
