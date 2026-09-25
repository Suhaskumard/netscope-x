"""Phase 83: end-to-end uncertainty propagation."""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest

from experiments.matrix_runner import (
    TOPOLOGY_LEVELS,
    _PULSE_CYCLES,
    _PULSE_INTENSITY_RANGE,
    _PULSE_PACKETS_PER_NODE,
    _WAVE_GAP_SECONDS,
)
from experiments.observation_sampling import sample_packets
from experiments.synthetic_traffic import assign_ips, generate_packets_for_scenario
from experiments.uncertainty import band, propagate
from experiments.uncertainty_benchmark import UncertaintyRow, monotonicity, run_cell

SMALL = "small"


def _observed(level: str, completeness: float, seed: int = 42):
    roles, edges = TOPOLOGY_LEVELS[level]()
    ips = assign_ips(list(roles))
    packets = generate_packets_for_scenario(
        roles, edges, ips, "t", seed, packets_per_edge=15, wave_2_edges=max(1, len(edges) // 4),
        wave_gap_seconds=_WAVE_GAP_SECONDS, pulse_cycles=_PULSE_CYCLES,
        pulse_packets_per_node=_PULSE_PACKETS_PER_NODE, pulse_intensity_range=_PULSE_INTENSITY_RANGE,
    )
    return sample_packets(packets, completeness, seed), ips


def test_band_is_percentile_interval():
    b = band(list(range(101)))
    assert (b.low, b.mean, b.high) == (5.0, 50.0, 95.0)
    assert b.width == 90.0


def test_band_of_constant_has_zero_width():
    assert band([0.4] * 10).width == 0.0


def test_propagate_rejects_single_draw(tmp_path):
    observed, _ = _observed(SMALL, 1.0)
    with pytest.raises(ValueError):
        propagate(observed, tmp_path, [], draws=1)


def test_propagate_is_deterministic_for_a_seed(tmp_path):
    observed, ips = _observed("medium", 0.25)
    target = [list(ips.values())[0]]
    a = propagate(observed, tmp_path, target, draws=5, seed=3)
    b = propagate(observed, tmp_path, target, draws=5, seed=3)
    assert a.stage_width == b.stage_width
    assert a.edge_presence == b.edge_presence


def test_width_grows_when_observation_is_noisy(tmp_path):
    hi_obs, ips = _observed("medium", 1.0)
    lo_obs, _ = _observed("medium", 0.25)
    target = [list(ips.values())[0]]
    hi = propagate(hi_obs, tmp_path, target, draws=8, seed=1)
    lo = propagate(lo_obs, tmp_path, target, draws=8, seed=1)
    assert lo.stage_width["topology"] > hi.stage_width["topology"]


def test_empty_observation_gives_empty_uncertainty(tmp_path):
    u = propagate([], tmp_path, [], draws=3, seed=0)
    assert u.edge_presence == {} and u.stage_width["topology"] == 0.0


def test_run_cell_scores_against_truth(tmp_path):
    row = run_cell(SMALL, 1.0, 42, tmp_path, draws=4)
    assert row.edge_blind_rate == 0.0
    assert 0.0 <= row.edge_brier_bootstrap <= 1.0
    assert set(row.widths) == {"topology", "dependency", "pathforge", "combined"}


def _row(level, c, seed, w):
    widths = {"topology": w, "dependency": w, "pathforge": w, "combined": w}
    return UncertaintyRow(level, c, seed, widths, 0.0, 0.0, 0.0, None, None)


def test_monotonicity_criterion_requires_strict_majority():
    wider = [_row("a", 1.0, 1, 0.1), _row("a", 0.25, 1, 0.5), _row("a", 1.0, 2, 0.1), _row("a", 0.25, 2, 0.5)]
    assert monotonicity(wider).criterion_met
    tied = [_row("a", 1.0, 1, 0.2), _row("a", 0.25, 1, 0.2)]
    assert not monotonicity(tied).criterion_met
    assert np.isnan(monotonicity(tied).spearman["combined"][0])


def test_propagation_module_never_imports_ground_truth():
    tree = ast.parse(Path("experiments/uncertainty.py").read_text())
    imported = {
        n.module if isinstance(n, ast.ImportFrom) else a.name
        for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
        for a in (n.names if isinstance(n, ast.Import) else [n])
    }
    assert not any(m and ("ground_truth" in m or "matrix_runner" in m or "synthetic_traffic" in m) for m in imported)
