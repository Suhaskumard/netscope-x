"""Phase 79: causal-discovery benchmark harness and the parent-driven control dataset."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from backend.dependency.causal_candidates import CausalCandidate
from experiments.causal_discovery_benchmark import (
    SWEEP_ALPHAS,
    build_case,
    evaluate_case,
    format_alpha_sweep_table,
    format_benchmark_table,
    format_diagnostics_table,
    run_causal_benchmark,
    score_candidates,
)
from experiments.causal_generators import parent_driven_traffic
from experiments.matrix_runner import TOPOLOGY_LEVELS
from experiments.synthetic_traffic import assign_ips
from simulator.scenarios.topologies import ScenarioEdge


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.corrcoef(a, b)[0, 1])


def _chain(seed: int = 1):
    roles, edges = TOPOLOGY_LEVELS["small"]()
    return roles, edges, parent_driven_traffic(roles, edges, assign_ips(list(roles)), "cap", seed)


def test_child_follows_its_parent_at_lag_one_not_lag_zero() -> None:
    _, edges, dataset = _chain()
    (a, b), (_, c) = [(e.source, e.target) for e in edges]
    for parent, child in ((a, b), (b, c)):
        p, q = dataset.activity[parent], dataset.activity[child]
        assert _corr(p[:-1], q[1:]) > 0.3 > abs(_corr(p, q))  # lag 1 carries the influence, lag 0 does not
    assert dataset.true_edges == sorted((e.source, e.target) for e in edges)
    assert dataset.dropped_edges == []


def test_generator_is_deterministic_and_seed_sensitive() -> None:
    _, _, one = _chain(3)
    _, _, two = _chain(3)
    _, _, other = _chain(4)
    assert [p.model_dump() for p in one.packets] == [p.model_dump() for p in two.packets]
    assert not np.array_equal(next(iter(one.activity.values())), next(iter(other.activity.values())))


def test_cyclic_declared_edges_are_broken_and_reported() -> None:
    roles = {n: next(iter(TOPOLOGY_LEVELS["small"]()[0].values())) for n in ("a", "b", "c")}
    edges = [ScenarioEdge("a", "b", ["tcp"]), ScenarioEdge("b", "c", ["tcp"]), ScenarioEdge("c", "a", ["tcp"])]
    dataset = parent_driven_traffic(roles, edges, assign_ips(list(roles)), "cap", 1, buckets=20)
    assert len(dataset.true_edges) == 2 and len(dataset.dropped_edges) == 1
    assert set(dataset.true_edges) | set(dataset.dropped_edges) == {("a", "b"), ("b", "c"), ("c", "a")}


def test_build_case_maps_declared_pairs_to_node_ids_by_ip(tmp_path: Path) -> None:
    for dataset in ("phase70", "parent_driven"):
        case = build_case(tmp_path, "small", 1.0, 1, dataset)
        assert len(case.ground_truth) == 2
        assert all(a != b for a, b in case.ground_truth)
        assert all(a.startswith(case.capture_id) for pair in case.ground_truth for a in pair)  # discovered node ids
    with pytest.raises(ValueError):
        build_case(tmp_path, "small", 1.0, 1, "bogus")


def _candidate(a: str, b: str) -> CausalCandidate:
    return CausalCandidate(f"{a}->{b}", a, b, 0.5, 0.5, ["x"])


def test_score_counts_reversed_and_spurious_pairs_separately(tmp_path: Path) -> None:
    case = build_case(tmp_path, "small", 1.0, 1, "phase70")
    case = type(case)(case.dataset, case.level, case.completeness, case.seed, case.root, case.capture_id,
                      [("A", "B"), ("B", "C")], [])
    score = score_candidates(case, "pc", 0.05, [_candidate("B", "A"), _candidate("A", "C"), _candidate("B", "C")])
    assert (score.matched, score.reversed_pairs, score.spurious_pairs) == (1, 1, 1)
    assert score.precision == pytest.approx(1 / 3) and score.recall == pytest.approx(1 / 2)
    # skeleton: {AB, AC, BC} vs truth {AB, BC} -> precision 2/3, recall 1
    assert score.skeleton_f1 == pytest.approx(0.8)


def test_both_methods_are_scored_on_identical_ground_truth(tmp_path: Path) -> None:
    case = build_case(tmp_path, "small", 1.0, 2, "parent_driven")
    scores = evaluate_case(case, SWEEP_ALPHAS)
    assert [s.method for s in scores] == ["phase53"] + ["pc"] * len(SWEEP_ALPHAS)
    assert {s.ground_truth for s in scores} == {2}
    assert [s.alpha for s in scores if s.method == "pc"] == list(SWEEP_ALPHAS)
    assert all(0.0 <= s.f1 <= 1.0 and 0.0 <= s.skeleton_f1 <= 1.0 for s in scores)


def test_run_is_deterministic_and_formats_tables(tmp_path: Path) -> None:
    def run(root: Path):
        return run_causal_benchmark(root, levels=["small", "multi_path"], completeness_levels=[1.0], seeds=[42])

    a, b = run(tmp_path / "a"), run(tmp_path / "b")
    key = lambda r: [(s.dataset, s.method, s.alpha, s.level, s.f1, s.predicted, s.matched) for s in r.scores]  # noqa: E731
    assert key(a) == key(b)
    assert len(a.scores) == 2 * 2 * (1 + len(SWEEP_ALPHAS))  # datasets x levels x (phase53 + pc alphas)
    assert "| **all** |" in format_benchmark_table(a, "phase70")
    assert "skeleton f1" in format_diagnostics_table(a)
    assert "spurious pairs / capture" in format_alpha_sweep_table(a)
