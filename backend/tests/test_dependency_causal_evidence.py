"""Phase 56 causal evidence report unit tests (pure, no Docker)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.app.models.dependency import DependencyEdge
from backend.app.models.failure import ImpactOrder, PropagationImpact
from backend.app.models.packet import Packet, PacketDirection, TransportProtocol
from backend.dependency.causal_candidates import CausalCandidate, generate_causal_candidates
from backend.dependency.causal_evidence import (
    CONFOUNDER_LIMITATION,
    PROPAGATION_LIMITATION,
    THRESHOLD_LIMITATION,
    build_dependency_evidence_report,
    build_propagation_evidence_report,
)
from backend.dependency.failure_propagation import propagate_failure
from backend.dependency.strength import estimate_dependency_strength
from backend.nettrace.reconstruct import reconstruct_flows
from backend.nettrace.topology.discovery import discover_nodes
from experiments.artifacts.io import write_jsonl
from experiments.artifacts.paths import packets_path

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _dep(
    dependency_id: str = "d0",
    source: str = "A",
    target: str = "B",
    strength: float = 0.8,
    directionality: float = 0.8,
    temporal_precedence: float = 0.5,
) -> DependencyEdge:
    return DependencyEdge(
        dependency_id=dependency_id,
        source_node_id=source,
        target_node_id=target,
        strength=strength,
        frequency=1.5,
        persistence_seconds=42.0,
        directionality_score=directionality,
        temporal_precedence_score=temporal_precedence,
    )


def _candidate(dependency: DependencyEdge) -> CausalCandidate:
    return CausalCandidate(
        dependency_id=dependency.dependency_id,
        source_node_id=dependency.source_node_id,
        target_node_id=dependency.target_node_id,
        strength=dependency.strength,
        temporal_precedence_score=dependency.temporal_precedence_score,
        rationale=["synthetic rationale"],
    )


def test_candidate_backed_dependency_uses_causal_candidate_wording() -> None:
    dependency = _dep()
    candidate = _candidate(dependency)

    report = build_dependency_evidence_report(dependency, candidate)

    assert "causal candidate" in report.relationship
    assert report.confidence == dependency.strength
    assert len(report.evidence) >= 1
    assert CONFOUNDER_LIMITATION in report.limitations
    assert THRESHOLD_LIMITATION in report.limitations


def test_non_candidate_dependency_uses_weaker_wording_and_threshold_counter_evidence() -> None:
    dependency = _dep(temporal_precedence=0.0)

    report = build_dependency_evidence_report(dependency, candidate=None)

    assert "communicate" in report.relationship
    assert "no causal direction is established" in report.relationship
    assert any("causal-candidate threshold" in c for c in report.counter_evidence)


def test_zero_temporal_precedence_adds_counter_evidence() -> None:
    dependency = _dep(temporal_precedence=0.0)

    report = build_dependency_evidence_report(dependency, candidate=None)

    assert any("temporal-precedence" in c for c in report.counter_evidence)


def test_positive_temporal_precedence_omits_that_counter_evidence_item() -> None:
    dependency = _dep(temporal_precedence=0.6)
    candidate = _candidate(dependency)

    report = build_dependency_evidence_report(dependency, candidate)

    assert not any("temporal-precedence" in c for c in report.counter_evidence)


def test_low_directionality_adds_counter_evidence() -> None:
    dependency = _dep(directionality=0.1)
    candidate = _candidate(dependency)

    report = build_dependency_evidence_report(dependency, candidate)

    assert any("bidirectional" in c for c in report.counter_evidence)


def test_high_directionality_omits_that_counter_evidence_item() -> None:
    dependency = _dep(directionality=0.9)
    candidate = _candidate(dependency)

    report = build_dependency_evidence_report(dependency, candidate)

    assert not any("bidirectional" in c for c in report.counter_evidence)


def test_strong_candidate_can_have_empty_counter_evidence() -> None:
    dependency = _dep(directionality=0.9, temporal_precedence=0.7)
    candidate = _candidate(dependency)

    report = build_dependency_evidence_report(dependency, candidate)

    assert report.counter_evidence == []


def _impact(order: ImpactOrder, affected: str, caused_by, evidence=("real evidence",)) -> PropagationImpact:
    return PropagationImpact(
        scenario_id="s1",
        affected_node_id=affected,
        order=order,
        caused_by_node_id=caused_by,
        evidence=list(evidence),
    )


def test_primary_impact_raises_value_error() -> None:
    impact = _impact(ImpactOrder.PRIMARY, "A", None)

    with pytest.raises(ValueError):
        build_propagation_evidence_report(impact, candidates=[])


def test_no_matching_candidate_raises_value_error() -> None:
    impact = _impact(ImpactOrder.SECONDARY, "B", "A")

    with pytest.raises(ValueError):
        build_propagation_evidence_report(impact, candidates=[])


def test_secondary_impact_report_uses_candidate_strength_and_real_evidence() -> None:
    dependency = _dep(source="A", target="B", strength=0.77)
    candidate = _candidate(dependency)
    impact = _impact(ImpactOrder.SECONDARY, "B", "A", evidence=["impact propagates from A via a causal candidate"])

    report = build_propagation_evidence_report(impact, candidates=[candidate])

    assert report.confidence == 0.77
    assert report.evidence == ["impact propagates from A via a causal candidate"]
    assert report.counter_evidence == []
    assert PROPAGATION_LIMITATION in report.limitations
    assert CONFOUNDER_LIMITATION in report.limitations
    assert THRESHOLD_LIMITATION in report.limitations
    assert "secondary" in report.relationship


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


def test_real_end_to_end_dependency_and_propagation_reports(tmp_path: Path) -> None:
    """A genuine 3-hop lagged-activity chain (Phase 54's own fixture
    pattern): runs the real pipeline through estimate_dependency_strength
    -> generate_causal_candidates -> propagate_failure, then generates
    both a dependency report and a propagation report from the
    genuinely-computed objects."""
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
    a_id, b_id = node_id_by_ip["10.0.0.1"], node_id_by_ip["10.0.0.2"]

    ab_dependency = next(d for d in dependencies if {d.source_node_id, d.target_node_id} == {a_id, b_id})
    ab_candidate = next((c for c in candidates if c.dependency_id == ab_dependency.dependency_id), None)

    dependency_report = build_dependency_evidence_report(ab_dependency, ab_candidate)
    assert dependency_report.relationship
    assert dependency_report.confidence == ab_dependency.strength

    impacts = propagate_failure(candidates, "scenario-1", a_id)
    secondary_impact = next(i for i in impacts if i.order == ImpactOrder.SECONDARY)

    propagation_report = build_propagation_evidence_report(secondary_impact, candidates)
    assert propagation_report.relationship
    assert propagation_report.evidence == secondary_impact.evidence
    assert 0.0 <= propagation_report.confidence <= 1.0
