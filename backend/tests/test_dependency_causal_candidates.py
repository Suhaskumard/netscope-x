"""Phase 53 causal candidate generation unit tests (pure, no Docker)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.app.models.dependency import DependencyEdge
from backend.app.models.packet import Packet, PacketDirection, TransportProtocol
from backend.dependency.causal_candidates import (
    CAUSAL_CANDIDATE_DISCLAIMER,
    format_causal_candidate,
    generate_causal_candidates,
)
from backend.dependency.strength import estimate_dependency_strength
from backend.nettrace.reconstruct import reconstruct_flows
from backend.nettrace.topology.discovery import discover_nodes
from experiments.artifacts.io import write_jsonl
from experiments.artifacts.paths import packets_path

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _dep(
    dependency_id: str,
    source: str = "n0",
    target: str = "n1",
    strength: float = 0.8,
    temporal_precedence_score: float = 0.5,
) -> DependencyEdge:
    return DependencyEdge(
        dependency_id=dependency_id,
        source_node_id=source,
        target_node_id=target,
        strength=strength,
        frequency=1.0,
        persistence_seconds=10.0,
        directionality_score=0.5,
        temporal_precedence_score=temporal_precedence_score,
    )


def test_qualifying_dependency_becomes_a_candidate() -> None:
    dep = _dep("d0", strength=0.8, temporal_precedence_score=0.5)

    candidates = generate_causal_candidates([dep], strength_threshold=0.5)

    assert len(candidates) == 1
    assert candidates[0].dependency_id == "d0"


def test_high_strength_without_temporal_precedence_does_not_qualify() -> None:
    """The key 'do not equate correlation with causation' case: strength
    alone, however high, is never sufficient."""
    dep = _dep("d0", strength=0.99, temporal_precedence_score=0.0)

    candidates = generate_causal_candidates([dep], strength_threshold=0.5)

    assert candidates == []


def test_low_strength_with_temporal_precedence_does_not_qualify() -> None:
    dep = _dep("d0", strength=0.2, temporal_precedence_score=0.9)

    candidates = generate_causal_candidates([dep], strength_threshold=0.5)

    assert candidates == []


def test_multiple_qualifying_edges_ordered_by_strength_descending() -> None:
    deps = [
        _dep("d0", strength=0.6, temporal_precedence_score=0.3),
        _dep("d1", strength=0.9, temporal_precedence_score=0.4),
        _dep("d2", strength=0.7, temporal_precedence_score=0.2),
    ]

    candidates = generate_causal_candidates(deps, strength_threshold=0.5)

    assert [c.dependency_id for c in candidates] == ["d1", "d2", "d0"]


def test_tie_broken_by_dependency_id() -> None:
    deps = [
        _dep("z", strength=0.8, temporal_precedence_score=0.3),
        _dep("a", strength=0.8, temporal_precedence_score=0.3),
    ]

    candidates = generate_causal_candidates(deps, strength_threshold=0.5)

    assert [c.dependency_id for c in candidates] == ["a", "z"]


def test_rationale_is_non_empty_and_references_real_values() -> None:
    dep = _dep("d0", strength=0.85, temporal_precedence_score=0.72)

    candidates = generate_causal_candidates([dep], strength_threshold=0.5)

    assert len(candidates) == 1
    rationale = candidates[0].rationale
    assert len(rationale) >= 1
    assert any("0.850" in r for r in rationale)
    assert any("0.720" in r for r in rationale)


def test_empty_dependencies_returns_empty_list() -> None:
    assert generate_causal_candidates([]) == []


def test_custom_threshold_changes_qualification() -> None:
    dep = _dep("d0", strength=0.6, temporal_precedence_score=0.5)

    assert generate_causal_candidates([dep], strength_threshold=0.5) != []
    assert generate_causal_candidates([dep], strength_threshold=0.7) == []


def test_format_causal_candidate_includes_disclaimer_and_content() -> None:
    dep = _dep("d0", source="api-1", target="db-1", strength=0.85, temporal_precedence_score=0.72)
    candidates = generate_causal_candidates([dep], strength_threshold=0.5)

    report = format_causal_candidate(candidates[0])

    assert "api-1" in report
    assert "db-1" in report
    assert "0.850" in report
    assert "0.720" in report
    assert CAUSAL_CANDIDATE_DISCLAIMER in report


def _pkt(pid, t, src_ip, src_port, dst_ip, dst_port, protocol) -> Packet:
    return Packet(
        packet_id=pid,
        capture_id="cap-1",
        timestamp=t,
        src_ip=src_ip,
        dst_ip=dst_ip,
        src_port=src_port,
        dst_port=dst_port,
        protocol=protocol,
        size_bytes=100,
        direction=PacketDirection.UNKNOWN,
    )


def test_real_end_to_end_leading_pair_becomes_candidate(tmp_path: Path) -> None:
    """Reuses Phase 52's own multi-node lagged-activity fixture: node A's
    side conversation (with C) consistently precedes node B's (with D) by
    a fixed lag, alongside a minimal direct A<->B exchange. The resulting
    A->B DependencyEdge should have real temporal precedence and become a
    genuine candidate; the A->C/B->D edges (no temporal evidence) should
    not."""
    root = tmp_path / "artifacts"
    packets = [
        _pkt("ab0", BASE, "10.0.0.1", 1000, "10.0.0.2", 80, TransportProtocol.TCP),
        _pkt("ab1", BASE + timedelta(milliseconds=10), "10.0.0.2", 80, "10.0.0.1", 1000, TransportProtocol.TCP),
    ]
    burst_offsets = [30, 34, 39, 45, 52]
    lag_seconds = 4
    for i, offset in enumerate(burst_offsets):
        a_t = BASE + timedelta(seconds=offset)
        b_t = BASE + timedelta(seconds=offset + lag_seconds)
        packets.append(_pkt(f"ac{2*i}", a_t, "10.0.0.1", 2000 + i, "10.0.0.9", 443, TransportProtocol.TCP))
        packets.append(
            _pkt(f"ac{2*i+1}", a_t + timedelta(milliseconds=10), "10.0.0.9", 443, "10.0.0.1", 2000 + i, TransportProtocol.TCP)
        )
        packets.append(_pkt(f"bd{2*i}", b_t, "10.0.0.2", 3000 + i, "10.0.0.8", 443, TransportProtocol.TCP))
        packets.append(
            _pkt(f"bd{2*i+1}", b_t + timedelta(milliseconds=10), "10.0.0.8", 443, "10.0.0.2", 3000 + i, TransportProtocol.TCP)
        )
    write_jsonl(packets_path(root, "cap-1"), packets)
    reconstruct_flows(root, "cap-1")

    dependencies = estimate_dependency_strength(root, "cap-1", dependency_temporal_bucket_seconds=2.0)
    nodes = discover_nodes(root, "cap-1")
    node_ip = {n.node_id: str(n.ip_addresses[0]) for n in nodes}

    ab_dep = next(
        d for d in dependencies if {node_ip[d.source_node_id], node_ip[d.target_node_id]} == {"10.0.0.1", "10.0.0.2"}
    )
    assert ab_dep.temporal_precedence_score > 0.0

    candidates = generate_causal_candidates(dependencies, strength_threshold=0.0)
    candidate_pairs = {
        frozenset({node_ip[c.source_node_id], node_ip[c.target_node_id]}) for c in candidates
    }

    assert frozenset({"10.0.0.1", "10.0.0.2"}) in candidate_pairs
    assert frozenset({"10.0.0.1", "10.0.0.9"}) not in candidate_pairs
    assert frozenset({"10.0.0.2", "10.0.0.8"}) not in candidate_pairs
