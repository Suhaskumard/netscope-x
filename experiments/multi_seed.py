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

import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from experiments.matrix_runner import (
    ABLATIONS,
    OBSERVATION_COMPLETENESS_LEVELS,
    TOPOLOGY_LEVELS,
    persist_cell,
    run_matrix_cell,
)

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
class MetricSummary:
    n: int
    mean: Optional[float]
    stdev: Optional[float]
    min: Optional[float]
    max: Optional[float]


@dataclass(frozen=True)
class MultiSeedCellSummary:
    topology_level: str
    completeness: float
    ablation: Optional[str]
    seeds: List[int]
    metrics: Dict[str, Dict[str, MetricSummary]]


def summarize_values(values: Sequence[Optional[float]]) -> MetricSummary:
    """n/mean/sample-stdev/min/max over the non-`None` values. Sample
    stdev (n-1 denominator) is `None` below 2 values; everything but `n`
    is `None` when there are no values at all."""
    present = [float(v) for v in values if v is not None]
    if not present:
        return MetricSummary(n=0, mean=None, stdev=None, min=None, max=None)
    return MetricSummary(
        n=len(present),
        mean=statistics.fmean(present),
        stdev=statistics.stdev(present) if len(present) >= 2 else None,
        min=min(present),
        max=max(present),
    )


def run_multi_seed_cell(
    root: Path,
    topology_level: str,
    completeness: float,
    seeds: Sequence[int],
    ablation: Optional[str] = None,
    packets_per_edge: int = 15,
    persist: bool = True,
) -> MultiSeedCellSummary:
    """Runs one matrix cell for real once per seed and summarizes every
    (context, field) pair across those runs."""
    collected: Dict[str, Dict[str, List[Optional[float]]]] = {}
    for seed in seeds:
        cell = run_matrix_cell(root, topology_level, completeness, seed=seed, ablation=ablation, packets_per_edge=packets_per_edge)
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
    )


def run_multi_seed_matrix(
    root: Path,
    seeds: Optional[Sequence[int]] = None,
    topology_levels: Optional[List[str]] = None,
    completeness_levels: Optional[List[float]] = None,
    run_ablations: bool = True,
    packets_per_edge: int = 15,
    persist: bool = True,
) -> List[MultiSeedCellSummary]:
    """The same cell set as `run_full_matrix` (every topology x completeness
    baseline cell, plus each topology's 4 ablations at completeness 1.0),
    each run once per seed and summarized."""
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
    return summaries


def format_summary(summary: Optional[MetricSummary]) -> str:
    """`mean ± stdev [min, max]` to 3 d.p.; `n/a` when no seed produced a value."""
    if summary is None or summary.n == 0:
        return "n/a"
    stdev = f"{summary.stdev:.3f}" if summary.stdev is not None else "n/a"
    return f"{summary.mean:.3f} ± {stdev} [{summary.min:.3f}, {summary.max:.3f}]"


def format_markdown_table(summaries: Sequence[MultiSeedCellSummary], columns: Sequence[Tuple[str, str]]) -> str:
    """One row per cell, one column per (context, field) pair."""
    header = ["topology", "completeness", "ablation"] + [f"{context} {field}" for context, field in columns]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for s in summaries:
        row = [s.topology_level, f"{s.completeness:g}", s.ablation or "baseline"]
        row += [format_summary(s.metrics.get(context, {}).get(field)) for context, field in columns]
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)
