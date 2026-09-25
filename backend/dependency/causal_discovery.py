"""Constraint-based causal discovery over node activity time series (spec addendum Phase 79).

An alternative to Phase 53's correlation-plus-temporal-precedence candidate filter
(`causal_candidates.py`): instead of promoting each communicating pair whose strength and lagged
correlation clear a threshold, it runs a real conditional-independence search, so a link that is explained
by a third node's earlier activity is removed rather than reported.

Algorithm: **time-series PC**, the parent-discovery stage of PCMCI (Runge et al.), implemented directly in
numpy/scipy. Variables are each node's per-bucket flow-activity count (the same bucketing as Phase 52's
`estimate_temporal_precedence`). For every target node j the possible parents are every (node i, lag k)
with 1 <= k <= `max_lag`, tested as parents of X_j(t):

  1. Start with all of them. At conditioning size s = 0, 1, ..., `max_condition_set`, remove a parent when
     it is conditionally independent of X_j(t) given some size-s subset of the other current parents
     (candidates for the subset: the `max_condition_candidates` strongest remaining parents). The current
     parent set is frozen at the start of each level so the result does not depend on iteration order
     (PC-stable).
  2. A final pass re-tests each survivor given the other survivors (the strongest
     `max_condition_candidates` of them) and keeps it only if it is still significant.

Test: partial correlation from least-squares residuals, Fisher-z p-value, significance `alpha`. Orientation
comes from time -- a cause precedes its effect -- so there is no v-structure orientation phase, and a
parent is always the earlier variable. Simultaneous (lag-0) links are not tested, so they are neither found
nor oriented.

Undefined tests are never silently resolved: when the conditioning set is rank-deficient (e.g. one variable
is an exact delayed copy of another, so they cannot be told apart) or the residual variance collapses, the
test cannot be performed; the parent is KEPT and the event is counted (`undefined_tests`). A variable with
no variation at all carries no evidence and is dropped, counted separately (`constant_series`).

Assumptions the method makes (and states in every candidate's rationale): causal sufficiency (no unobserved
common cause), faithfulness, stationarity, linear relationships with Gaussian-like noise, and no
simultaneous effects at the bucket width. Real traffic and Phase 70's synthetic traffic each violate some of
these; how much that matters is measured in `experiments/causal_discovery_benchmark.py`.

**Outputs are candidates, never proven causation** -- the same non-negotiable stance as Phase 53. A
discovered edge means "conditional on the other measured activity, X_i's earlier activity still predicts
X_j"; it is not an intervention result. `to_causal_candidates` returns Phase 53's own `CausalCandidate` type
so it is scored by the unmodified Phase 68 `evaluate_causal_analysis` and printed by
`format_causal_candidate` with `CAUSAL_CANDIDATE_DISCLAIMER`.

Never imports `simulator.ground_truth` (spec §4; `scripts/check_ground_truth_boundary.py`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import combinations
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from scipy.stats import norm

from backend.app.models.flow import Flow
from backend.app.models.topology import Node
from backend.dependency.causal_candidates import CausalCandidate
from backend.dependency.temporal_precedence import _bucket_counts
from backend.flowmind.features.node_features import flows_touching_node

DEFAULT_BUCKET_SECONDS = 10.0  # Phase 52's bucket width
DEFAULT_MAX_LAG = 5  # Phase 52's max lag
DEFAULT_ALPHA = 0.05
DEFAULT_MAX_CONDITION_SET = 3
DEFAULT_MAX_CONDITION_CANDIDATES = 6

ASSUMPTIONS = (
    "assumes causal sufficiency (no unobserved common cause), faithfulness, stationarity, linear "
    "relationships and no simultaneous effects at the bucket width"
)

_RANK_TOLERANCE = 1e-8
_DEGENERATE_RATIO = 1e-6


@dataclass(frozen=True)
class DiscoveredCausalEdge:
    source_node_id: str
    target_node_id: str
    lag_buckets: int
    partial_correlation: float
    p_value: float
    conditioning_size: int


@dataclass(frozen=True)
class CausalDiscoveryResult:
    edges: List[DiscoveredCausalEdge]
    total_tests: int
    undefined_tests: int
    constant_series: int
    bucket_count: int


def fisher_z_p_value(partial_correlation: float, sample_size: int, conditioning_size: int) -> float:
    """Two-sided p-value of H0 "partial correlation = 0" (Fisher z). Needs sample_size - conditioning_size
    > 3; returns 1.0 (no evidence) otherwise."""
    dof = sample_size - conditioning_size - 3
    if dof <= 0:
        return 1.0
    r = max(-1.0 + 1e-12, min(1.0 - 1e-12, partial_correlation))
    z = math.atanh(r) * math.sqrt(dof)
    return float(2.0 * norm.sf(abs(z)))


def activity_matrix(
    flows: Sequence[Flow], nodes: Sequence[Node], bucket_seconds: float = DEFAULT_BUCKET_SECONDS
) -> np.ndarray:
    """[buckets, nodes] flow-arrival counts, bucketed by `Flow.first_seen` from the earliest touching
    flow (the same series Phase 52 correlates). Empty if no node has any flow."""
    touching = [f for node in nodes for f in flows_touching_node(list(flows), node)]
    if not touching:
        return np.zeros((0, len(nodes)))
    start = min(f.first_seen for f in touching)
    end = max(f.first_seen for f in touching)
    num_buckets = int((end - start).total_seconds() // bucket_seconds) + 1
    return np.array(
        [_bucket_counts(list(flows), node, bucket_seconds, start, num_buckets) for node in nodes], dtype=float
    ).T


def _partial_correlation(x: np.ndarray, y: np.ndarray, z: np.ndarray) -> Tuple[Optional[float], bool]:
    """(partial correlation of x and y given the columns of z, defined?). Undefined -- rank-deficient z
    or a residual with (numerically) no variance -- returns (None, False)."""
    if z.shape[1] == 0:
        xr, yr = x - x.mean(), y - y.mean()
    else:
        zc = z - z.mean(axis=0)
        if np.linalg.matrix_rank(zc, tol=_RANK_TOLERANCE * max(1.0, float(np.abs(zc).max()))) < zc.shape[1]:
            return None, False
        xr = (x - x.mean()) - zc @ np.linalg.lstsq(zc, x - x.mean(), rcond=None)[0]
        yr = (y - y.mean()) - zc @ np.linalg.lstsq(zc, y - y.mean(), rcond=None)[0]
    sx, sy = float(np.linalg.norm(xr)), float(np.linalg.norm(yr))
    if sx <= _DEGENERATE_RATIO * max(float(np.linalg.norm(x - x.mean())), 1e-12):
        return None, False
    if sy <= _DEGENERATE_RATIO * max(float(np.linalg.norm(y - y.mean())), 1e-12):
        return None, False
    return float(np.clip(xr @ yr / (sx * sy), -1.0, 1.0)), True


def _discover_parents(
    columns: np.ndarray,
    y: np.ndarray,
    parent_labels: List[Tuple[int, int]],
    alpha: float,
    max_condition_set: int,
    max_candidates: int,
    counters: Dict[str, int],
) -> Dict[Tuple[int, int], Tuple[float, float, int]]:
    """Time-series PC for one target. Returns {(node, lag): (partial correlation, p-value, conditioning
    size)} for the surviving parents."""
    sample = len(y)
    if y.std() == 0:
        counters["constant"] += 1
        return {}

    alive: Dict[int, float] = {}
    info: Dict[int, Tuple[float, float, int]] = {}
    for idx in range(len(parent_labels)):
        x = columns[:, idx]
        if x.std() == 0:
            counters["constant"] += 1
            continue
        counters["tests"] += 1
        r, defined = _partial_correlation(x, y, np.zeros((sample, 0)))
        if not defined:
            counters["undefined"] += 1
            alive[idx], info[idx] = 0.0, (0.0, 1.0, 0)
            continue
        p = fisher_z_p_value(r, sample, 0)
        if p <= alpha:
            alive[idx], info[idx] = abs(r), (r, p, 0)

    for size in range(1, max_condition_set + 1):
        frozen = dict(alive)
        removed = set()
        progressed = False
        for idx in sorted(frozen):
            others = sorted((j for j in frozen if j != idx), key=lambda j: (-frozen[j], j))[:max_candidates]
            if len(others) < size:
                continue
            progressed = True
            for subset in combinations(others, size):
                counters["tests"] += 1
                r, defined = _partial_correlation(columns[:, idx], y, columns[:, list(subset)])
                if not defined:
                    counters["undefined"] += 1
                    continue
                p = fisher_z_p_value(r, sample, size)
                if p > alpha:
                    removed.add(idx)
                    break
                alive[idx], info[idx] = abs(r), (r, p, size)
        for idx in removed:
            alive.pop(idx, None)
            info.pop(idx, None)
        if not progressed:
            break

    # Final pass: each survivor must still be significant given the strongest other survivors.
    survivors = dict(alive)
    for idx in sorted(survivors):
        others = sorted((j for j in survivors if j != idx), key=lambda j: (-survivors[j], j))[:max_candidates]
        counters["tests"] += 1
        r, defined = _partial_correlation(columns[:, idx], y, columns[:, others])
        if not defined:
            counters["undefined"] += 1
            continue
        p = fisher_z_p_value(r, sample, len(others))
        if p > alpha:
            alive.pop(idx)
            info.pop(idx)
        else:
            info[idx] = (r, p, len(others))

    return {parent_labels[idx]: info[idx] for idx in alive}


def discover_from_series(
    series: np.ndarray,
    node_ids: Sequence[str],
    max_lag: int = DEFAULT_MAX_LAG,
    alpha: float = DEFAULT_ALPHA,
    max_condition_set: int = DEFAULT_MAX_CONDITION_SET,
    max_condition_candidates: int = DEFAULT_MAX_CONDITION_CANDIDATES,
) -> CausalDiscoveryResult:
    """Runs time-series PC on a [buckets, nodes] activity matrix and returns one directed edge per ordered
    node pair (source's earlier activity -> target), at that pair's strongest surviving lag. A node's own
    earlier activity is used as a conditioning/parent variable but never reported as an edge. Returns no
    edges (never an error) when there are too few buckets to test anything."""
    if max_lag < 1 or not 0.0 < alpha < 1.0:
        raise ValueError("max_lag must be >= 1 and alpha must lie in (0, 1)")
    buckets, n = series.shape
    if n != len(node_ids):
        raise ValueError("node_ids must match the series' columns")
    counters = {"tests": 0, "undefined": 0, "constant": 0}
    if buckets <= max_lag + 3 or n < 2:
        return CausalDiscoveryResult([], 0, 0, 0, buckets)

    parent_labels = [(i, k) for i in range(n) for k in range(1, max_lag + 1)]
    columns = np.column_stack([series[max_lag - k : buckets - k, i] for i, k in parent_labels])

    best: Dict[Tuple[int, int], Tuple[int, float, float, int]] = {}
    for j in range(n):
        for (i, k), (r, p, size) in _discover_parents(
            columns, series[max_lag:, j], parent_labels, alpha, max_condition_set, max_condition_candidates, counters
        ).items():
            if i == j:
                continue
            if (i, j) not in best or abs(r) > abs(best[(i, j)][1]):
                best[(i, j)] = (k, r, p, size)

    edges = [
        DiscoveredCausalEdge(node_ids[i], node_ids[j], k, r, p, size)
        for (i, j), (k, r, p, size) in sorted(best.items())
    ]
    return CausalDiscoveryResult(edges, counters["tests"], counters["undefined"], counters["constant"], buckets)


def discover_causal_edges(
    flows: Sequence[Flow],
    nodes: Sequence[Node],
    bucket_seconds: float = DEFAULT_BUCKET_SECONDS,
    **kwargs,
) -> CausalDiscoveryResult:
    """`discover_from_series` over `nodes`' flow-arrival series (`activity_matrix`); `kwargs` are its
    `max_lag`/`alpha`/`max_condition_set`/`max_condition_candidates`."""
    series = activity_matrix(flows, nodes, bucket_seconds)
    return discover_from_series(series, [n.node_id for n in nodes], **kwargs)


def to_causal_candidates(edges: Sequence[DiscoveredCausalEdge], alpha: float = DEFAULT_ALPHA) -> List[CausalCandidate]:
    """Wraps discovered edges as Phase 53's `CausalCandidate` (strength and temporal_precedence_score are
    both |partial correlation| at the discovered lag -- a lagged, conditional association, not a Phase 51
    strength), ordered by strength descending, then by pair for determinism."""
    candidates = [
        CausalCandidate(
            dependency_id=f"pc:{e.source_node_id}->{e.target_node_id}",
            source_node_id=e.source_node_id,
            target_node_id=e.target_node_id,
            strength=abs(e.partial_correlation),
            temporal_precedence_score=abs(e.partial_correlation),
            rationale=[
                f"{e.source_node_id}'s activity {e.lag_buckets} bucket(s) earlier is associated with "
                f"{e.target_node_id}'s activity (partial correlation {e.partial_correlation:.3f}, "
                f"p={e.p_value:.4f} < alpha {alpha:.3f}) after conditioning on {e.conditioning_size} other "
                "earlier activity series",
                f"time-series PC {ASSUMPTIONS}",
            ],
        )
        for e in edges
    ]
    return sorted(candidates, key=lambda c: (-c.strength, c.dependency_id))
