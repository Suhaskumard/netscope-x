"""Reproducible traffic-pattern schedule generation (spec Phase 14).

Pure functions: no I/O, no real sleeping, no network. Given the same
(pattern, seed, duration_seconds), `generate_schedule` always returns an
identical list of `ScheduledEvent`s -- reproducibility is the acceptance
bar spec Phase 14 requires, and it is proven here independently of any
Docker lab or real clock (see simulator/tests/test_patterns.py). Actual
execution against a real target lives in generate.py.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional


@dataclass(frozen=True)
class ScheduledEvent:
    """One request scheduled at a relative offset from the start of the run."""

    offset_seconds: float
    group_id: int
    retry_of: Optional[int] = None  # group_id of the original event, if this is a retry


def _normal(seed: int, duration_seconds: float, rate_per_second: float = 1.0) -> List[ScheduledEvent]:
    """Steady-rate traffic: exponential inter-arrival times (Poisson process)."""
    rng = random.Random(seed)
    events: List[ScheduledEvent] = []
    t = 0.0
    idx = 0
    while True:
        t += rng.expovariate(rate_per_second)
        if t >= duration_seconds:
            break
        events.append(ScheduledEvent(offset_seconds=t, group_id=idx))
        idx += 1
    return events


def _burst(
    seed: int,
    duration_seconds: float,
    quiet_seconds: float = 3.0,
    burst_size: int = 5,
    burst_spread_seconds: float = 0.5,
) -> List[ScheduledEvent]:
    """Alternating quiet windows and bursts of near-simultaneous requests."""
    rng = random.Random(seed)
    events: List[ScheduledEvent] = []
    t = 0.0
    group = 0
    while True:
        t += quiet_seconds + rng.uniform(-0.3, 0.3)
        if t >= duration_seconds:
            break
        for _ in range(burst_size):
            offset = t + rng.uniform(0, burst_spread_seconds)
            if offset >= duration_seconds:
                break
            events.append(ScheduledEvent(offset_seconds=offset, group_id=group))
        t += burst_spread_seconds
        group += 1
    return events


def _periodic(seed: int, duration_seconds: float, interval_seconds: float = 2.0) -> List[ScheduledEvent]:
    """Fixed-interval requests -- no randomness in timing by construction (seed unused,
    accepted only so every pattern shares the same function signature)."""
    del seed
    events: List[ScheduledEvent] = []
    t = interval_seconds
    idx = 0
    while t < duration_seconds:
        events.append(ScheduledEvent(offset_seconds=t, group_id=idx))
        t += interval_seconds
        idx += 1
    return events


def _concurrent(
    seed: int,
    duration_seconds: float,
    group_size: int = 5,
    interval_seconds: float = 3.0,
) -> List[ScheduledEvent]:
    """Repeated groups of simultaneous requests -- all events in a group share one offset."""
    del seed  # timing is deterministic by construction; no jitter needed to prove concurrency
    events: List[ScheduledEvent] = []
    t = interval_seconds
    group = 0
    while t < duration_seconds:
        for _ in range(group_size):
            events.append(ScheduledEvent(offset_seconds=t, group_id=group))
        t += interval_seconds
        group += 1
    return events


def _idle(seed: int, duration_seconds: float, rate_per_second: float = 0.05) -> List[ScheduledEvent]:
    """Very sparse traffic -- same Poisson process as `_normal` at a much lower rate."""
    return _normal(seed, duration_seconds, rate_per_second=rate_per_second)


def _degraded(
    seed: int,
    duration_seconds: float,
    rate_per_second: float = 1.0,
    retry_fraction: float = 0.3,
    retry_delay_seconds: float = 0.3,
) -> List[ScheduledEvent]:
    """Normal-rate traffic where a seeded fraction of requests are followed by a
    client-side retry shortly after -- simulates a client under degraded conditions
    re-attempting a request it believes failed or was slow."""
    rng = random.Random(seed)
    events: List[ScheduledEvent] = []
    t = 0.0
    idx = 0
    while True:
        t += rng.expovariate(rate_per_second)
        if t >= duration_seconds:
            break
        original_group = idx
        events.append(ScheduledEvent(offset_seconds=t, group_id=original_group))
        idx += 1
        if rng.random() < retry_fraction:
            retry_t = t + retry_delay_seconds + rng.uniform(0, 0.2)
            if retry_t < duration_seconds:
                events.append(
                    ScheduledEvent(offset_seconds=retry_t, group_id=original_group, retry_of=original_group)
                )
                idx += 1
    return events


_GENERATORS: Dict[str, Callable[[int, float], List[ScheduledEvent]]] = {
    "normal": _normal,
    "burst": _burst,
    "periodic": _periodic,
    "concurrent": _concurrent,
    "idle": _idle,
    "degraded": _degraded,
}

PATTERNS = tuple(_GENERATORS.keys())


def generate_schedule(pattern: str, seed: int, duration_seconds: float) -> List[ScheduledEvent]:
    """Deterministic schedule for one of the 6 required traffic patterns (spec Phase 14).

    Same (pattern, seed, duration_seconds) always returns an identical list, sorted by
    offset_seconds (stable sort, so concurrent-group ordering is also deterministic).
    """
    if pattern not in _GENERATORS:
        raise ValueError(f"unknown traffic pattern: {pattern!r}; expected one of {PATTERNS}")
    events = _GENERATORS[pattern](seed, duration_seconds)
    return sorted(events, key=lambda e: e.offset_seconds)
