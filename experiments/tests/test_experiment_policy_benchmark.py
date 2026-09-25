"""Phase 80: experiment-policy benchmark harness -- reward, held-out accounting, protocol."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import experiments.experiment_policy_benchmark as bench
from backend.dependency.experiment_policy import LinUCBPolicy, RandomPolicy, StaticPolicy
from experiments.experiment_policy_benchmark import (
    EpisodeResult,
    build_twin_case,
    evaluate_experiment,
    format_curve_table,
    format_policy_table,
    format_repair_table,
    format_topology_table,
    pretrain_linucb,
    run_episode,
    run_policy_benchmark,
)


def test_reward_is_one_minus_the_real_phase_63_f1(tmp_path: Path) -> None:
    case = build_twin_case(tmp_path, "medium", 0.5, 42)
    episode = run_episode(case, RandomPolicy(seed=1), budget=1)
    (pick,) = episode.picks
    f1, _cf = evaluate_experiment(case, case.graph, pick)  # recomputed independently, on the un-repaired twin
    assert episode.rewards == [pytest.approx(1.0 - f1)]
    assert 0.0 <= episode.rewards[0] <= 1.0


def test_heldout_accuracy_excludes_every_tested_node(tmp_path: Path) -> None:
    case = build_twin_case(tmp_path, "small", 1.0, 42)  # 3 nodes: budget 4 tests them all
    episode = run_episode(case, RandomPolicy(seed=1), budget=4)
    assert episode.n_experiments == 3
    assert episode.a_held_start is None and episode.a_held_end is None  # nothing left held out
    assert episode.gain_held_per_experiment is None
    partial = run_episode(case, RandomPolicy(seed=1), budget=1)
    assert partial.a_held_start is not None  # two nodes remain held out


def test_static_policy_can_run_fewer_experiments_than_the_budget(tmp_path: Path) -> None:
    case = build_twin_case(tmp_path, "medium", 0.5, 42)  # a star: Phase 67 recommends only the hub
    episode = run_episode(case, StaticPolicy(case.graph), budget=4)
    assert 1 <= episode.n_experiments < 4
    assert episode.a_all_curve and len(episode.a_all_curve) == episode.n_experiments + 1


def test_episode_gain_arithmetic() -> None:
    episode = EpisodeResult("x", "l", 0.5, 1, ["a", "b"], [0.5, 0.0], [0.8, 0.9, 1.0], 0.8, 1.0, 0.7, 0.9, 0.6, 0.6, 1, 0)
    assert episode.gain_all == pytest.approx(0.2) and episode.n_experiments == 2
    assert episode.gain_all_per_experiment == pytest.approx(0.1)
    assert episode.gain_held_per_experiment == pytest.approx(0.1)
    none = EpisodeResult("x", "l", 0.5, 1, [], [], [0.8], 0.8, 0.8, None, None, 0.6, 0.6, 0, 0)
    assert none.gain_all_per_experiment is None


def test_pretraining_updates_the_policy_and_skips_accuracy_scoring(tmp_path: Path) -> None:
    cases = [build_twin_case(tmp_path, "multi_path", 0.5, s) for s in (100, 101)]
    fresh = LinUCBPolicy()
    trained = pretrain_linucb(cases, budget=3)
    assert not np.array_equal(trained.A, fresh.A) and not np.array_equal(trained.b, fresh.b)
    episode = run_episode(cases[0], LinUCBPolicy(), budget=2, score_accuracy=False)
    assert episode.a_all_curve == [] and episode.picks


def test_protocol_guards(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        run_policy_benchmark(tmp_path, levels=["small", "medium"], test_seeds=[42], train_seeds=[42])
    with pytest.raises(ValueError):
        run_policy_benchmark(tmp_path, levels=["small"], test_seeds=[42], train_seeds=[100])
    with pytest.raises(ValueError):
        run_policy_benchmark(tmp_path, levels=["small", "medium"], completeness_levels=[0.5], test_seeds=[42],
                             train_seeds=[100], policies=("bogus",))


def test_benchmark_is_deterministic_and_holds_out_the_test_level(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pretrained_on = []
    real = bench.pretrain_linucb

    def spy(cases, *args, **kwargs):
        pretrained_on.append({c.level for c in cases})
        return real(cases, *args, **kwargs)

    monkeypatch.setattr(bench, "pretrain_linucb", spy)

    def run(root: Path):
        return run_policy_benchmark(root, levels=["small", "medium", "multi_path"], completeness_levels=[0.5],
                                    test_seeds=[42], train_seeds=[100])

    a, b = run(tmp_path / "a"), run(tmp_path / "b")
    key = lambda r: [(e.policy, e.level, e.picks, e.rewards, e.a_all_end) for e in r.episodes]  # noqa: E731
    assert key(a) == key(b)
    assert len(a.episodes) == 3 * 4  # levels x policies (one completeness, one seed)
    for held_out, levels in zip(["small", "medium", "multi_path"], pretrained_on[:3]):
        assert held_out not in levels and len(levels) == 2  # each fold trains on the other levels only
    for table in (format_policy_table(a), format_curve_table(a), format_repair_table(a), format_topology_table(a)):
        assert "static" in table and "random" in table
