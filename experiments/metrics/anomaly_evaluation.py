"""Anomaly-detection evaluation, for evaluation purposes only (spec Phase 42,
FR-1.19: "measure and report FLOWMIND's own precision, recall, F1,
false-positive rate, false-negative rate, and detection latency against
labeled experiments"; RQ3).

This module is the evaluation-only counterpart to `backend/flowmind/anomaly/
node_anomaly.py`'s real `detect_node_anomalies`/`detect_node_anomalies_with_
drift`: it SCORES a set of real `Anomaly` outputs against caller-supplied
labeled ground truth -- it never detects, injects, or generates anomalies
itself. RQ3 ties this to `dataset_anomaly`/`dataset_noisy` (Phase
19-replay-based datasets "with injected known anomalies whose onset time
and type are recorded as ground truth"), but no such dataset generator
exists anywhere in this repo yet -- building one is a separate, much larger
capability nobody has asked for, not implied by FR-1.19's literal text.
`LabeledAnomalyEvent` is deliberately the minimal shape a caller who already
knows the ground truth (however it was obtained) needs to supply.

Mirrors Phase 32/37's `experiments/metrics/{topology_comparison,
role_calibration}.py` precedent exactly: returns a plain
`AnomalyDetectionEvaluation` dataclass, not a `MetricResult`
(`backend/app/models/metric.py`) -- `MetricResult.experiment_id` is
required, and no experiment registry exists anywhere in this repository yet
(`Experiment`, `backend/app/models/experiment.py`, is never constructed for
real anywhere), so wrapping this in a `MetricResult` would mean fabricating
an experiment identity with nothing real behind it, exactly what spec §21
("No Fake Metrics") forbids. `GET /metrics`
(`backend/app/api/routes/metrics.py`) is explicitly scoped to Phase 68 in
its own docstring already, not this phase.

Never imported by anything under `backend/nettrace/`/`backend/app/` --
evaluation-only, matching the boundary already established for topology
comparison/role calibration. Takes real labels as a plain parameter; never
imports `simulator.ground_truth` itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from backend.app.models.anomaly import Anomaly, AnomalyDimension


@dataclass(frozen=True)
class LabeledAnomalyEvent:
    """One real, known-true anomaly occurrence a test harness has labeled
    (RQ3: "injected known anomalies whose onset time and type are recorded
    as ground truth"). `onset_at` is when the anomaly genuinely started --
    a detection before this cannot legitimately be credited to it."""

    node_id: str
    dimension: AnomalyDimension
    onset_at: datetime


@dataclass(frozen=True)
class AnomalyDetectionEvaluation:
    label_count: int
    detected_count: int
    true_positive_count: int
    false_positive_count: int
    false_negative_count: int

    precision: float
    recall: float
    f1: float
    false_negative_rate: float
    # None unless `total_checks` was supplied -- a real false-positive rate
    # needs a countable negative-instance universe, which `detected`/
    # `labeled_events` alone don't provide (see module docstring).
    false_positive_rate: Optional[float]
    # None if there are zero true positives -- never fabricated as 0.0.
    mean_detection_latency_seconds: Optional[float]


def _find_match(
    event: LabeledAnomalyEvent, candidates: List[Anomaly], claimed: List[bool]
) -> Optional[int]:
    """Returns the index into `candidates` of the earliest not-yet-claimed
    anomaly matching `event` (same node_id/dimension, detected_at >=
    onset_at), or None. A detection strictly before onset_at cannot be
    credited to an event that hadn't started yet."""
    best_index: Optional[int] = None
    for index, anomaly in enumerate(candidates):
        if claimed[index]:
            continue
        if anomaly.node_id != event.node_id or anomaly.dimension != event.dimension:
            continue
        if anomaly.detected_at < event.onset_at:
            continue
        if best_index is None or anomaly.detected_at < candidates[best_index].detected_at:
            best_index = index
    return best_index


def evaluate_anomaly_detection(
    detected: List[Anomaly],
    labeled_events: List[LabeledAnomalyEvent],
    total_checks: Optional[int] = None,
) -> AnomalyDetectionEvaluation:
    """Scores `detected` (real `Anomaly` output, e.g. from
    `detect_node_anomalies`) against `labeled_events` (real, caller-known
    ground truth). Matching is greedy per (node_id, dimension): each label
    claims at most one detection (the earliest with `detected_at >=
    onset_at`), and vice versa -- a real, buildable, documented
    simplification that scores at most one labeled anomaly episode per
    (node_id, dimension) per call.

    `false_positive_rate` requires a countable negative-instance universe
    (how many total node x dimension checks were run, most of which
    should NOT have fired) that `detected`/`labeled_events` alone cannot
    supply -- pass `total_checks` (the real number of detection attempts
    performed during the evaluated period) to compute it for real;
    otherwise it stays honestly `None`, never fabricated.

    Raises `ValueError` on empty `labeled_events` (an evaluation cannot be
    computed against nothing, mirroring `evaluate_role_calibration`'s
    identical stance), or if a supplied `total_checks` is smaller than
    `true_positive_count + false_positive_count + false_negative_count`
    (internally inconsistent -- those are real events that occurred within
    however many checks were run).
    """
    if not labeled_events:
        raise ValueError("evaluate_anomaly_detection requires at least one labeled event")

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
        latency = (detected[match_index].detected_at - event.onset_at).total_seconds()
        latencies.append(latency)

    false_positive_count = sum(1 for was_claimed in claimed if not was_claimed)

    precision = (
        true_positive_count / (true_positive_count + false_positive_count)
        if (true_positive_count + false_positive_count) > 0
        else 0.0
    )
    recall = true_positive_count / (true_positive_count + false_negative_count)
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    false_negative_rate = false_negative_count / (false_negative_count + true_positive_count)

    false_positive_rate: Optional[float] = None
    if total_checks is not None:
        accounted_for = true_positive_count + false_positive_count + false_negative_count
        if total_checks < accounted_for:
            raise ValueError(
                f"total_checks ({total_checks}) is smaller than the number of events that "
                f"actually occurred ({accounted_for} = true_positives + false_positives + "
                "false_negatives) -- inconsistent input"
            )
        true_negative_count = total_checks - accounted_for
        denominator = false_positive_count + true_negative_count
        false_positive_rate = (false_positive_count / denominator) if denominator > 0 else 0.0

    mean_detection_latency_seconds = (
        sum(latencies) / len(latencies) if latencies else None
    )

    return AnomalyDetectionEvaluation(
        label_count=len(labeled_events),
        detected_count=len(detected),
        true_positive_count=true_positive_count,
        false_positive_count=false_positive_count,
        false_negative_count=false_negative_count,
        precision=precision,
        recall=recall,
        f1=f1,
        false_negative_rate=false_negative_rate,
        false_positive_rate=false_positive_rate,
        mean_detection_latency_seconds=mean_detection_latency_seconds,
    )
