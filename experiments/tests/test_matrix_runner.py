"""Phase 68 experimental-matrix runner unit tests (pure, no Docker).

Runs the REAL matrix cell logic (real pipeline execution, real scoring)
over small topology levels for speed -- the full 6x5 sweep plus ablations
is left to `scripts/run_experiment_matrix.py` for a real manual run (see
`docs/architecture/experimental_matrix.md`'s worked example for real
numbers from that run).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.models.metric import MetricContext
from experiments.artifacts.io import read_experiment_run
from experiments.matrix_runner import (
    ABLATIONS,
    TOPOLOGY_LEVELS,
    persist_cell,
    run_matrix_cell,
)


def test_baseline_cell_produces_six_real_metrics(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    cell = run_matrix_cell(root, "small", 1.0, seed=1)

    contexts = {m.context for m in cell.metrics}
    assert contexts == {
        MetricContext.TOPOLOGY_RECONSTRUCTION,
        MetricContext.ROLE_INFERENCE,
        MetricContext.TEMPORAL_ANALYSIS,
        MetricContext.CAUSAL_ANALYSIS,
        MetricContext.PATHFORGE,
        MetricContext.COUNTERFACTUAL,
        MetricContext.ANOMALY_DETECTION,  # Phase 76
    }


def test_perfect_topology_reconstruction_at_full_completeness(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    cell = run_matrix_cell(root, "small", 1.0, seed=1, packets_per_edge=15)

    topo = next(m for m in cell.metrics if m.context == MetricContext.TOPOLOGY_RECONSTRUCTION)
    assert topo.graph_similarity == 1.0


def test_experiment_carries_real_repro1_fields(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    cell = run_matrix_cell(root, "small", 1.0, seed=3)

    exp = cell.experiment
    assert exp.experiment_id
    assert exp.random_seed == 3
    assert exp.configuration["topology_level"] == "small"
    assert exp.configuration["completeness"] == 1.0
    assert exp.results  # real raw evaluation results, not empty


def test_persist_cell_writes_real_files(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    cell = run_matrix_cell(root, "small", 1.0, seed=4)
    persist_cell(root, cell)

    loaded_experiment, loaded_metrics = read_experiment_run(root, cell.experiment.experiment_id)
    assert loaded_experiment.experiment_id == cell.experiment.experiment_id
    assert loaded_experiment.configuration["run_version"] == 1
    assert len(loaded_metrics) == len(cell.metrics)


def test_lower_completeness_still_produces_a_valid_cell(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    cell = run_matrix_cell(root, "medium", 0.25, seed=5)
    assert len(cell.metrics) >= 1  # at minimum topology_reconstruction always runs


@pytest.mark.parametrize("ablation", ABLATIONS)
def test_every_ablation_runs_for_real(tmp_path: Path, ablation: str) -> None:
    root = tmp_path / "artifacts"
    cell = run_matrix_cell(root, "medium", 1.0, seed=6, ablation=ablation)
    assert cell.experiment.configuration["ablation"] == ablation
    assert len(cell.metrics) >= 1


def test_unknown_topology_level_raises(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    with pytest.raises(KeyError):
        run_matrix_cell(root, "no-such-level", 1.0)


def test_unknown_ablation_raises(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    with pytest.raises(ValueError):
        run_matrix_cell(root, "small", 1.0, ablation="no-such-ablation")


def test_without_behavioral_ablation_produces_identical_pathforge_accuracy_to_baseline(tmp_path: Path) -> None:
    """Verified null result (see matrix_runner.py's own docstring): role_classifications
    is never read by any scored field of run_failure_propagation_pipeline/
    compare_counterfactual_outcome, so this ablation's real, honest effect is zero."""
    root = tmp_path / "artifacts"
    baseline = run_matrix_cell(root, "medium", 1.0, seed=8)
    ablated = run_matrix_cell(root, "medium", 1.0, seed=8, ablation="without_behavioral")

    baseline_pathforge = next(m for m in baseline.metrics if m.context == MetricContext.PATHFORGE)
    ablated_pathforge = next(m for m in ablated.metrics if m.context == MetricContext.PATHFORGE)
    assert baseline_pathforge.precision == ablated_pathforge.precision
    assert baseline_pathforge.recall == ablated_pathforge.recall


def test_without_temporal_ablation_produces_zero_causal_candidates(tmp_path: Path) -> None:
    """Real effect of forcing temporal_precedence_score=0.0 before candidate
    generation: Phase 53's own gate requires > 0.0, so nothing is ever promoted."""
    root = tmp_path / "artifacts"
    cell = run_matrix_cell(root, "medium", 1.0, seed=9, ablation="without_temporal")
    causal = cell.raw_evaluations["causal_analysis"]
    assert causal["predicted_count"] == 0


def test_all_topology_levels_run_without_error(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    for level in TOPOLOGY_LEVELS:
        cell = run_matrix_cell(root, level, 1.0, seed=10, packets_per_edge=8)
        assert cell.metrics


def test_phase_70_pulses_give_causal_analysis_a_real_positive_signal(tmp_path: Path) -> None:
    """Phase 70's own fix, verified at the matrix level (not just the generator level):
    before Phase 70, causal_analysis's predicted_count was 0 in every real matrix cell
    (see docs/architecture/experimental_matrix.md's original finding). "large" (multi_tier)
    is one of the topology shapes Phase 70 confirmed reliably shows a real signal across
    seeds -- "small"/"medium"/"multi_path"/"multi_service" still do not (documented
    structural limitation, see matrix_runner.py's own _PULSE_* constants docstring)."""
    root = tmp_path / "artifacts"
    cell = run_matrix_cell(root, "large", 1.0, seed=1)
    causal = cell.raw_evaluations["causal_analysis"]
    assert causal["predicted_count"] > 0
    assert causal["matched_count"] > 0


def test_phase_71_role_inference_reports_in_sample_and_held_out_side_by_side(tmp_path: Path) -> None:
    """Phase 71: the matrix's role_inference result carries BOTH the in-sample score
    (Phase 68's original methodology) and a genuine leave-one-node-out held-out score,
    and the headline MetricResult is the held-out one, not the in-sample one."""
    root = tmp_path / "artifacts"
    cell = run_matrix_cell(root, "medium", 1.0, seed=42)
    role = cell.raw_evaluations["role_inference"]
    assert role["in_sample"]["sample_count"] == role["held_out"]["sample_count"] == role["fold_count"]
    assert role["held_out"]["accuracy"] <= role["in_sample"]["accuracy"]
    headline = next(m for m in cell.metrics if m.context == MetricContext.ROLE_INFERENCE)
    assert headline.precision == role["held_out"]["accuracy"]
