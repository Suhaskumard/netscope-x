"""Phase 72 multi-seed variance reporting unit tests (pure, no Docker).

Runs the REAL matrix cell logic over small topology levels and few seeds
for speed -- the full 10-seed sweep is left to
`scripts/run_experiment_matrix.py --n-seeds 10` (see
`docs/architecture/experimental_matrix.md`'s "Phase 72" section for real
numbers from that run).
"""

from __future__ import annotations

import statistics
from pathlib import Path

import pytest

from experiments.artifacts.paths import experiment_run_dir, packets_path
from experiments.matrix_runner import run_matrix_cell
from experiments.multi_seed import (
    DEFAULT_SEEDS,
    MetricSummary,
    MultiSeedCellSummary,
    format_markdown_table,
    format_summary,
    run_multi_seed_cell,
    run_multi_seed_matrix,
    summarize_values,
)


def test_summarize_values_known_values() -> None:
    s = summarize_values([0.5, 1.0, 0.75])
    assert s.n == 3
    assert s.mean == pytest.approx(0.75)
    assert s.stdev == pytest.approx(statistics.stdev([0.5, 1.0, 0.75]))
    assert (s.min, s.max) == (0.5, 1.0)


def test_summarize_values_drops_none_and_handles_small_n() -> None:
    assert summarize_values([None, 0.4, None]) == MetricSummary(n=1, mean=0.4, stdev=None, min=0.4, max=0.4)
    assert summarize_values([None, None]) == MetricSummary(n=0, mean=None, stdev=None, min=None, max=None)
    assert summarize_values([]).n == 0


def test_default_seeds_are_ten_distinct_including_42() -> None:
    assert len(set(DEFAULT_SEEDS)) == 10
    assert 42 in DEFAULT_SEEDS


def test_different_seeds_really_produce_different_traffic(tmp_path: Path) -> None:
    """Guards against the seed being silently ignored, which would make every
    reported stdev trivially 0."""
    root = tmp_path / "artifacts"
    a = run_matrix_cell(root, "small", 1.0, seed=1, packets_per_edge=8)
    b = run_matrix_cell(root, "small", 1.0, seed=2, packets_per_edge=8)
    text_a = packets_path(root, a.experiment.experiment_id).read_text()
    text_b = packets_path(root, b.experiment.experiment_id).read_text()
    assert text_a != text_b


def test_multi_seed_cell_matches_independent_single_seed_runs(tmp_path: Path) -> None:
    seeds = [1, 2, 3]
    summary = run_multi_seed_cell(tmp_path / "multi", "medium", 1.0, seeds, packets_per_edge=8)

    singles = [run_matrix_cell(tmp_path / "single", "medium", 1.0, seed=s, packets_per_edge=8) for s in seeds]
    for context, per_field in summary.metrics.items():
        for field, stats in per_field.items():
            values = [
                getattr(m, field) for cell in singles for m in cell.metrics if m.context.value == context
            ]
            present = [v for v in values if v is not None]
            assert stats.n == len(present)
            if present:
                assert stats.mean == pytest.approx(statistics.fmean(present))
                assert stats.min == pytest.approx(min(present))
                assert stats.max == pytest.approx(max(present))

    # Always-populated headline fields got one value per seed.
    assert summary.metrics["topology_reconstruction"]["f1"].n == len(seeds)
    assert summary.metrics["role_inference"]["precision"].n == len(seeds)


def test_multi_seed_matrix_runs_every_cell_and_persists_every_seed(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    seeds = [5, 6]
    summaries = run_multi_seed_matrix(
        root, seeds=seeds, topology_levels=["small"], completeness_levels=[1.0, 0.5], packets_per_edge=8
    )
    # 2 baseline completeness cells + 4 ablations + 2 Phase 74 low-volume sweep cells.
    assert len(summaries) == 8
    assert [s.ablation for s in summaries][:2] == [None, None]
    assert [s.variant for s in summaries][-2:] == ["lowvol", "lowvol"]
    for s in summaries:
        assert s.seeds == seeds
        tag = (s.ablation or "baseline") + (f"-{s.variant}" if s.variant else "")
        for seed in seeds:
            exp_id = f"matrix-small-{str(s.completeness).replace('.', 'p')}-{tag}-{seed}"
            assert (experiment_run_dir(root, exp_id, 1) / "experiment.json").exists()


def test_format_summary_and_table() -> None:
    assert format_summary(MetricSummary(n=2, mean=0.5, stdev=0.1, min=0.4, max=0.6)) == "0.500 ± 0.100 [0.400, 0.600]"
    assert format_summary(MetricSummary(n=1, mean=0.5, stdev=None, min=0.5, max=0.5)) == "0.500 ± n/a [0.500, 0.500]"
    assert format_summary(None) == "n/a"

    s = MultiSeedCellSummary(
        topology_level="small",
        completeness=0.75,
        ablation=None,
        seeds=[1, 2],
        metrics={"pathforge": {"f1": MetricSummary(n=2, mean=1.0, stdev=0.0, min=1.0, max=1.0)}},
    )
    table = format_markdown_table([s], [("pathforge", "f1"), ("causal_analysis", "f1")])
    lines = table.splitlines()
    assert lines[0] == "| topology | completeness | ablation | variant | pathforge f1 | causal_analysis f1 |"
    assert lines[2] == "| small | 0.75 | baseline | default | 1.000 ± 0.000 [1.000, 1.000] | n/a |"
