"""Temporal precedence analysis (spec Phase 52, FR-1.27 first half: "analyze
temporal precedence between component changes as one input to
dependency/causal candidate generation").

The algorithm is already committed, not decided here: `docs/architecture/
algorithm_selection.md` section 6 selected "time-lagged cross-correlation
for temporal precedence" as part of the same weighted multi-signal scoring
function that already produces `DependencyEdge.strength` (Phase 51),
explicitly stating that approach "produc[es] the `DependencyEdge.strength`
and `temporal_precedence_score` fields ... from the same combined scoring
function" -- so this module's output is meant to fold back into Phase 51's
`estimate_dependency_strength` (`backend/dependency/strength.py`), not
stand alone.

What "changes" means here: per-node flow activity, time-bucketed by
`Flow.first_seen`, not Phase 45/47's structural `GraphChangeEvent`s (which
the research behind this phase confirmed are sparse per node -- essentially
one NODE_ADDED event ever, since topology reconstruction is cumulative with
no expiry) and not Phase 46's `BehavioralEvolutionEvent` (only available
from a caller-supplied fingerprint list -- no persisted multi-batch history
exists yet). Flow activity keeps this phase self-sufficient and automatic
like Phase 50/51, and is information-dense enough to support real
cross-correlation. A node's OVERALL activity (with any counterpart, not
just the other side of this specific edge) is used, to avoid conflating
this signal with the already-separate directionality signal.

Never imports `simulator.ground_truth` (spec §4;
`scripts/check_ground_truth_boundary.py` would reject it if it did).
"""

from __future__ import annotations

import statistics
from datetime import datetime
from typing import List, Optional

from backend.app.models.flow import Flow
from backend.app.models.topology import Node
from backend.flowmind.features.node_features import flows_touching_node

_DEFAULT_BUCKET_SECONDS = 10.0  # mirrors Settings.dependency_temporal_bucket_seconds
_DEFAULT_MAX_LAG_BUCKETS = 5  # mirrors Settings.dependency_temporal_max_lag_buckets


def _bucket_counts(
    flows: List[Flow], node: Node, bucket_seconds: float, start: datetime, num_buckets: int
) -> List[int]:
    """Buckets `flows` touching `node` into `num_buckets` fixed-width
    windows of `bucket_seconds`, starting at `start`, counted by
    `Flow.first_seen`."""
    counts = [0] * num_buckets
    for flow in flows_touching_node(flows, node):
        offset = (flow.first_seen - start).total_seconds()
        index = int(offset // bucket_seconds)
        if 0 <= index < num_buckets:
            counts[index] += 1
    return counts


def _times_to_counts(times: List[datetime], bucket_seconds: float, start: datetime, num_buckets: int) -> List[int]:
    counts = [0] * num_buckets
    for t in times:
        index = int((t - start).total_seconds() // bucket_seconds)
        if 0 <= index < num_buckets:
            counts[index] += 1
    return counts


def _correlation(a: List[float], b: List[float]) -> Optional[float]:
    """Pearson correlation coefficient via stdlib `statistics.correlation`
    (the same module this project already uses for robust statistics --
    `node_baseline.py`'s median/MAD). `None` when undefined (either series
    has zero variance, or fewer than 2 overlapping points) -- honestly "no
    evidence," never fabricated as `0.0` internally (the caller decides
    what "no evidence" means for the final score)."""
    if len(a) < 2 or len(b) < 2:
        return None
    try:
        return statistics.correlation(a, b)
    except statistics.StatisticsError:
        return None


def estimate_temporal_precedence(
    flows: List[Flow],
    source_node: Node,
    target_node: Node,
    bucket_seconds: float = _DEFAULT_BUCKET_SECONDS,
    max_lag_buckets: int = _DEFAULT_MAX_LAG_BUCKETS,
) -> float:
    """Estimates the strength of evidence that `source_node`'s flow
    activity precedes `target_node`'s (`DependencyEdge.temporal_precedence_score`'s
    own docstring: "strength of evidence that source-side changes precede
    target-side changes"), via time-lagged cross-correlation of each
    node's per-bucket flow-activity count over a bounded set of positive
    lag offsets (`algorithm_selection.md` section 6's committed design).

    Returns the best positive-lag correlation (`lag = 1..max_lag_buckets`,
    `target[t]` paired with `source[t - lag]`) only when it is both
    positive AND strictly stronger than the zero-lag (simultaneous)
    correlation -- a merely-simultaneous relationship is deliberately not
    counted as "precedes," since that would overclaim a lagged
    relationship that isn't actually there. Returns `0.0` for empty
    input, insufficient overlapping data, or when no lag search beats the
    zero-lag baseline -- never an error, never a fabricated score.
    """
    source_times = [f.first_seen for f in flows_touching_node(flows, source_node)]
    target_times = [f.first_seen for f in flows_touching_node(flows, target_node)]
    return precedence_from_times(source_times, target_times, bucket_seconds, max_lag_buckets)


def precedence_from_times(
    source_times: List[datetime],
    target_times: List[datetime],
    bucket_seconds: float = _DEFAULT_BUCKET_SECONDS,
    max_lag_buckets: int = _DEFAULT_MAX_LAG_BUCKETS,
) -> float:
    """`estimate_temporal_precedence` over the `first_seen` times of each node's touching flows (shared with
    Phase 87's streaming estimator, which keeps those times per node instead of re-filtering every flow)."""
    all_times = source_times + target_times
    if not all_times:
        return 0.0

    start = min(all_times)
    end = max(all_times)
    span_seconds = (end - start).total_seconds()
    num_buckets = int(span_seconds // bucket_seconds) + 1

    source_series = _times_to_counts(source_times, bucket_seconds, start, num_buckets)
    target_series = _times_to_counts(target_times, bucket_seconds, start, num_buckets)

    zero_lag = _correlation(source_series, target_series) or 0.0

    best_correlation = 0.0
    for lag in range(1, min(max_lag_buckets, num_buckets - 1) + 1):
        r = _correlation(source_series[: num_buckets - lag], target_series[lag:])
        if r is not None and r > best_correlation:
            best_correlation = r

    if best_correlation > zero_lag and best_correlation > 0.0:
        return min(1.0, best_correlation)
    return 0.0
