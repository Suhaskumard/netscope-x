"""Phase 68 observation-completeness sampling unit tests (pure, no Docker)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.app.models.packet import Packet, PacketDirection, TransportProtocol
from experiments.observation_sampling import sample_packets

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _packets(n: int):
    return [
        Packet(
            packet_id=f"p{i}",
            capture_id="cap-1",
            timestamp=BASE,
            src_ip="10.0.0.1",
            dst_ip="10.0.0.2",
            src_port=1000 + i,
            dst_port=80,
            protocol=TransportProtocol.TCP,
            size_bytes=100,
            direction=PacketDirection.UNKNOWN,
        )
        for i in range(n)
    ]


def test_full_completeness_returns_identical_list() -> None:
    packets = _packets(50)
    result = sample_packets(packets, 1.0, seed=1)
    assert result is packets


def test_zero_completeness_returns_empty() -> None:
    packets = _packets(50)
    assert sample_packets(packets, 0.0, seed=1) == []


def test_deterministic_for_same_seed() -> None:
    packets = _packets(200)
    first = sample_packets(packets, 0.5, seed=7)
    second = sample_packets(packets, 0.5, seed=7)
    assert [p.packet_id for p in first] == [p.packet_id for p in second]


def test_different_seeds_can_differ() -> None:
    packets = _packets(200)
    a = sample_packets(packets, 0.5, seed=1)
    b = sample_packets(packets, 0.5, seed=2)
    assert [p.packet_id for p in a] != [p.packet_id for p in b]


def test_completeness_is_a_subset_relationship() -> None:
    """A lower completeness's sample is always a subset of a higher one's,
    for the same (packets, seed) -- not independently redrawn."""
    packets = _packets(500)
    low = {p.packet_id for p in sample_packets(packets, 0.25, seed=3)}
    high = {p.packet_id for p in sample_packets(packets, 0.75, seed=3)}
    assert low.issubset(high)


def test_order_preserved() -> None:
    packets = _packets(100)
    result = sample_packets(packets, 0.5, seed=9)
    ids = [p.packet_id for p in result]
    assert ids == sorted(ids, key=lambda pid: int(pid[1:]))


def test_out_of_range_completeness_raises() -> None:
    with pytest.raises(ValueError):
        sample_packets(_packets(5), 1.5, seed=1)
    with pytest.raises(ValueError):
        sample_packets(_packets(5), -0.1, seed=1)


def test_roughly_matches_target_completeness_on_a_large_sample() -> None:
    packets = _packets(5000)
    result = sample_packets(packets, 0.5, seed=11)
    ratio = len(result) / len(packets)
    assert 0.45 < ratio < 0.55
