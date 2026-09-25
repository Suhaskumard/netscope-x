"""Phase 77: GNN-vs-heuristic benchmark harness."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import experiments.gnn_benchmark as bench
from backend.nettrace.topology.gnn_edge_model import fit_edge_model, predict_edge_probabilities
from experiments.gnn_benchmark import (
    THRESHOLD,
    build_example,
    expected_calibration_error,
    format_benchmark_table,
    format_edge_flow_table,
    graph_from_probabilities,
    heuristic_thresholded_graph,
    run_benchmark,
)
from experiments.metrics.topology_comparison import compare_topology_to_ground_truth


def test_labels_match_the_declared_edges_by_ip(tmp_path: Path) -> None:
    item = build_example(tmp_path, "small", 1.0, 1, "default")  # chain of 3 -> 2 edges among 3 nodes
    assert item.example.node_count == 3
    assert int(item.labels.sum()) // 2 == 2 == len(item.ground_truth.edges)
    assert np.array_equal(item.labels, item.labels.T)
    # at full observation every declared edge is observed by the heuristic
    assert compare_topology_to_ground_truth(item.graph, item.ground_truth).edge_f1 == 1.0
    assert ((item.example.adjacency > 0) == item.labels).all()


def test_lowvol_loses_edges_that_default_keeps(tmp_path: Path) -> None:
    default = build_example(tmp_path, "large", 0.25, 3, "default")
    lowvol = build_example(tmp_path, "large", 0.25, 3, "lowvol")
    assert len(default.graph.edges) > len(lowvol.graph.edges)


def test_unknown_variant_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        build_example(tmp_path, "small", 1.0, 1, "bogus")


def test_graph_from_probabilities_respects_the_threshold(tmp_path: Path) -> None:
    item = build_example(tmp_path, "medium", 1.0, 2, "lowvol")
    n = item.example.node_count
    probabilities = np.zeros((n, n))
    probabilities[0, 1] = probabilities[1, 0] = 0.9
    probabilities[0, 2] = probabilities[2, 0] = THRESHOLD - 0.01
    graph = graph_from_probabilities(item.graph, item.example, probabilities)
    assert len(graph.edges) == 1
    assert graph.edges[0].confidence == pytest.approx(0.9)
    assert {e.source_node_id for e in graph.edges} | {e.target_node_id for e in graph.edges} <= set(item.example.node_ids)


def test_unobserved_predictions_are_labelled_as_model_predictions(tmp_path: Path) -> None:
    item = build_example(tmp_path, "large", 0.25, 3, "lowvol")
    n = item.example.node_count
    unobserved = [(u, v) for u in range(n) for v in range(u + 1, n) if item.example.adjacency[u, v] == 0]
    u, v = unobserved[0]
    probabilities = np.zeros((n, n))
    probabilities[u, v] = probabilities[v, u] = 0.8
    (edge,) = graph_from_probabilities(item.graph, item.example, probabilities).edges
    assert edge.edge_id.startswith("gnn:") and "no observed flows" in edge.evidence[0]


def test_heuristic_thresholding_drops_low_confidence_edges(tmp_path: Path) -> None:
    item = build_example(tmp_path, "medium", 1.0, 2, "lowvol")
    kept = heuristic_thresholded_graph(item.graph)
    assert all(e.confidence >= THRESHOLD for e in kept.edges)
    assert len(kept.edges) <= len(item.graph.edges)


def test_expected_calibration_error() -> None:
    assert expected_calibration_error(np.array([]), np.array([])) == 0.0
    perfect = expected_calibration_error(np.array([1.0, 1.0, 0.0, 0.0]), np.array([1.0, 1.0, 0.0, 0.0]))
    assert perfect == 0.0
    assert expected_calibration_error(np.array([0.9, 0.9]), np.array([0.0, 0.0])) == pytest.approx(0.9)


def test_benchmark_holds_out_the_test_level_and_seeds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    trained_on: list = []
    real_fit = bench.fit_edge_model

    def spy(examples, labels, **kwargs):
        trained_on.append(len(examples))
        return real_fit(examples, labels, **kwargs)

    monkeypatch.setattr(bench, "fit_edge_model", spy)
    levels = ["small", "medium", "multi_path"]
    result = run_benchmark(
        tmp_path, levels=levels, completeness_levels=[1.0, 0.5], test_seeds=[42, 43], train_seeds=[100],
        variants=("lowvol",), epochs=5,
    )
    assert len(trained_on) == 3  # one model per held-out level
    assert {s.level for s in result.scores} == set(levels)
    assert len(result.scores) == 3 * 2 * 2  # levels x completeness x test seeds
    assert {s.seed for s in result.scores} == {42, 43}
    for score in result.scores:
        assert set(score.f1) == {"heuristic", "heuristic_thresholded", "gnn"}
        assert all(0.0 <= v <= 1.0 for v in score.f1.values())
    assert "| **all** |" in format_benchmark_table(result, "lowvol")
    assert "recovered" in format_edge_flow_table(result)

    with pytest.raises(ValueError):
        run_benchmark(tmp_path, levels=levels, test_seeds=[42], train_seeds=[42])  # overlapping seeds
    with pytest.raises(ValueError):
        run_benchmark(tmp_path, levels=["small"], test_seeds=[42], train_seeds=[100])


def test_gnn_scoring_uses_the_real_topology_comparison(tmp_path: Path) -> None:
    item = build_example(tmp_path, "small", 1.0, 1, "default")
    model = fit_edge_model([item.example], [item.labels], epochs=150, seed=0)
    graph = graph_from_probabilities(item.graph, item.example, predict_edge_probabilities(model, item.example))
    result = compare_topology_to_ground_truth(graph, item.ground_truth)
    assert 0.0 <= result.edge_f1 <= 1.0 and result.ground_truth_edge_count == 2
