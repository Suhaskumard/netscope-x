"""Phase 78: LSTM-vs-MAD anomaly benchmark harness."""

from __future__ import annotations

from pathlib import Path

import pytest

import experiments.sequence_anomaly_benchmark as bench
from backend.flowmind.anomaly.node_anomaly import detect_node_anomalies
from backend.flowmind.baseline.node_baseline import build_node_baseline
from experiments.anomaly_fingerprints import build_epoch_fingerprints
from experiments.anomaly_injection import generate_anomaly_dataset
from experiments.matrix_runner import TOPOLOGY_LEVELS
from experiments.sequence_anomaly_benchmark import (
    SHARED_DIMENSIONS,
    build_bench_example,
    format_cold_start_table,
    format_method_table,
    run_sequence_benchmark,
    score_detections,
)
from experiments.synthetic_traffic import assign_ips


def test_bench_example_has_full_history_and_labels_for_kept_nodes(tmp_path: Path) -> None:
    item = build_bench_example(tmp_path, "medium", 1.0, 1, "default")
    assert item.dataset.baseline_epochs >= 5
    assert all(len(h) == item.dataset.total_epochs for h in item.fingerprints.values())
    assert {l.node_id for l in item.labels} <= set(item.fingerprints)
    assert item.labels  # a spike and a burst were injected and both nodes were observed
    with pytest.raises(ValueError):
        build_bench_example(tmp_path, "medium", 1.0, 1, "bogus")


def test_shared_fingerprint_builder_matches_the_matrix_path(tmp_path: Path) -> None:
    """`build_epoch_fingerprints` (used by the matrix) and the benchmark's split path give the same history."""
    item = build_bench_example(tmp_path, "small", 1.0, 3, "default")
    roles, edges = TOPOLOGY_LEVELS["small"]()
    dataset = generate_anomaly_dataset(roles, edges, assign_ips(list(roles)), "cap", 3, packets_per_edge=15)
    from backend.nettrace.topology.discovery import discover_nodes
    from experiments.anomaly_fingerprints import anomaly_capture_id, write_anomaly_capture

    write_anomaly_capture(tmp_path, "matrixcap", dataset, 1.0, 3)
    nodes = discover_nodes(tmp_path, anomaly_capture_id("matrixcap"))
    via_matrix = build_epoch_fingerprints(tmp_path, "matrixcap", dataset, 1.0, 3, nodes)
    assert {n: [(f.distinct_destinations, f.total_byte_count) for f in h] for n, h in via_matrix.items()}.keys() == {
        n.node_id for n in nodes
    }
    # same packets (same seed) => same per-node feature series, matched by node IP order
    assert sorted(tuple((f.distinct_destinations, f.total_byte_count) for f in h) for h in via_matrix.values()) == sorted(
        tuple((f.distinct_destinations, f.total_byte_count) for f in h) for h in item.fingerprints.values()
    )


def test_mad_returns_nothing_below_its_five_observation_minimum(tmp_path: Path) -> None:
    item = build_bench_example(tmp_path, "medium", 1.0, 2, "default")
    for h in (2, 3, 4):
        detected, _ = bench._mad_detections(item, h)
        assert detected == []
    detected, _ = bench._mad_detections(item, 8)
    assert detected  # sufficient baseline: the injected anomalies (at least) are found
    assert all(a.dimension in SHARED_DIMENSIONS for a in detected)


def test_mad_path_equals_calling_the_real_detector_directly(tmp_path: Path) -> None:
    item = build_bench_example(tmp_path, "small", 1.0, 2, "default")
    detected, dropped = bench._mad_detections(item, 8)
    direct = []
    for history in item.fingerprints.values():
        baseline = build_node_baseline(history[:8])
        for fp in history[8:]:
            direct.extend(detect_node_anomalies(baseline, fp))
    assert len(direct) == len(detected) + dropped


def test_both_methods_are_scored_by_the_real_evaluator_on_identical_labels(tmp_path: Path) -> None:
    result = run_sequence_benchmark(
        tmp_path, levels=["small", "medium", "multi_path"], completeness_levels=[1.0], test_seeds=[42],
        train_seeds=[100], train_completeness=[1.0], variants=("default",), history_lengths=(3, 8), epochs=5,
    )
    assert {s.method for s in result.scores} == {"mad_zscore", "lstm"}
    assert {s.history_epochs for s in result.scores} == {3, 8}
    per_key = {}
    for s in result.scores:
        per_key.setdefault((s.level, s.history_epochs), {})[s.method] = s
    for pair in per_key.values():
        m, l = pair["mad_zscore"], pair["lstm"]
        assert m.true_positives + m.false_negatives == l.true_positives + l.false_negatives  # same label set
        assert m.clean_epoch_checks == l.clean_epoch_checks
    assert all(s.recall == 0.0 for s in result.scores if s.method == "mad_zscore" and s.history_epochs == 3)
    assert set(result.fold_info) == {"small", "medium", "multi_path"}
    assert "| **all** |" in format_method_table(result, "default", 8)
    assert "clean-epoch false-alarm rate" in format_cold_start_table(result, "default")


def test_train_and_test_are_disjoint(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        run_sequence_benchmark(tmp_path, levels=["small", "medium"], test_seeds=[42], train_seeds=[42])
    with pytest.raises(ValueError):
        run_sequence_benchmark(tmp_path, levels=["small"], test_seeds=[42], train_seeds=[100])
    with pytest.raises(ValueError):
        run_sequence_benchmark(tmp_path, levels=["small", "medium"], history_lengths=(1,))


def test_lstm_is_never_trained_on_the_held_out_level(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen = []
    real_fit = bench.fit_sequence_model

    def spy(histories, **kwargs):
        seen.append(len(histories))
        return real_fit(histories, **kwargs)

    monkeypatch.setattr(bench, "fit_sequence_model", spy)
    run_sequence_benchmark(
        tmp_path, levels=["small", "medium", "multi_path"], completeness_levels=[1.0], test_seeds=[42],
        train_seeds=[100], train_completeness=[1.0], variants=("default",), history_lengths=(8,), epochs=2,
    )
    # small=3 nodes, medium=7, multi_path=? -- each fold trains on exactly the *other* levels' node histories
    assert len(seen) == 3 and len(set(seen)) == 3  # three different training sets, one per held-out level


def test_score_returns_none_without_labels(tmp_path: Path) -> None:
    item = build_bench_example(tmp_path, "small", 1.0, 1, "default")
    empty = type(item)(item.level, item.completeness, item.variant, item.seed, item.dataset, item.fingerprints, [])
    assert score_detections(empty, [], 8, "lstm") is None
