# NETSCOPE-X — Traffic Workload Generator

Phase 14 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 14 — TRAFFIC WORKLOAD
GENERATOR"): "Implement reproducible: normal, burst, periodic, concurrent, idle, degraded traffic."
Code: `simulator/traffic/`. Verified by `simulator/tests/test_patterns.py` (19 tests, all passing) and
a real run against the Phase 11-13 lab.

## Design: schedule generation is pure and reproducible; execution is not

`simulator/traffic/patterns.py`'s `generate_schedule(pattern, seed, duration_seconds)` is a pure
function — no I/O, no sleeping, no network access. Given the same `(pattern, seed, duration)` it
always returns an identical list of `ScheduledEvent(offset_seconds, group_id, retry_of)` objects. This
is the concrete, unit-testable reproducibility guarantee spec Phase 14 requires.

`simulator/traffic/generate.py`'s `run(...)` takes that schedule and actually executes it: sleeps in
real wall-clock time to each offset, issues a real HTTP GET (stdlib `urllib`, no new dependency), and
appends one JSON-Lines record per executed request. **This execution layer is honestly not
reproducible** — real network latency, real scheduling jitter from the OS, and the real target's
actual responses all vary run to run. Only the *schedule* (when each request is supposed to fire) is
guaranteed reproducible; this distinction is stated explicitly rather than overclaiming reproducibility
of the full execution, per spec §21 ("no fake metrics" / honest limitations).

## The 6 required patterns

| Pattern | Algorithm | Reproducible via seed? |
|---|---|---|
| **normal** | Exponential inter-arrival times (Poisson process), `rate=1/s` default | Yes |
| **burst** | Alternating quiet windows (~3s ± jitter) and clusters of 5 near-simultaneous requests | Yes |
| **periodic** | Fixed interval (2s default), zero randomness by construction | N/A (deterministic regardless of seed) |
| **concurrent** | Repeated groups of 5 requests scheduled at the *same* offset, every 3s | N/A (deterministic regardless of seed) |
| **idle** | Same Poisson process as `normal`, much lower rate (0.05/s default) | Yes |
| **degraded** | Normal-rate requests where a seeded fraction (~30%) get a linked client-side retry shortly after | Yes |

`periodic` and `concurrent` are deterministic by construction (their timing has no random component),
so they don't vary with the seed — this is intentional, not a bug, and is explicitly tested
(`test_periodic_is_seed_independent`, `test_concurrent_is_seed_independent`).

## Wiring into the lab

The `client` service (Phase 11: alpine + curl/bind-tools) gained `python3` and a read-only mount of
`simulator/` at `/opt/netscope/simulator` (Phase 14 change to `simulator/docker/docker-compose.yml`,
documented per spec §38 like the Phase 12/13 changes). Run from inside the lab:

```
docker compose -f simulator/docker/docker-compose.yml exec client \
    python3 -m simulator.traffic.generate --pattern normal --seed 42 \
    --duration 12 --target http://gateway/ --out /tmp/normal.jsonl
```

(`client` is only on the `edge` network per Phase 12, so `http://gateway/` — the intended entry point
— is exactly what it can and should target; this is consistent with, not a workaround around, the
Phase 12 isolation boundaries.)

## Verification actually performed this phase

- `pytest simulator/tests/test_patterns.py` — 19/19 passed: same-seed determinism for all 6 patterns;
  different-seed variation for the 4 seed-dependent patterns; all offsets sorted and within
  `[0, duration)`; periodic's gaps are all identical; periodic/concurrent are seed-independent; idle
  produces far fewer events than normal; concurrent events cluster into groups sharing one offset, each
  with more than one member; burst has higher inter-arrival variance than periodic; degraded produces
  retries whose `retry_of` correctly references a real original event; an unknown pattern name raises.
- **Real integration run** against the live Phase 11-13 lab (3 of the 6 patterns, chosen as
  representative — steady-rate, bursty, and simultaneous-group traffic shapes):
  - `normal`, seed 42, 12s: 18 requests sent, all HTTP 200, real latencies (5-26ms), real
    `sent_at` timestamps confirming actual delivery over real wall-clock time.
  - `burst`, seed 42, 12s: 15 requests; the log shows a genuine cluster of 5 requests within ~0.36s
    (group_id 0), then a gap of ~3.4s before the next group begins — matching the designed
    quiet/burst alternation.
  - `concurrent`, seed 42, 10s: 15 requests; group 0's 5 requests were all sent within 20ms of each
    other (18:06:30.583978 to 18:06:30.603554), and group 1 similarly clustered ~3s later — real,
    observed near-simultaneous delivery, not merely scheduled that way.
  - All requests across all three runs returned real HTTP 200 responses from the live gateway→
    load-balancer→api chain.
- Lab torn down (`docker compose ... down`) after verification.

## Known limitations

- Execution timing accuracy is bounded by Python's `time.sleep` resolution and whatever load the host/
  container is under — schedules are followed closely but not with hard real-time guarantees; this is
  acceptable for a research lab traffic generator, not a real-time system.
- `degraded` traffic simulates client-side retry *behavior*, not server-side degradation (slow
  responses, partial failures) — actual service degradation is Phase 59's failure-injection framework;
  this phase only produces the client traffic *pattern* associated with a client experiencing
  degraded conditions.
- No protocol diversity yet (this phase only issues HTTP GETs) — TCP/UDP/DNS/TLS/database/cache
  traffic diversity is Phase 15's job.
- Logs are written per-run to an arbitrary `--out` path chosen by the caller; there is no dataset
  registry yet tying generated traffic to a named, versioned dataset (`dataset_small`, etc.) — that's
  Phase 19, building on this generator and Phase 10's artifact I/O layer.

## Status

This document, together with `simulator/traffic/{patterns,generate}.py` and
`simulator/tests/test_patterns.py`, satisfies Phase 14: all 6 required traffic patterns are
implemented with a proven, unit-tested reproducibility guarantee on their schedule, and were actually
exercised against the real multi-tier lab (3 of 6 patterns run for real; all 6 covered by the
schedule-determinism unit tests).
