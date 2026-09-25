"""Phase 87: streaming dependency-strength and causal-candidate updates."""

from __future__ import annotations


import pytest

from backend.dependency.streaming import StreamingDependencyEstimator
from backend.nettrace.topology.incremental import IncrementalTopology
from experiments import incremental_topology_benchmark as IB
from experiments import streaming_dependency_benchmark as B

TOL = 1e-9


def test_empty_estimator_has_no_dependencies_or_candidates():
    est = StreamingDependencyEstimator("c")
    assert est.ingest([]) == 0 and est.dependencies() == [] and est.candidates() == []


def test_ingest_reports_old_and_new_units_and_keeps_stats_equality():
    pk = IB.scenario_packets("small", 42)[:30]
    inc = IncrementalTopology(IB.CAPTURE)
    first = inc.ingest(pk[:15])
    assert all(before == () and len(after) >= 1 for _, before, after in first.changes)
    second = inc.ingest(pk[15:])
    assert any(before and after != before for _, before, after in second.changes)  # a known flow grew
    assert first == first.__class__(first.packets, first.flow_keys_touched, first.flow_keys_total, first.new_ips)


@pytest.mark.parametrize("mode", ["in_order", "shuffled"])
def test_every_chunk_matches_batch_on_matrix_traffic(mode, tmp_path):
    pk = IB.sample_packets(IB.scenario_packets("medium", 42), 0.5, 42)
    row = B.check_stream("matrix", pk, mode, "ten", 42, tmp_path)
    assert row.first_mismatch is None
    assert row.structure_matches == row.candidate_matches == row.checks > 0
    assert row.max_abs_diff < TOL


def test_every_packet_prefix_matches_batch_on_smallest_scenario(tmp_path):
    pk = IB.scenario_packets("small", 42)[:60]
    row = B.check_stream("matrix", pk, "in_order", "single", 42, tmp_path)
    assert row.first_mismatch is None and row.checks == 60 and row.max_abs_diff < TOL


def test_lagged_traffic_with_nonzero_temporal_precedence_matches_batch(tmp_path):
    seen_temporal = False
    for level in ("large", "multi_service"):
        pk = B.lagged_packets(level, 42)[:1500]
        est = StreamingDependencyEstimator(IB.CAPTURE)
        for end in (500, 1000, 1500):
            est.ingest(pk[end - 500:end])
            got = est.dependencies()
            ref, ref_cands, _, _ = B.batch_dependencies(pk[:end], tmp_path)
            ok, diff = B.compare(got, ref)
            assert ok and diff < TOL
            assert B._candidate_ids(est.candidates()) == B._candidate_ids(ref_cands)
            seen_temporal |= any(d.temporal_precedence_score > 0 for d in ref)
    assert seen_temporal, "no cell exercised a non-zero temporal precedence score"


def test_node_ids_shifting_as_new_ips_appear_still_match_batch(tmp_path):
    # A late-arriving earlier-observed IP renumbers nodes; orientation and dependency ids must follow batch.
    pk = IB.scenario_packets("small", 43)
    late_first = sorted(pk, key=lambda p: p.timestamp)
    arrival = late_first[len(late_first) // 2:] + late_first[: len(late_first) // 2]
    est = StreamingDependencyEstimator(IB.CAPTURE)
    est.ingest(arrival[: len(arrival) // 2])
    est.ingest(arrival[len(arrival) // 2:])
    ref, _, _, _ = B.batch_dependencies(arrival, tmp_path)
    ok, diff = B.compare(est.dependencies(), ref)
    assert ok and diff < TOL


def test_second_read_recomputes_nothing_and_touched_pairs_are_bounded():
    pk = IB.scenario_packets("multi_service", 42)
    est = StreamingDependencyEstimator(IB.CAPTURE)
    est.ingest(pk[: len(pk) // 2])
    est.dependencies()
    assert est.dependencies() == est.dependencies() and est.pairs_recomputed_last == 0
    est.ingest(pk[len(pk) // 2: len(pk) // 2 + 5])
    est.dependencies()
    assert 0 < est.pairs_recomputed_last <= len(est.dependencies())


def test_udp_session_retraction_matches_batch(tmp_path):
    # UDP sessions split on idle gaps; a later packet can merge or add units, exercising retract-then-add.
    pk = IB.udp_session_packets(42)
    row = B.check_stream("udp", pk, "in_order", "random", 7, tmp_path)
    assert row.first_mismatch is None and row.max_abs_diff < TOL
