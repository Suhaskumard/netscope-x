"""Multi-seed variance reporting for the experimental matrix (spec Phase 72:
"Run every Phase 68 matrix cell across multiple traffic-generation seeds
and report variance, per RQ1's own stated requirement, not a single point
estimate").

Orchestration and aggregation only, like `matrix_runner.py` itself: every
number comes from calling the real `run_matrix_cell` once per seed, then
summarizing that cell's real `MetricResult`s per (context, field) as
n/mean/sample-stdev/min/max. No pipeline stage is reimplemented here.

What varies across seeds: `seed` is threaded into
`generate_packets_for_scenario` (packet timing/jitter/pulse intensities)
and `sample_packets` (which packets survive observation loss). What does
NOT vary: the declared topology itself -- every `TOPOLOGY_LEVELS` entry is
fixed (including `dynamic`, whose own generator seed stays 42), so the
reported spread is traffic-generation variance on a fixed network, exactly
the variance the spec asks for.

`None` metric values (e.g. `detection_latency_seconds` when nothing was
detected) are excluded from a summary, not coerced to 0; `n` reports how
many seeds actually contributed a value.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from experiments.matrix_runner import (
    ABLATIONS,
    OBSERVATION_COMPLETENESS_LEVELS,
    SENSITIVITY_SWEEP,
    TOPOLOGY_LEVELS,
    persist_cell,
    run_matrix_cell,
)
from experiments.metrics.summary_stats import MetricSummary, format_summary, summarize_values

DEFAULT_SEEDS: List[int] = list(range(42, 52))

METRIC_FIELDS: Tuple[str, ...] = (
    "precision",
    "recall",
    "f1",
    "graph_similarity",
    "calibration_error",
    "detection_latency_seconds",
)


@dataclass(frozen=True)
class MultiSeedCellSummary:
    topology_level: str
    completeness: float
    ablation: Optional[str]
    seeds: List[int]
    metrics: Dict[str, Dict[str, MetricSummary]]
    variant: Optional[str] = None


def run_multi_seed_cell(
    root: Path,
    topology_level: str,
    completeness: float,
    seeds: Sequence[int],
    ablation: Optional[str] = None,
    packets_per_edge: int = 15,
    persist: bool = True,
    **cell_kwargs,
) -> MultiSeedCellSummary:
    """Runs one matrix cell for real once per seed and summarizes every
    (context, field) pair across those runs. `cell_kwargs` pass through to
    `run_matrix_cell` (e.g. Phase 74's `pulse_cycles`/`variant`)."""
    collected: Dict[str, Dict[str, List[Optional[float]]]] = {}
    for seed in seeds:
        cell = run_matrix_cell(
            root, topology_level, completeness, seed=seed, ablation=ablation, packets_per_edge=packets_per_edge, **cell_kwargs
        )
        if persist:
            persist_cell(root, cell)
        for metric in cell.metrics:
            per_field = collected.setdefault(metric.context.value, {f: [] for f in METRIC_FIELDS})
            for field in METRIC_FIELDS:
                per_field[field].append(getattr(metric, field))

    return MultiSeedCellSummary(
        topology_level=topology_level,
        completeness=completeness,
        ablation=ablation,
        seeds=list(seeds),
        metrics={
            context: {field: summarize_values(values) for field, values in per_field.items()}
            for context, per_field in collected.items()
        },
        variant=cell_kwargs.get("variant"),
    )


def run_multi_seed_matrix(
    root: Path,
    seeds: Optional[Sequence[int]] = None,
    topology_levels: Optional[List[str]] = None,
    completeness_levels: Optional[List[float]] = None,
    run_ablations: bool = True,
    packets_per_edge: int = 15,
    persist: bool = True,
    run_sensitivity_sweep: bool = True,
) -> List[MultiSeedCellSummary]:
    """The same cell set as `run_full_matrix` (every topology x completeness
    baseline cell, each topology's 4 ablations at completeness 1.0, and
    Phase 74's low-volume sweep cells), each run once per seed and summarized."""
    seeds = list(seeds) if seeds is not None else DEFAULT_SEEDS
    levels = topology_levels or list(TOPOLOGY_LEVELS)
    completenesses = completeness_levels or OBSERVATION_COMPLETENESS_LEVELS

    summaries: List[MultiSeedCellSummary] = []
    for level in levels:
        for completeness in completenesses:
            summaries.append(run_multi_seed_cell(root, level, completeness, seeds, packets_per_edge=packets_per_edge, persist=persist))
        if run_ablations:
            for ablation in ABLATIONS:
                summaries.append(
                    run_multi_seed_cell(root, level, 1.0, seeds, ablation=ablation, packets_per_edge=packets_per_edge, persist=persist)
                )
        if run_sensitivity_sweep:
            for completeness in completenesses:
                summaries.append(run_multi_seed_cell(root, level, completeness, seeds, persist=persist, **SENSITIVITY_SWEEP))
    return summaries


def format_markdown_table(summaries: Sequence[MultiSeedCellSummary], columns: Sequence[Tuple[str, str]]) -> str:
    """One row per cell, one column per (context, field) pair."""
    header = ["topology", "completeness", "ablation", "variant"] + [f"{context} {field}" for context, field in columns]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for s in summaries:
        row = [s.topology_level, f"{s.completeness:g}", s.ablation or "baseline", s.variant or "default"]
        row += [format_summary(s.metrics.get(context, {}).get(field)) for context, field in columns]
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)
