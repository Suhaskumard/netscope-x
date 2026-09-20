"""Causal-analysis evaluation, for evaluation purposes only (spec Phase 68,
FR-1.40's `causal_analysis` context; RQ5: "measure dependency precision/
recall... against the ground-truth dependency graph").

Mirrors `experiments/metrics/topology_comparison.py` (Phase 32) and
`failure_propagation_validation.py` (Phase 63) exactly: a pure function
scoring a real, already-computed prediction (`CausalCandidate`, Phase 53)
against caller-supplied ground truth -- it never generates candidates or
ground truth itself.

Ground truth for "dependency" is not a separate concept anywhere in this
repo's `simulator/ground_truth/` -- a declared scenario's edges (Phase 18)
already ARE the intended relationships (client depends on the API it
calls, the API depends on the database it queries). This module accepts
`ground_truth_dependency_pairs` as caller-supplied directed `(source,
target)` node-id pairs for exactly this reason: the caller (Phase 68's
matrix runner) is responsible for resolving declared service names to
inferred node ids via IP address, the same identity problem
`topology_comparison.py` already solved for nodes/edges.

`CausalCandidate.source_node_id -> target_node_id` is meaningfully
directed (Phase 53 requires positive `temporal_precedence_score` for that
specific direction), so pairs are compared directionally, unlike
`topology_comparison.py`'s deliberately-undirected edge matching --
comparing directionally here is the correct choice, not an inconsistency.

Returns a plain `CausalAnalysisEvaluation` dataclass, not a `MetricResult`
directly -- Phase 68's matrix runner wraps the real `Experiment` this
module's caller anchors to; this module itself does no I/O and never
imports `simulator.ground_truth`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Set, Tuple

from backend.dependency.causal_candidates import CausalCandidate


@dataclass(frozen=True)
class CausalAnalysisEvaluation:
    computed_at: datetime

    dependency_precision: float
    dependency_recall: float
    dependency_f1: float

    predicted_count: int
    ground_truth_count: int
    matched_count: int


def _precision_recall_f1(matched: int, predicted: int, actual: int) -> Tuple[float, float, float]:
    """Empty-vs-empty is perfect agreement (1.0/1.0/1.0); empty-vs-nonempty
    is 0.0 on whichever side has nothing -- matching every other evaluation
    module's established convention (`topology_comparison.py` et al.)."""
    if predicted == 0 and actual == 0:
        return 1.0, 1.0, 1.0
    precision = (matched / predicted) if predicted else 0.0
    recall = (matched / actual) if actual else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return precision, recall, f1


def evaluate_causal_analysis(
    candidates: List[CausalCandidate],
    ground_truth_dependency_pairs: List[Tuple[str, str]],
) -> CausalAnalysisEvaluation:
    """Scores `candidates` (real `generate_causal_candidates` output)
    against `ground_truth_dependency_pairs` (real, caller-resolved directed
    `(source_node_id, target_node_id)` pairs). Does no I/O; never mutates
    either argument.
    """
    predicted_pairs: Set[Tuple[str, str]] = {(c.source_node_id, c.target_node_id) for c in candidates}
    actual_pairs: Set[Tuple[str, str]] = set(ground_truth_dependency_pairs)

    matched = len(predicted_pairs & actual_pairs)
    precision, recall, f1 = _precision_recall_f1(matched, len(predicted_pairs), len(actual_pairs))

    return CausalAnalysisEvaluation(
        computed_at=datetime.now(timezone.utc),
        dependency_precision=precision,
        dependency_recall=recall,
        dependency_f1=f1,
        predicted_count=len(predicted_pairs),
        ground_truth_count=len(actual_pairs),
        matched_count=matched,
    )
