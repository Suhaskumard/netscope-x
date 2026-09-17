"""Phase 14 traffic-pattern schedule tests.

Pure, no Docker/network required -- proves the reproducibility guarantee
(same seed -> identical schedule) and each pattern's expected shape.
"""

from __future__ import annotations

import statistics

import pytest

from simulator.traffic.patterns import PATTERNS, generate_schedule

DURATION = 30.0


@pytest.mark.parametrize("pattern", PATTERNS)
def test_same_seed_produces_identical_schedule(pattern: str) -> None:
    a = generate_schedule(pattern, seed=42, duration_seconds=DURATION)
    b = generate_schedule(pattern, seed=42, duration_seconds=DURATION)
    assert a == b
    assert len(a) > 0, f"{pattern} produced an empty schedule over {DURATION}s"


@pytest.mark.parametrize("pattern", [p for p in PATTERNS if p != "periodic" and p != "concurrent"])
def test_different_seed_produces_different_schedule(pattern: str) -> None:
    # periodic/concurrent are deterministic by construction (no seed dependence),
    # so they're excluded here and covered by their own dedicated tests below.
    a = generate_schedule(pattern, seed=1, duration_seconds=DURATION)
    b = generate_schedule(pattern, seed=2, duration_seconds=DURATION)
    assert a != b


def test_schedule_offsets_within_duration_and_sorted() -> None:
    for pattern in PATTERNS:
        schedule = generate_schedule(pattern, seed=7, duration_seconds=DURATION)
        offsets = [e.offset_seconds for e in schedule]
        assert offsets == sorted(offsets), f"{pattern} schedule not sorted"
        assert all(0 <= o < DURATION for o in offsets), f"{pattern} has an offset outside [0, duration)"


def test_periodic_has_uniform_fixed_interval() -> None:
    schedule = generate_schedule("periodic", seed=1, duration_seconds=DURATION)
    offsets = [e.offset_seconds for e in schedule]
    gaps = [b - a for a, b in zip(offsets, offsets[1:])]
    assert len(set(round(g, 6) for g in gaps)) == 1, "periodic gaps should all be identical"


def test_periodic_is_seed_independent() -> None:
    a = generate_schedule("periodic", seed=1, duration_seconds=DURATION)
    b = generate_schedule("periodic", seed=999, duration_seconds=DURATION)
    assert a == b


def test_idle_has_far_fewer_events_than_normal() -> None:
    normal = generate_schedule("normal", seed=1, duration_seconds=DURATION)
    idle = generate_schedule("idle", seed=1, duration_seconds=DURATION)
    assert len(idle) < len(normal)


def test_concurrent_events_form_equal_offset_groups() -> None:
    schedule = generate_schedule("concurrent", seed=1, duration_seconds=DURATION)
    groups: dict[int, set[float]] = {}
    for event in schedule:
        groups.setdefault(event.group_id, set()).add(event.offset_seconds)
    assert groups, "concurrent schedule produced no groups"
    for group_id, offsets in groups.items():
        assert len(offsets) == 1, f"group {group_id} events do not share a single offset: {offsets}"
    # More than one event per group is the whole point of "concurrent".
    counts = {}
    for event in schedule:
        counts[event.group_id] = counts.get(event.group_id, 0) + 1
    assert all(c > 1 for c in counts.values())


def test_concurrent_is_seed_independent() -> None:
    a = generate_schedule("concurrent", seed=1, duration_seconds=DURATION)
    b = generate_schedule("concurrent", seed=999, duration_seconds=DURATION)
    assert a == b


def test_burst_has_higher_inter_arrival_variance_than_periodic() -> None:
    burst = generate_schedule("burst", seed=3, duration_seconds=60.0)
    periodic = generate_schedule("periodic", seed=3, duration_seconds=60.0)
    burst_gaps = [b.offset_seconds - a.offset_seconds for a, b in zip(burst, burst[1:])]
    periodic_gaps = [b.offset_seconds - a.offset_seconds for a, b in zip(periodic, periodic[1:])]
    assert statistics.pvariance(burst_gaps) > statistics.pvariance(periodic_gaps)


def test_degraded_produces_retries_linked_to_their_original() -> None:
    schedule = generate_schedule("degraded", seed=5, duration_seconds=60.0)
    retries = [e for e in schedule if e.retry_of is not None]
    originals = {e.group_id for e in schedule if e.retry_of is None}
    assert retries, "degraded pattern with this seed/duration produced no retries"
    for retry in retries:
        assert retry.retry_of in originals, "retry references a group_id that has no original event"


def test_unknown_pattern_raises() -> None:
    with pytest.raises(ValueError):
        generate_schedule("not_a_real_pattern", seed=1, duration_seconds=DURATION)
