"""Phase 105: the evolving topology, the drift statistics and the recalibration checkpoint, on planted and real inputs."""

from __future__ import annotations

import numpy as np
import pytest

import experiments.drift_study as ds
from backend.app.models.behavior import ServiceRole
from experiments.matrix_runner import TOPOLOGY_LEVELS, run_matrix_cell

FIELDS = ("precision", "recall", "f1", "false_positive_rate", "false_negative_rate", "detection_latency_seconds",
          "graph_similarity", "calibration_error")


def _sig(scenario):
    roles, edges = scenario
    return sorted((n, r.value) for n, r in roles.items()), sorted((e.source, e.target) for e in edges)


def test_evolution_is_deterministic_connected_and_changes_every_week():
    prev = None
    for week in range(12):
        scenario = ds.evolve_topology(week)
        roles, edges = scenario
        assert ds._connected(roles, edges)
        assert roles[ds.ROOT_NODE] == ServiceRole.CLIENT
        assert all(e.source in roles and e.target in roles and e.source != e.target for e in edges)
        assert _sig(scenario) == _sig(ds.evolve_topology(week))
        if prev is not None:
            assert _sig(scenario) != prev
        prev = _sig(scenario)
    assert _sig(ds.evolve_topology(3, seed=8)) != _sig(ds.evolve_topology(3, seed=7))
    with pytest.raises(ValueError):
        ds.evolve_topology(-1)


def test_scenario_argument_is_bit_identical_to_named_topology_and_none_is_unchanged(tmp_path):
    a = run_matrix_cell(tmp_path / "a", "small", 1.0, seed=5, evaluate_anomaly=False)
    b = run_matrix_cell(tmp_path / "b", "label-only", 1.0, seed=5, evaluate_anomaly=False, scenario=TOPOLOGY_LEVELS["small"]())
    assert [m.context for m in a.metrics] == [m.context for m in b.metrics]
    for ma, mb in zip(a.metrics, b.metrics):
        assert {f: getattr(ma, f) for f in FIELDS} == {f: getattr(mb, f) for f in FIELDS}
    with pytest.raises(KeyError):
        run_matrix_cell(tmp_path / "c", "label-only", 1.0, seed=5)  # without `scenario`, an unknown level is still an error


def test_first_sustained_degradation_ignores_a_single_dip():
    means = [1.0, 1.0, 1.0, 0.5, 1.0, 1.0, 0.5, 0.5, 0.4]
    assert ds.first_sustained_degradation(means, 1.0, 0.05) == 6
    assert ds.first_sustained_degradation([1.0, 0.5, 1.0, 0.5, 1.0], 1.0, 0.05) is None
    assert ds.first_sustained_degradation([0.1, 0.1, 0.4, 0.5, 0.6], 0.1, 0.02, higher_is_worse=True) == 2
    assert ds.first_sustained_degradation([1.0, 0.99, 0.98, 0.97], 1.0, 0.05) is None  # within the spread


def _series(values, rng, sd=0.01, seeds=4):
    return [list(v + rng.normal(0, sd, seeds)) for v in values]


def test_drift_stats_planted_trend_flat_and_constant():
    rng = np.random.default_rng(3)
    weeks = list(range(12))
    down = ds.drift_stats(weeks, _series([0.9 - 0.02 * w for w in weeks], rng), [8 + w for w in weeks])
    assert down["trend"] == "significant worsening" and down["slope_per_week"] == pytest.approx(-0.02, abs=0.004)
    assert down["first_sustained_degradation_week"] is not None and down["kendall_p"] < 0.01
    up_err = ds.drift_stats(weeks, _series([0.05 + 0.01 * w for w in weeks], rng), [8] * 12, higher_is_worse=True)
    assert up_err["trend"] == "significant worsening"
    flat = ds.drift_stats(weeks, _series([0.8] * 12, rng, sd=0.02), [8 + w for w in weeks])
    assert flat["trend"] == "no significant trend" and flat["first_sustained_degradation_week"] is None
    const = ds.drift_stats(weeks, [[0.5] * 4 for _ in weeks], [8] * 12)
    assert const["trend"].startswith("flat") and const["kendall_p"] is None


def test_small_end_to_end_study_with_a_real_checkpoint(tmp_path):
    rep = ds.run_drift_study(tmp_path, weeks=3, seeds=[1, 2], checkpoints=[0], n_init=2, n_iter=0,
                             train_seeds=[1], validation_seeds=[2, 3])
    assert [w["week"] for w in rep["weekly"]] == [0, 1, 2]
    assert all(len(rep["per_seed"][m]) == 3 and len(rep["per_seed"][m][0]) == 2 for m in ds.METRICS)
    cp = rep["checkpoints"][0]
    assert cp["week"] == 0 and isinstance(cp["recalibration_necessary"], bool) and len(cp["groups"]) == 3 and cp["cells_run"] > 0
    for g in cp["groups"]:  # the pre-registered rule is applied as documented
        assert g["adopt"] == (g["gain"] > max(g["baseline_spread"], 1e-9) and all("regressed" not in r for r in g["reasons"]))
    assert isinstance(rep["recalibration_necessary_weeks"], list) and set(rep["recalibration_necessary_weeks"]) <= {0, 1, 2}
    assert (tmp_path / "drift" / "report.json").is_file()
    md = (tmp_path / "drift" / "report.md").read_text(encoding="utf-8")
    assert "Synthetic" in md and "Resolution limit" in md
