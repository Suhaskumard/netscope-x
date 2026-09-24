"""n/mean/sample-stdev/min/max summaries shared by Phase 72's multi-seed
variance reporting (`experiments/multi_seed.py`) and Phase 73's
multi-target failure sweep (`experiments/matrix_runner.py`). Lives here,
not in `multi_seed.py`, because `multi_seed` imports `matrix_runner` --
`matrix_runner` importing it back would be a cycle.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Optional, Sequence


@dataclass(frozen=True)
class MetricSummary:
    n: int
    mean: Optional[float]
    stdev: Optional[float]
    min: Optional[float]
    max: Optional[float]


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


def format_summary(summary: Optional[MetricSummary]) -> str:
    """`mean ± stdev [min, max]` to 3 d.p.; `n/a` when there are no values."""
    if summary is None or summary.n == 0:
        return "n/a"
    stdev = f"{summary.stdev:.3f}" if summary.stdev is not None else "n/a"
    return f"{summary.mean:.3f} ± {stdev} [{summary.min:.3f}, {summary.max:.3f}]"
