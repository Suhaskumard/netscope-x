"""Phase 81: cross-topology transfer benchmark harness."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import experiments.transfer_benchmark as tb
from backend.app.models.behavior import ServiceRole
from backend.flowmind.anomaly.sequence_model import fit_sequence_model
from experiments.transfer_benchmark import (
    ARCHETYPES,
    _build_pool,
    baseline_histories,
    degradation,
    format_anomaly_table,
    format_degradation_table,
    format_role_table,
    role_samples,
    run_transfer_benchmark,
    select_shot_nodes,
)

FAST = dict(
    archetypes=["chain", "multi_path"], train_seeds=[100], support_seeds=[200], test_seeds=[42],
    shots=(1, 2), epochs=8, fine_tune_epochs=3, hidden=4,
)


def test_archetypes_are_distinct_shapes_and_star_levels_share_one_archetype() -> None:
    assert set(ARCHETYPES) == {"chain", "star", "multi_tier", "multi_path", "redundant", "dynamic"}
    from experiments.matrix_runner import TOPOLOGY_LEVELS

    # the reason the split is by archetype: two matrix levels are both stars
    assert {len(TOPOLOGY_LEVELS["medium"]()[0]) - 1, len(TOPOLOGY_LEVELS["multi_service"]()[0]) - 1} == {6, 10}
    assert all(len(makes) == 2 for makes in ARCHETYPES.values())


def test_pool_carries_declared_roles_and_full_history(tmp_path: Path) -> None:
    pool = _build_pool(tmp_path, "chain", [100])
    assert len(pool) == 2
    for item in pool:
        assert item.role_by_node
        assert {ServiceRole.CLIENT, ServiceRole.DATABASE} <= set(item.role_by_node.values())
        assert all(len(h) == item.dataset.total_epochs for h in item.fingerprints.values())
    samples = role_samples(pool)
    assert samples and all(isinstance(role, ServiceRole) for _, role in samples)
    assert all(len(h) == pool[0].dataset.baseline_epochs for h in baseline_histories(pool[:1]))


def test_shot_selection_is_round_robin_over_roles_and_deterministic(tmp_path: Path) -> None:
    pool = _build_pool(tmp_path, "multi_tier", [200])
    three = select_shot_nodes(pool, 3)
    roles = {item.role_by_node[node] for item, node in three}
    assert len(roles) == 3  # one per role before any role repeats
    assert select_shot_nodes(pool, 3) == three
    assert select_shot_nodes(pool, 0) == []
    with pytest.raises(ValueError):
        select_shot_nodes(pool, -1)
    total = sum(len(item.role_by_node) for item in pool)
    assert len(select_shot_nodes(pool, total + 50)) == total  # capped, never invents nodes


def test_seed_sets_must_be_disjoint_and_two_archetypes_required(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        run_transfer_benchmark(tmp_path, **{**FAST, "test_seeds": [100]})
    with pytest.raises(ValueError):
        run_transfer_benchmark(tmp_path, **{**FAST, "archetypes": ["chain"]})
    with pytest.raises(KeyError):
        run_transfer_benchmark(tmp_path, **{**FAST, "archetypes": ["chain", "bogus"]})


def test_fine_tune_starts_from_init_and_changes_weights(tmp_path: Path) -> None:
    pool = _build_pool(tmp_path, "chain", [100])
    histories = baseline_histories(pool)
    base = fit_sequence_model(histories, hidden=4, epochs=5, seed=0)
    tuned = fit_sequence_model(histories[:2], epochs=3, learning_rate=0.003, seed=0, init=base)
    assert tuned.parameter_count == base.parameter_count and tuned.hidden == base.hidden
    assert any(not np.allclose(tuned.params[k], base.params[k]) for k in base.params)
    original = {k: v.copy() for k, v in base.params.items()}
    assert all(np.array_equal(base.params[k], original[k]) for k in original)  # init is not mutated
    zero_steps = fit_sequence_model(histories[:2], epochs=0, seed=0, init=base)
    assert all(np.allclose(zero_steps.params[k], base.params[k]) for k in base.params)


def test_every_fold_reports_all_role_modes(tmp_path: Path) -> None:
    result = run_transfer_benchmark(tmp_path, tasks=("role",), **FAST)
    assert {r.archetype for r in result.role_rows} == {"chain", "multi_path"}
    for a in FAST["archetypes"]:
        modes = {(r.mode, r.shots) for r in result.role_rows if r.archetype == a}
        assert {("in_distribution", 0), ("zero_shot", 0), ("few_shot", 1), ("scratch", 2)} <= modes


def test_unseen_role_is_counted_not_hidden(tmp_path: Path) -> None:
    # chain holds CLIENT/API/DATABASE; multi_path the same -> nothing unseen. Force a real unseen case:
    # zero-shot on `star` (sole GATEWAY carrier when the others are chain/multi_path).
    result = run_transfer_benchmark(tmp_path, tasks=("role",), **{**FAST, "archetypes": ["star", "chain", "multi_path"]})
    star_zero = next(r for r in result.role_rows if r.archetype == "star" and r.mode == "zero_shot")
    assert star_zero.unseen_role_share > 0.0  # the hub's GATEWAY role cannot be learned from the others
    assert star_zero.seen_role_accuracy is not None
    assert star_zero.accuracy <= 1.0 - star_zero.unseen_role_share + 1e-9


def test_anomaly_rows_and_tables(tmp_path: Path) -> None:
    result = run_transfer_benchmark(tmp_path, **FAST)
    for a in FAST["archetypes"]:
        modes = {(r.mode, r.shots) for r in result.anomaly_rows if r.archetype == a}
        assert {("mad_zscore", 0), ("lstm_in_distribution", 0), ("lstm_zero_shot", 0),
                ("lstm_few_shot", 1), ("lstm_scratch", 2)} <= modes
    for r in result.anomaly_rows:
        assert 0.0 <= r.precision <= 1.0 and 0.0 <= r.recall <= 1.0 and 0.0 <= r.f1 <= 1.0
    assert "zero_shot" in format_role_table(result)
    assert "lstm_zero_shot" in format_anomaly_table(result)
    assert "chain" in format_degradation_table(result)


def test_degradation_is_in_distribution_minus_zero_shot(tmp_path: Path) -> None:
    result = run_transfer_benchmark(tmp_path, **FAST)
    d = degradation(result)
    for a in FAST["archetypes"]:
        role = {r.mode: r for r in result.role_rows if r.archetype == a and r.shots == 0}
        assert d[a]["role_accuracy"] == pytest.approx(role["in_distribution"].accuracy - role["zero_shot"].accuracy)


def test_benchmark_is_deterministic(tmp_path: Path) -> None:
    a = run_transfer_benchmark(tmp_path / "a", **FAST)
    b = run_transfer_benchmark(tmp_path / "b", **FAST)
    assert a.role_rows == b.role_rows
    assert a.anomaly_rows == b.anomaly_rows
