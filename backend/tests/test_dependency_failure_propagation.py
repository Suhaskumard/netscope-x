"""Phase 54 failure propagation graph unit tests (pure, no Docker)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.app.models.failure import ImpactOrder
from backend.app.models.packet import Packet, PacketDirection, TransportProtocol
from backend.dependency.causal_candidates import CausalCandidate, generate_causal_candidates
from backend.dependency.failure_propagation import propagate_failure
from backend.dependency.strength import estimate_dependency_strength
from backend.nettrace.reconstruct import reconstruct_flows
from backend.nettrace.topology.discovery import discover_nodes
from experiments.artifacts.io import write_jsonl
from experiments.artifacts.paths import packets_path

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _candidate(dependency_id: str, source: str, target: str, strength: float = 0.8, tp: float = 0.6) -> CausalCandidate:
    return CausalCandidate(
        dependency_id=dependency_id,
        source_node_id=source,
        target_node_id=target,
        strength=strength,
        temporal_precedence_score=tp,
        rationale=[f"strength {strength:.3f} meets threshold", f"temporal_precedence_score {tp:.3f}"],
    )


def test_simple_chain_produces_primary_secondary_tertiary() -> None:
    candidates = [
        _candidate("d0", "A", "B"),
        _candidate("d1", "B", "C"),
        _candidate("d2", "C", "D"),  # beyond tertiary, should not appear
    ]

    impacts = propagate_failure(candidates, "scenario-1", "A")

    by_order = {i.order: i.affected_node_id for i in impacts}
    assert by_order[ImpactOrder.PRIMARY] == "A"
    assert by_order[ImpactOrder.SECONDARY] == "B"
    assert by_order[ImpactOrder.TERTIARY] == "C"
    assert not any(i.affected_node_id == "D" for i in impacts)
    assert len(impacts) == 3


def test_node_with_no_outgoing_candidates_produces_only_primary() -> None:
    candidates = [_candidate("d0", "X", "Y")]

    impacts = propagate_failure(candidates, "scenario-1", "A")

    assert len(impacts) == 1
    assert impacts[0].order == ImpactOrder.PRIMARY
    assert impacts[0].affected_node_id == "A"
    assert impacts[0].caused_by_node_id is None


def test_diamond_pattern_visits_shared_descendant_once() -> None:
    candidates = [
        _candidate("d0", "A", "B"),
        _candidate("d1", "A", "C"),
        _candidate("d2", "B", "D"),
        _candidate("d3", "C", "D"),
    ]

    impacts = propagate_failure(candidates, "scenario-1", "A")

    d_impacts = [i for i in impacts if i.affected_node_id == "D"]
    assert len(d_impacts) == 1
    assert d_impacts[0].order == ImpactOrder.TERTIARY
    # Deterministic: B sorts before C, and d2 (B->D) is processed first.
    assert d_impacts[0].caused_by_node_id == "B"


def test_cycle_does_not_infinite_loop_or_revisit() -> None:
    candidates = [
        _candidate("d0", "A", "B"),
        _candidate("d1", "B", "A"),
        _candidate("d2", "A", "C"),
    ]

    impacts = propagate_failure(candidates, "scenario-1", "A")

    affected_ids = [i.affected_node_id for i in impacts]
    assert affected_ids.count("A") == 1
    assert set(affected_ids) == {"A", "B", "C"}


def test_non_primary_evidence_references_real_candidate_values() -> None:
    candidates = [_candidate("d0", "A", "B", strength=0.85, tp=0.72)]

    impacts = propagate_failure(candidates, "scenario-1", "A")

    secondary = next(i for i in impacts if i.order == ImpactOrder.SECONDARY)
    assert len(secondary.evidence) >= 1
    assert "0.850" in secondary.evidence[0]
    assert "0.720" in secondary.evidence[0]


def test_empty_candidates_produces_only_primary() -> None:
    impacts = propagate_failure([], "scenario-1", "A")

    assert len(impacts) == 1
    assert impacts[0].order == ImpactOrder.PRIMARY


def test_deterministic_across_repeated_calls() -> None:
    candidates = [
        _candidate("d0", "A", "B"),
        _candidate("d1", "A", "C"),
        _candidate("d2", "B", "D"),
    ]

    first = propagate_failure(candidates, "scenario-1", "A")
    second = propagate_failure(candidates, "scenario-1", "A")

    assert first == second


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


def test_real_end_to_end_three_hop_chain(tmp_path: Path) -> None:
    """A genuine 3-hop dependency chain: A's overall activity (via dummy
    partner A') precedes B's (via B'), which precedes C's (via C'), each
    by a fixed lag. Direct minimal A<->B and B<->C exchanges give each
    pair a real DependencyEdge/CausalCandidate. No direct A<->C traffic
    exists, so any TERTIARY discovery of C must come from real
    propagation through B, not a shortcut edge."""
    root = tmp_path / "artifacts"
    packets = [
        _pkt("ab0", BASE, "10.0.0.1", 1000, "10.0.0.2", 80, TransportProtocol.TCP),
        _pkt("ab1", BASE + timedelta(milliseconds=10), "10.0.0.2", 80, "10.0.0.1", 1000, TransportProtocol.TCP),
        _pkt("bc0", BASE, "10.0.0.2", 1100, "10.0.0.3", 81, TransportProtocol.TCP),
        _pkt("bc1", BASE + timedelta(milliseconds=10), "10.0.0.3", 81, "10.0.0.2", 1100, TransportProtocol.TCP),
    ]
    burst_offsets = [30, 34, 39, 45, 52]
    lag = 4
    for i, offset in enumerate(burst_offsets):
        a_t = BASE + timedelta(seconds=offset)
        b_t = BASE + timedelta(seconds=offset + lag)
        c_t = BASE + timedelta(seconds=offset + 2 * lag)
        packets.append(_pkt(f"a{2*i}", a_t, "10.0.0.1", 2000 + i, "10.0.0.91", 443, TransportProtocol.TCP))
        packets.append(_pkt(f"a{2*i+1}", a_t + timedelta(milliseconds=10), "10.0.0.91", 443, "10.0.0.1", 2000 + i, TransportProtocol.TCP))
        packets.append(_pkt(f"b{2*i}", b_t, "10.0.0.2", 3000 + i, "10.0.0.92", 443, TransportProtocol.TCP))
        packets.append(_pkt(f"b{2*i+1}", b_t + timedelta(milliseconds=10), "10.0.0.92", 443, "10.0.0.2", 3000 + i, TransportProtocol.TCP))
        packets.append(_pkt(f"c{2*i}", c_t, "10.0.0.3", 4000 + i, "10.0.0.93", 443, TransportProtocol.TCP))
        packets.append(_pkt(f"c{2*i+1}", c_t + timedelta(milliseconds=10), "10.0.0.93", 443, "10.0.0.3", 4000 + i, TransportProtocol.TCP))
    write_jsonl(packets_path(root, "cap-1"), packets)
    reconstruct_flows(root, "cap-1")

    dependencies = estimate_dependency_strength(root, "cap-1", dependency_temporal_bucket_seconds=2.0)
    candidates = generate_causal_candidates(dependencies, strength_threshold=0.0)
    nodes = discover_nodes(root, "cap-1")
    node_id_by_ip = {str(n.ip_addresses[0]): n.node_id for n in nodes}

    a_id = node_id_by_ip["10.0.0.1"]
    b_id = node_id_by_ip["10.0.0.2"]
    c_id = node_id_by_ip["10.0.0.3"]

    impacts = propagate_failure(candidates, "scenario-1", a_id)
    by_order = {i.order: i.affected_node_id for i in impacts}

    assert by_order[ImpactOrder.PRIMARY] == a_id
    assert by_order.get(ImpactOrder.SECONDARY) == b_id
    assert by_order.get(ImpactOrder.TERTIARY) == c_id
