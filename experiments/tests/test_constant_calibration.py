"""Phase 82: automated constant calibration."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from backend.app.core.config import Settings
from backend.app.models.metric import MetricContext
from backend.simulation import path_engine
from experiments.calibration.bayes_opt import Dimension, optimize
from experiments.calibration.calibrate import calibrate, cell_set, decide
from experiments.calibration.constants import GROUPS, SPACE, CalibrationConstants
from experiments.matrix_runner import run_matrix_cell

T, C, P = MetricContext.TOPOLOGY_RECONSTRUCTION, MetricContext.CAUSAL_ANALYSIS, MetricContext.TEMPORAL_ANALYSIS


def _quadratic(p):
    return -((math.log10(p["a"]) - 0.5) ** 2) - (p["b"] - 0.7) ** 2


DIMS = [Dimension("a", 0.01, 100.0, log=True), Dimension("b", -2.0, 2.0)]


def test_bo_finds_optimum_and_beats_random_at_same_budget() -> None:
    result = optimize(_quadratic, DIMS, n_init=6, n_iter=18, seed=1, start={"a": 1.0, "b": 0.0})
    assert result.evaluations <= 24
    assert result.best_value > -0.01  # true optimum is 0
    import random

    rng = random.Random(1)
    random_best = max(
        _quadratic({"a": math.exp(rng.uniform(math.log(0.01), math.log(100))), "b": rng.uniform(-2, 2)})
        for _ in range(result.evaluations)
    )
    assert result.best_value >= random_best


def test_bo_is_deterministic_bounded_and_never_worse_than_start() -> None:
    a = optimize(_quadratic, DIMS, n_init=4, n_iter=6, seed=3, start={"a": 1.0, "b": 0.0})
    b = optimize(_quadratic, DIMS, n_init=4, n_iter=6, seed=3, start={"a": 1.0, "b": 0.0})
    assert a.history == b.history
    assert a.best_value >= _quadratic({"a": 1.0, "b": 0.0})
    assert all(0.01 <= h["params"]["a"] <= 100.0 and -2.0 <= h["params"]["b"] <= 2.0 for h in a.history)


def test_bo_handles_integer_dimension_without_repeating_evaluations() -> None:
    dims = [Dimension("k", 1, 5, integer=True)]
    result = optimize(lambda p: -abs(p["k"] - 4), dims, n_init=2, n_iter=10, seed=0, start={"k": 1})
    keys = [h["params"]["k"] for h in result.history]
    assert len(keys) == len(set(keys)) <= 5
    assert result.best_params["k"] == 4 and isinstance(result.best_params["k"], int)


def test_dimension_validation() -> None:
    with pytest.raises(ValueError):
        Dimension("x", 1.0, 1.0)
    with pytest.raises(ValueError):
        Dimension("x", 0.0, 1.0, log=True)


def test_defaults_mirror_settings_and_search_space_contains_them() -> None:
    settings, constants = Settings(), CalibrationConstants()
    for name, value in constants.as_dict().items():
        assert getattr(settings, name) == value
        dim = SPACE[name]
        assert dim.low <= value <= dim.high
    assert {n for g in GROUPS for n in g.constants} == set(constants.as_dict())  # every constant is in one group


def test_default_constants_reproduce_the_unmodified_cell(tmp_path: Path) -> None:
    a = run_matrix_cell(tmp_path, "medium", 0.5, seed=42, capture_id="a", evaluate_anomaly=False)
    b = run_matrix_cell(tmp_path, "medium", 0.5, seed=42, capture_id="b", evaluate_anomaly=False,
                        constants=CalibrationConstants())
    assert [(m.context, m.f1) for m in a.metrics] == [(m.context, m.f1) for m in b.metrics]


def test_a_changed_constant_reaches_the_pipeline(tmp_path: Path) -> None:
    base = run_matrix_cell(tmp_path, "large", 1.0, seed=42, capture_id="a", evaluate_anomaly=False)
    changed = run_matrix_cell(tmp_path, "large", 1.0, seed=42, capture_id="b", evaluate_anomaly=False,
                              constants=CalibrationConstants(causal_candidate_strength_threshold=0.01))
    raw = lambda r: r.raw_evaluations["causal_analysis"]  # noqa: E731
    assert raw(base) != raw(changed)  # a near-zero threshold promotes more candidates
    topo = lambda r: next(m.f1 for m in r.metrics if m.context == T)  # noqa: E731
    assert topo(base) == topo(changed)  # ...and touches nothing upstream


def test_latency_scale_only_matters_for_latency_injection(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from backend.app.models.failure import FailureScenario, FailureType

    edge = SimpleNamespace(confidence=0.8, edge_id="e1")

    def weight(scenario):
        return path_engine._edge_weight(edge, SimpleNamespace(scenario=scenario, degraded_edge_ids=["e1"]))

    node = FailureScenario(scenario_id="s", failure_type=FailureType.NODE_FAILURE, target_node_id="n")
    latency = FailureScenario(scenario_id="l", failure_type=FailureType.LATENCY_INJECTION, target_node_id="n",
                              latency_ms=200.0)
    node_before, latency_before = weight(node), weight(latency)
    monkeypatch.setattr(path_engine, "_DEFAULT_LATENCY_COST_SCALE", 10.0)
    assert weight(node) == node_before  # why the matrix (NODE_FAILURE only) cannot calibrate it
    assert weight(latency) > latency_before


def test_decision_rule() -> None:
    base = {T: [0.50, 0.52, 0.48, 0.50], C: [0.4, 0.4, 0.4, 0.4], P: [1.0, 1.0, 1.0, 1.0]}
    def tuned(t_gain, c_delta=0.0):
        return {T: [v + t_gain for v in base[T]], C: [v + c_delta for v in base[C]], P: base[P]}

    assert decide(base, tuned(0.10), T, (C, P)).adopt  # 0.10 >> spread ~0.017
    small = decide(base, tuned(0.01), T, (C, P))
    assert not small.adopt and "spread" in small.reasons[0]
    assert not decide(base, tuned(-0.05), T, (C, P)).adopt
    blocked = decide(base, tuned(0.10, c_delta=-0.2), T, (C, P))  # guard has zero baseline spread
    assert not blocked.adopt and any("guard" in r for r in blocked.reasons)
    with pytest.raises(ValueError):
        decide(base, {T: [0.5], C: [0.4], P: [1.0]}, T, ())


def test_seed_sets_must_be_disjoint(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        calibrate(tmp_path, train_seeds=[1, 2], validation_seeds=[2, 3])


def test_end_to_end_report_lists_every_constant_and_keeps_defaults_when_not_adopted(tmp_path: Path) -> None:
    cells = cell_set(levels=["small"], completeness=[1.0])
    report = calibrate(
        tmp_path, groups=[GROUPS[0]], train_seeds=[42], validation_seeds=[100, 101],
        train_cells=cells, validation_cells=cells, n_init=2, n_iter=1,
    )
    assert [g.group for g in report.groups] == ["topology"]
    assert {c.name for c in report.groups[0].constants} == set(GROUPS[0].constants)
    group = report.groups[0]
    if not group.decision.adopt:
        assert report.adopted == CalibrationConstants()
    assert group.bo_evaluations >= 1 and report.not_calibratable
