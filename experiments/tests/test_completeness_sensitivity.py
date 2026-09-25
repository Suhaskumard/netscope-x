"""Phase 74 observation-completeness sensitivity sweep tests (pure, no Docker).

Cells are run for real (real packet generation, sampling, pipeline and
scoring). See `docs/architecture/experimental_matrix.md`'s "Phase 74"
section for real numbers from a full run.
"""

from __future__ import annotations

import statistics
from pathlib import Path

import pytest

from experiments.artifacts.paths import experiment_run_dir
from experiments.matrix_runner import (
    ABLATIONS,
    SENSITIVITY_SWEEP,
    edge_survival_check,
    format_sensitivity_table,
    run_full_matrix,
    run_matrix_cell,
)


def _topology_f1(cell) -> float:
    return next(m.f1 for m in cell.metrics if m.context.value == "topology_reconstruction")


def test_sweep_cell_has_its_own_id_and_records_its_settings(tmp_path: Path) -> None:
    default = run_matrix_cell(tmp_path, "small", 1.0, seed=3, packets_per_edge=8)
    sweep = run_matrix_cell(tmp_path, "small", 1.0, seed=3, **SENSITIVITY_SWEEP)
    assert default.experiment.experiment_id == "matrix-small-1p0-baseline-3"
    assert sweep.experiment.experiment_id == "matrix-small-1p0-baseline-lowvol-3"
    config = sweep.experiment.configuration
    assert (config["variant"], config["packets_per_edge"], config["pulse_cycles"]) == ("lowvol", 1, 0)
    assert default.experiment.configuration["variant"] is None


def test_pulse_cycles_zero_really_removes_pulse_traffic() -> None:
    with_pulses = edge_survival_check("medium", 1.0, seed=3, packets_per_edge=1)
    without = edge_survival_check("medium", 1.0, seed=3, packets_per_edge=1, pulse_cycles=0)
    assert without.mean_packets_per_edge == 2.0  # 1 request + 1 response
    assert with_pulses.mean_packets_per_edge > without.mean_packets_per_edge


def test_sweep_topology_f1_really_drops_with_completeness_on_large(tmp_path: Path) -> None:
    full = run_matrix_cell(tmp_path, "large", 1.0, seed=42, **SENSITIVITY_SWEEP)
    quarter = run_matrix_cell(tmp_path, "large", 0.25, seed=42, **SENSITIVITY_SWEEP)
    assert _topology_f1(full) == 1.0
    assert _topology_f1(quarter) < 0.9


def test_default_volume_keeps_every_edge_even_at_quarter_completeness() -> None:
    survival = edge_survival_check("large", 0.25, seed=42)
    assert survival.expected_survival > 0.999
    assert survival.observed_survival == 1.0


def test_observed_survival_matches_the_analytic_expectation_across_seeds() -> None:
    observed = [edge_survival_check("large", 0.5, seed=s, packets_per_edge=1, pulse_cycles=0).observed_survival for s in range(20)]
    expected = edge_survival_check("large", 0.5, seed=0, packets_per_edge=1, pulse_cycles=0).expected_survival
    assert expected == pytest.approx(0.75)
    assert statistics.fmean(observed) == pytest.approx(expected, abs=0.05)


def test_full_matrix_persists_sweep_cells_and_can_skip_them(tmp_path: Path) -> None:
    with_sweep = run_full_matrix(tmp_path / "a", topology_levels=["small"], completeness_levels=[1.0, 0.5], seed=4)
    assert len(with_sweep) == 2 + len(ABLATIONS) + 2
    for completeness in ("1p0", "0p5"):
        assert (experiment_run_dir(tmp_path / "a", f"matrix-small-{completeness}-baseline-lowvol-4", 1) / "experiment.json").exists()
    table = format_sensitivity_table(with_sweep).splitlines()
    assert table[0] == "| topology | metric | c=1 | c=0.5 |"
    assert len(table) == 2 + 4  # one row per reported metric for the one topology

    without = run_full_matrix(
        tmp_path / "b", topology_levels=["small"], completeness_levels=[1.0, 0.5], seed=4, run_sensitivity_sweep=False
    )
    assert len(without) == 2 + len(ABLATIONS)
