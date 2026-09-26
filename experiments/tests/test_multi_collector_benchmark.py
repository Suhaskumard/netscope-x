"""Phase 90: fused multi-collector graph vs full capture, and the measured failure cases."""

from __future__ import annotations

from experiments import multi_collector_benchmark as B


def test_union_of_collectors_reproduces_the_full_capture_exactly():
    rows = B.run_equivalence(("small", "multi_path"), (42,), (2, 3))
    assert rows and all(r.pairs_equal and r.max_conf_diff < 1e-9 and r.accepted == r.packets_full for r in rows)


def test_pooled_beats_naive_and_confidence_merges_on_a_no_loss_overlap_run():
    r = B.run_quality(("large",), (42,), drop=0.0)[0]
    assert r.mae_pooled < 1e-9 < r.mae_naive and r.mae_pooled < r.mae_union_max and r.resolutions_complete


def test_wide_tolerance_and_beyond_tolerance_skew_are_real_failures():
    got = {r.case: float(r.detail.split()[1]) for r in B.run_failures(("multi_service", "large"), (42,))}
    assert got["keepalive_tol_1.0:false_merges_of_120"] == 60 and got["keepalive_tol_0.001:false_merges_of_120"] == 0
    assert got["skew_beyond_tol:accepted_over_full"] > 1.9 and got["skew_within_tol:accepted_over_full"] == 1.0
    assert got["fabricated_N3_pooled:false_edges_kept"] > 0 and got["fabricated_N3_quorum:false_edges_kept"] == 0
    assert got["segments_N3_quorum:edge_recall"] < got["segments_N3_pooled:edge_recall"]
