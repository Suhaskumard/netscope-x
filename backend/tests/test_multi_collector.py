"""Phase 90 multi-collector pipeline tests (pure, no Docker)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.app.models.packet import Packet, PacketDirection, TransportProtocol
from backend.nettrace.collectors.multi import MultiCollectorPipeline
from backend.nettrace.topology.edges import confidence_from_stats  # noqa: F401  (documents the pooled noisy-OR)
from backend.nettrace.topology.incremental import IncrementalTopology

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def pkt(pid, t, src, dst, sp=1000, dp=80, size=100, proto=TransportProtocol.TCP) -> Packet:
    return Packet(packet_id=pid, capture_id="c", timestamp=BASE + timedelta(seconds=t), src_ip=src, dst_ip=dst,
                  src_port=sp, dst_port=dp, protocol=proto, size_bytes=size, direction=PacketDirection.UNKNOWN)


def conv(prefix, a, b, n, t0=0.0, sp=1000):
    out = []
    for i in range(n):
        out.append(pkt(f"{prefix}f{i}", t0 + i, a, b, sp, 80))
        out.append(pkt(f"{prefix}r{i}", t0 + i + 0.01, b, a, 80, sp))
    return out


def edge_set(graph):
    ip = {n.node_id: str(n.ip_addresses[0]) for n in graph.nodes}
    return {frozenset({ip[e.source_node_id], ip[e.target_node_id]}): e.confidence for e in graph.edges}


def full(packets):
    inc = IncrementalTopology("c")
    inc.ingest(sorted(packets, key=lambda p: p.timestamp))
    return inc.graph("c")


def test_same_packet_from_two_collectors_counts_once():
    p = conv("a", "10.0.0.1", "10.0.0.2", 5)
    pipe = MultiCollectorPipeline("c")
    r1 = pipe.ingest("A", p)
    r2 = pipe.ingest("B", p)
    assert (r1.accepted, r1.duplicates) == (len(p), 0) and (r2.accepted, r2.duplicates) == (0, len(p))
    assert edge_set(pipe.graph()) == edge_set(full(p))


def test_a_collectors_own_repeats_are_never_merged():
    same = [pkt(f"k{i}", 0.0005 * i, "10.0.0.1", "10.0.0.2", size=64) for i in range(4)]  # identical, within tolerance
    pipe = MultiCollectorPipeline("c", dedupe_tolerance_s=0.001)
    assert pipe.ingest("A", same).duplicates == 0
    assert pipe.ingest("B", same).duplicates == 4  # each of B's four pairs with one of A's four, once


def test_skew_inside_tolerance_dedupes_and_outside_does_not():
    p = conv("a", "10.0.0.1", "10.0.0.2", 5)
    skewed = [x.model_copy(update={"timestamp": x.timestamp + timedelta(seconds=0.0005)}) for x in p]
    inside = MultiCollectorPipeline("c", dedupe_tolerance_s=0.001)
    inside.ingest("A", p)
    assert inside.ingest("B", skewed).duplicates == len(p)
    far = [x.model_copy(update={"timestamp": x.timestamp + timedelta(seconds=0.05)}) for x in p]
    outside = MultiCollectorPipeline("c", dedupe_tolerance_s=0.001)
    outside.ingest("A", p)
    assert outside.ingest("B", far).duplicates == 0  # failure case: double counting


def test_naive_concatenation_inflates_confidence_pooled_does_not():
    p = conv("a", "10.0.0.1", "10.0.0.2", 3)
    ref = next(iter(edge_set(full(p)).values()))
    pooled, naive = MultiCollectorPipeline("c"), MultiCollectorPipeline("c", dedupe=False)
    for pipe in (pooled, naive):
        pipe.ingest("A", p)
        pipe.ingest("B", p)
    assert next(iter(edge_set(pooled.graph()).values())) == pytest.approx(ref, abs=1e-12)
    assert next(iter(edge_set(naive.graph()).values())) > ref


def test_disagreement_on_existence_gets_a_resolution_record():
    ab = conv("ab", "10.0.0.1", "10.0.0.2", 4)
    ac = conv("ac", "10.0.0.1", "10.0.0.3", 4, t0=10)
    pipe = MultiCollectorPipeline("c")
    pipe.ingest("A", ab + ac)  # sees both edges
    pipe.ingest("B", ab)  # sees only A-B
    pipe.ingest("B", [pkt("b3", 20, "10.0.0.3", "10.0.0.9")])  # B knows node .3 but never saw the .1-.3 edge
    res = {r.pair: r for r in pipe.resolutions()}
    r13 = res[frozenset({"10.0.0.1", "10.0.0.3"})]
    assert r13.supporting == ("A",) and r13.kind in {"existence", "single_source"}
    assert res[frozenset({"10.0.0.1", "10.0.0.2"})].kind == "agree"
    assert len(res) == len(pipe.graph().edges)


def test_quorum_drops_single_source_edge_when_two_others_saw_both_endpoints():
    real = conv("r", "10.0.0.1", "10.0.0.2", 4)
    other = conv("o", "10.0.0.3", "10.0.0.4", 4, t0=5)
    fab = conv("fab", "10.0.0.1", "10.0.0.3", 6, t0=30, sp=4000)  # only collector A claims 1<->3
    view_a = real + other + fab
    view_b = real + other
    view_c = real + other
    for quorum, expect in ((False, True), (True, False)):
        pipe = MultiCollectorPipeline("c", quorum=quorum)
        pipe.ingest("A", view_a)
        pipe.ingest("B", view_b)
        pipe.ingest("C", view_c)
        assert (frozenset({"10.0.0.1", "10.0.0.3"}) in edge_set(pipe.graph())) is expect
        assert frozenset({"10.0.0.1", "10.0.0.2"}) in edge_set(pipe.graph())


def test_two_collector_tie_cannot_fire_default_quorum():
    real = conv("r", "10.0.0.1", "10.0.0.2", 4)
    other = conv("o", "10.0.0.3", "10.0.0.4", 4, t0=5)
    fab = conv("fab", "10.0.0.1", "10.0.0.3", 6, t0=30, sp=4000)
    pipe = MultiCollectorPipeline("c", quorum=True)  # quorum_min_absent=2 but only one other collector exists
    pipe.ingest("A", real + other + fab)
    pipe.ingest("B", real + other)
    assert frozenset({"10.0.0.1", "10.0.0.3"}) in edge_set(pipe.graph())  # documented failure case


def test_result_is_independent_of_collector_arrival_order():
    p = conv("a", "10.0.0.1", "10.0.0.2", 6) + conv("b", "10.0.0.2", "10.0.0.3", 6, t0=3)
    va = p[::2] + [x for i, x in enumerate(p) if i % 2 == 1 and i % 3 == 0]
    vb = p[1::2] + [x for i, x in enumerate(p) if i % 2 == 0 and i % 3 == 0]
    one, two = MultiCollectorPipeline("c"), MultiCollectorPipeline("c")
    one.ingest("A", va); one.ingest("B", vb)  # noqa: E702
    two.ingest("B", vb); two.ingest("A", va)  # noqa: E702
    assert edge_set(one.graph()) == edge_set(two.graph())
    assert edge_set(one.graph()) == edge_set(full(p))


def test_bad_settings_raise():
    with pytest.raises(ValueError):
        MultiCollectorPipeline("c", dedupe_tolerance_s=-1)
