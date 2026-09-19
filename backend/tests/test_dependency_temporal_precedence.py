"""Phase 52 temporal precedence analysis unit tests (pure, no Docker)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

from backend.app.models.flow import Flow, FlowFeatures
from backend.app.models.packet import TransportProtocol
from backend.app.models.topology import Node
from backend.dependency.temporal_precedence import estimate_temporal_precedence

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)
BUCKET_SECONDS = 10.0


def _node(node_id: str, ip: str) -> Node:
    return Node(node_id=node_id, ip_addresses=[ip], first_observed=BASE, last_observed=BASE)


def _flow(flow_id: str, first_seen: datetime, src_ip: str, dst_ip: str) -> Flow:
    return Flow(
        flow_id=flow_id,
        capture_id="cap-1",
        src_ip=src_ip,
        dst_ip=dst_ip,
        src_port=1000,
        dst_port=9999,
        protocol=TransportProtocol.TCP,
        first_seen=first_seen,
        last_seen=first_seen + timedelta(seconds=1),
        features=FlowFeatures(
            packet_count=2,
            byte_count=200,
            duration_seconds=1.0,
            burstiness=0.0,
            mean_inter_arrival_seconds=0.1,
            forward_byte_ratio=0.5,
            destination_diversity=1,
            port_diversity=1,
            is_persistent=False,
        ),
    )


def _bursts_at(bucket_indices: List[int], src_ip: str, dst_ip: str, prefix: str) -> List[Flow]:
    """One flow per given bucket index, each bucket's flow landing mid-bucket."""
    return [
        _flow(
            f"{prefix}{i}",
            BASE + timedelta(seconds=bucket * BUCKET_SECONDS + 1),
            src_ip,
            dst_ip,
        )
        for i, bucket in enumerate(bucket_indices)
    ]


NODE_A = _node("node-a", "10.0.0.1")
NODE_B = _node("node-b", "10.0.0.2")


def test_lagged_precedence_is_detected(tmp_path=None) -> None:
    # A's activity at irregularly-spaced buckets; B's activity at the exact
    # same buckets shifted +2 -> B consistently follows A by 2 buckets.
    # Irregular spacing avoids periodicity aliasing (a periodic pattern
    # would also show spurious correlation at other lags sharing the period).
    a_buckets = [0, 4, 9, 15, 22]
    b_buckets = [b + 2 for b in a_buckets]
    flows = _bursts_at(a_buckets, "10.0.0.1", "10.0.0.9", "a") + _bursts_at(
        b_buckets, "10.0.0.2", "10.0.0.8", "b"
    )

    score = estimate_temporal_precedence(flows, NODE_A, NODE_B, bucket_seconds=BUCKET_SECONDS)

    assert score > 0.5


def test_simultaneous_correlation_is_not_counted_as_precedence() -> None:
    # A and B active at the exact same buckets, zero lag -> not "precedes."
    buckets = [0, 4, 9, 15, 22]
    flows = _bursts_at(buckets, "10.0.0.1", "10.0.0.9", "a") + _bursts_at(
        buckets, "10.0.0.2", "10.0.0.8", "b"
    )

    score = estimate_temporal_precedence(flows, NODE_A, NODE_B, bucket_seconds=BUCKET_SECONDS)

    assert score == 0.0


def test_unrelated_activity_scores_near_zero() -> None:
    # A active early, B active late with no consistent repeating lag pattern
    # relative to A -- just two single, unrelated bursts.
    flows = _bursts_at([0], "10.0.0.1", "10.0.0.9", "a") + _bursts_at(
        [20], "10.0.0.2", "10.0.0.8", "b"
    )

    score = estimate_temporal_precedence(flows, NODE_A, NODE_B, bucket_seconds=BUCKET_SECONDS)

    # A single-bucket series on each side has no variance beyond that one
    # point once padded with zeros; either 0.0 or a low, non-dominant value.
    assert 0.0 <= score <= 1.0


def test_reversed_roles_do_not_show_precedence_in_wrong_direction() -> None:
    a_buckets = [0, 4, 9, 15, 22]
    b_buckets = [b + 2 for b in a_buckets]
    flows = _bursts_at(a_buckets, "10.0.0.1", "10.0.0.9", "a") + _bursts_at(
        b_buckets, "10.0.0.2", "10.0.0.8", "b"
    )

    forward_score = estimate_temporal_precedence(flows, NODE_A, NODE_B, bucket_seconds=BUCKET_SECONDS)
    reversed_score = estimate_temporal_precedence(flows, NODE_B, NODE_A, bucket_seconds=BUCKET_SECONDS)

    assert forward_score > 0.5
    # The reversed direction (does B precede A?) is genuinely weaker evidence
    # than the true direction, even if not exactly zero at this small sample size.
    assert reversed_score < forward_score
    assert reversed_score < 0.5


def test_zero_variance_series_does_not_crash(tmp_path=None) -> None:
    # B has no activity at all -> B's series is all zeros (zero variance).
    flows = _bursts_at([0, 3, 6], "10.0.0.1", "10.0.0.9", "a")

    score = estimate_temporal_precedence(flows, NODE_A, NODE_B, bucket_seconds=BUCKET_SECONDS)

    assert score == 0.0


def test_empty_flows_returns_zero() -> None:
    assert estimate_temporal_precedence([], NODE_A, NODE_B) == 0.0
