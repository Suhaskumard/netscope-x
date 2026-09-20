"""Temporal-analysis evaluation, for evaluation purposes only (spec Phase
68, FR-1.40's `temporal_analysis` context; RQ4: "change precision/recall,
detection latency... against a scripted ground-truth topology-event
timeline").

Mirrors `experiments/metrics/anomaly_evaluation.py` (Phase 42) closely: a
pure function scoring real `GraphChangeEvent` output (Phase 45's
`diff_snapshots`/Phase 47's `build_topology_event_timeline`) against
caller-supplied labeled ground truth -- it never generates topology
changes or labels itself. `LabeledTopologyEvent` is the temporal
analogue of `anomaly_evaluation.py`'s `LabeledAnomalyEvent`: the minimal
shape a caller who scripted a known, timestamped topology change (e.g.
Phase 68's matrix runner deliberately adding a node/edge in a second
traffic "wave") needs to supply.

Matching is greedy per `(change_type, affected_node_id, affected_edge_id)`:
each label claims at most one detected event (the earliest with
`occurred_at >= onset_at` -- a detection strictly before the change
genuinely happened cannot be credited to it), and vice versa, the same
"at most one claim" simplification `anomaly_evaluation.py` already
documents and relies on.

Returns a plain `TemporalAnalysisEvaluation` dataclass, not a
`MetricResult` directly -- Phase 68's matrix runner does that wrapping.
Does no I/O; never imports `simulator.ground_truth`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from backend.app.models.snapshot import ChangeType, GraphChangeEvent


@dataclass(frozen=True)
class LabeledTopologyEvent:
    """One real, known-true topology change a test harness has labeled
    (RQ4: a scripted change whose onset time and target are recorded as
    ground truth). Exactly one of `node_id`/`edge_id` should be set,
    matching whichever `GraphChangeEvent.affected_node_id`/
    `affected_edge_id` the corresponding real change would populate."""

    change_type: ChangeType
    onset_at: datetime
    node_id: Optional[str] = None
    edge_id: Optional[str] = None


@dataclass(frozen=True)
class TemporalAnalysisEvaluation:
    label_count: int
    detected_count: int
    true_positive_count: int
    false_positive_count: int
    false_negative_count: int

    precision: float
    recall: float
    f1: float

    mean_detection_latency_seconds: Optional[float]


def _matches(event: LabeledTopologyEvent, candidate: GraphChangeEvent) -> bool:
    if candidate.change_type != event.change_type:
        return False
    if event.node_id is not None and candidate.affected_node_id != event.node_id:
        return False
    if event.edge_id is not None and candidate.affected_edge_id != event.edge_id:
        return False
    return candidate.occurred_at >= event.onset_at


def _find_match(
    event: LabeledTopologyEvent, candidates: List[GraphChangeEvent], claimed: List[bool]
) -> Optional[int]:
    best_index: Optional[int] = None
    for index, candidate in enumerate(candidates):
        if claimed[index] or not _matches(event, candidate):
            continue
        if best_index is None or candidate.occurred_at < candidates[best_index].occurred_at:
            best_index = index
    return best_index


def evaluate_temporal_analysis(
    detected: List[GraphChangeEvent],
    labeled_events: List[LabeledTopologyEvent],
) -> TemporalAnalysisEvaluation:
    """Scores `detected` (real `GraphChangeEvent` output) against
    `labeled_events` (real, caller-known ground truth). Raises `ValueError`
    on empty `labeled_events` -- an evaluation cannot be computed against
    nothing, mirroring `evaluate_anomaly_detection`'s identical stance.
    """
    if not labeled_events:
        raise ValueError("evaluate_temporal_analysis requires at least one labeled event")

    claimed = [False] * len(detected)
    latencies: List[float] = []
    true_positive_count = 0
    false_negative_count = 0

    for event in labeled_events:
        match_index = _find_match(event, detected, claimed)
        if match_index is None:
            false_negative_count += 1
            continue
        claimed[match_index] = True
        true_positive_count += 1
        latencies.append((detected[match_index].occurred_at - event.onset_at).total_seconds())

    false_positive_count = sum(1 for was_claimed in claimed if not was_claimed)

    precision = (
        true_positive_count / (true_positive_count + false_positive_count)
        if (true_positive_count + false_positive_count) > 0
        else 0.0
    )
    recall = true_positive_count / (true_positive_count + false_negative_count)
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    return TemporalAnalysisEvaluation(
        label_count=len(labeled_events),
        detected_count=len(detected),
        true_positive_count=true_positive_count,
        false_positive_count=false_positive_count,
        false_negative_count=false_negative_count,
        precision=precision,
        recall=recall,
        f1=f1,
        mean_detection_latency_seconds=(sum(latencies) / len(latencies)) if latencies else None,
    )
