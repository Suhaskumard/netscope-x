"""Head-to-head benchmark: LSTM sequence model vs the MAD/z-score detector (spec addendum Phase 78).

Both detectors are scored on Phase 76's labeled injected-anomaly datasets by the same
`evaluate_anomaly_detection`, on identical fingerprint histories (`experiments/anomaly_fingerprints.py`).

Comparison rules (fixed in advance):
  - Shared dimension universe: the four continuous dimensions both detectors can emit (DESTINATIONS,
    TIMING, BEHAVIOR, TRAFFIC_VOLUME). PORTS/PROTOCOLS are set-novelty checks the sequence model does not
    cover, so MAD detections on them are dropped from the comparison (and counted, so nothing is hidden);
    `total_checks` is nodes x 4 dimensions x test epochs for both.
  - MAD/z-score: `build_node_baseline` on the `history_epochs` baseline epochs immediately before the test
    epochs, then `detect_node_anomalies` on each test epoch (Phase 76's fixed-baseline protocol). With fewer
    than its 5-observation minimum the baseline is `is_sufficient=False` and it returns nothing -- the
    real cold-start behavior, not a special case here.
  - LSTM: online. Each test epoch is judged from the preceding `history_epochs` baseline epochs *plus every
    earlier test epoch*, as a deployed detector would see them -- so an earlier injected anomaly really does
    contaminate later predictions, and that shows up in the numbers.
  - Leave-one-topology-level-out: each fold trains the LSTM on NORMAL baseline epochs of the other five
    levels (training seeds), never on the held-out level, never on any test epoch or label; tested on the
    held-out level with disjoint seeds. The alarm threshold is the LSTM's own training-residual quantile,
    not tuned on test data.
  - Cold-start sweep over `history_epochs` (default 2, 3, 5, 8).

Nodes are discovered from the anomaly capture itself (not the matrix cell's main capture), so this is its
own protocol; its MAD numbers are comparable to Phase 76's matrix ones, not identical.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from backend.app.models.anomaly import Anomaly, AnomalyDimension
from backend.app.models.behavior import BehavioralFingerprint
from backend.flowmind.anomaly.node_anomaly import detect_node_anomalies
from backend.flowmind.anomaly.sequence_model import (
    FEATURES,
    SequenceAnomalyModel,
    detect_sequence_anomalies,
    fit_sequence_model,
)
from backend.flowmind.baseline.node_baseline import build_node_baseline
from backend.nettrace.topology.discovery import discover_nodes
from experiments.anomaly_fingerprints import anomaly_capture_id, fingerprints_from_flows, write_anomaly_capture
from experiments.anomaly_injection import AnomalyDataset, generate_anomaly_dataset
from experiments.matrix_runner import OBSERVATION_COMPLETENESS_LEVELS, SENSITIVITY_SWEEP, TOPOLOGY_LEVELS
from experiments.metrics.anomaly_evaluation import LabeledAnomalyEvent, evaluate_anomaly_detection
from experiments.metrics.summary_stats import MetricSummary, format_summary, summarize_values
from experiments.synthetic_traffic import assign_ips

SHARED_DIMENSIONS = frozenset(dim for _, dim, _ in FEATURES)
METHODS: Tuple[str, ...] = ("mad_zscore", "lstm")
TRAIN_SEEDS: List[int] = list(range(100, 105))
TEST_SEEDS: List[int] = list(range(42, 52))
TRAIN_COMPLETENESS: List[float] = [1.0, 0.5]
VARIANTS: Tuple[str, ...] = ("default", "lowvol")
HISTORY_LENGTHS: Tuple[int, ...] = (2, 3, 5, 8)


@dataclass(frozen=True)
class AnomalyBenchExample:
    level: str
    completeness: float
    variant: str
    seed: int
    dataset: AnomalyDataset
    fingerprints: Dict[str, List[BehavioralFingerprint]]
    labels: List[LabeledAnomalyEvent]


def build_bench_example(root: Path, level: str, completeness: float, seed: int, variant: str) -> AnomalyBenchExample:
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}; choose from {VARIANTS}")
    roles, edges = TOPOLOGY_LEVELS[level]()
    ip_by_name = assign_ips(list(roles))
    capture_id = f"seqbench-{level}-{str(completeness).replace('.', 'p')}-{variant}-{seed}"
    packets_per_edge = SENSITIVITY_SWEEP["packets_per_edge"] if variant == "lowvol" else 15
    dataset = generate_anomaly_dataset(roles, edges, ip_by_name, capture_id, seed, packets_per_edge=packets_per_edge)

    flows = write_anomaly_capture(root, capture_id, dataset, completeness, seed)
    nodes = discover_nodes(root, anomaly_capture_id(capture_id))
    fingerprints = fingerprints_from_flows(flows, dataset, nodes)

    node_id_by_name: Dict[str, str] = {}
    ip_to_name = {ip: name for name, ip in ip_by_name.items()}
    for node in nodes:
        name = ip_to_name.get(str(node.ip_addresses[0]))
        if name is not None:
            node_id_by_name[name] = node.node_id
    labels = [
        LabeledAnomalyEvent(node_id=node_id_by_name[name], dimension=dim, onset_at=injected.onset_at)
        for injected in dataset.injected
        for name, dim in injected.labels
        if name in node_id_by_name
    ]
    return AnomalyBenchExample(level, completeness, variant, seed, dataset, fingerprints, labels)


def _mad_detections(item: AnomalyBenchExample, history_epochs: int) -> Tuple[List[Anomaly], int]:
    first_test = item.dataset.baseline_epochs
    detected: List[Anomaly] = []
    dropped_novelty = 0
    for history in item.fingerprints.values():
        baseline = build_node_baseline(history[first_test - history_epochs : first_test])
        for fingerprint in history[first_test:]:
            for anomaly in detect_node_anomalies(baseline, fingerprint):
                if anomaly.dimension in SHARED_DIMENSIONS:
                    detected.append(anomaly)
                else:
                    dropped_novelty += 1
    return detected, dropped_novelty


def _lstm_detections(item: AnomalyBenchExample, model: SequenceAnomalyModel, history_epochs: int) -> List[Anomaly]:
    first_test = item.dataset.baseline_epochs
    detected: List[Anomaly] = []
    for history in item.fingerprints.values():
        for t in range(first_test, item.dataset.total_epochs):
            detected.extend(detect_sequence_anomalies(model, history[first_test - history_epochs : t], history[t]))
    return detected


@dataclass(frozen=True)
class SequenceScore:
    level: str
    completeness: float
    variant: str
    seed: int
    history_epochs: int
    method: str
    precision: float
    recall: float
    f1: float
    false_positive_rate: Optional[float]
    detection_latency_seconds: Optional[float]
    true_positives: int
    false_positives: int
    false_negatives: int
    clean_epoch_detections: int
    clean_epoch_checks: int


def score_detections(
    item: AnomalyBenchExample, detected: List[Anomaly], history_epochs: int, method: str
) -> Optional[SequenceScore]:
    """Scores `detected` with the real `evaluate_anomaly_detection` over the shared 4-dimension universe;
    `None` if the capture kept none of the injected labels' nodes (nothing to score against)."""
    if not item.labels:
        return None
    test_epochs = item.dataset.test_epochs
    total_checks = len(item.fingerprints) * len(SHARED_DIMENSIONS) * test_epochs
    evaluation = evaluate_anomaly_detection(detected, item.labels, total_checks=total_checks)

    injected_epochs = {i.epoch for i in item.dataset.injected}
    epoch_by_end = {item.dataset.epoch_end(e): e for e in range(item.dataset.baseline_epochs, item.dataset.total_epochs)}
    clean_detections = sum(1 for a in detected if epoch_by_end[a.detected_at] not in injected_epochs)
    clean_checks = len(item.fingerprints) * len(SHARED_DIMENSIONS) * (test_epochs - len(injected_epochs))
    return SequenceScore(
        level=item.level, completeness=item.completeness, variant=item.variant, seed=item.seed,
        history_epochs=history_epochs, method=method,
        precision=evaluation.precision, recall=evaluation.recall, f1=evaluation.f1,
        false_positive_rate=evaluation.false_positive_rate,
        detection_latency_seconds=evaluation.mean_detection_latency_seconds,
        true_positives=evaluation.true_positive_count, false_positives=evaluation.false_positive_count,
        false_negatives=evaluation.false_negative_count,
        clean_epoch_detections=clean_detections, clean_epoch_checks=clean_checks,
    )


@dataclass
class SequenceBenchmarkResult:
    scores: List[SequenceScore]
    fold_info: Dict[str, Dict[str, float]]  # held-out level -> training sizes, parameters, threshold, seconds
    history_lengths: Tuple[int, ...]
    train_seeds: List[int]
    test_seeds: List[int]
    dropped_mad_novelty_detections: int = 0
    notes: List[str] = field(default_factory=list)


def run_sequence_benchmark(
    root: Path,
    levels: Optional[Sequence[str]] = None,
    completeness_levels: Optional[Sequence[float]] = None,
    test_seeds: Optional[Sequence[int]] = None,
    train_seeds: Optional[Sequence[int]] = None,
    train_completeness: Optional[Sequence[float]] = None,
    variants: Sequence[str] = VARIANTS,
    history_lengths: Sequence[int] = HISTORY_LENGTHS,
    hidden: int = 16,
    epochs: int = 200,
    model_seed: int = 0,
) -> SequenceBenchmarkResult:
    """Leave-one-topology-level-out benchmark (see module docstring)."""
    levels = list(levels or TOPOLOGY_LEVELS)
    completenesses = list(completeness_levels or OBSERVATION_COMPLETENESS_LEVELS)
    test_seeds = list(test_seeds if test_seeds is not None else TEST_SEEDS)
    train_seeds = list(train_seeds if train_seeds is not None else TRAIN_SEEDS)
    train_completeness = list(train_completeness or TRAIN_COMPLETENESS)
    if set(train_seeds) & set(test_seeds):
        raise ValueError("train_seeds and test_seeds must be disjoint")
    if len(levels) < 2:
        raise ValueError("leave-one-level-out needs at least two topology levels")
    if any(h < 2 or h > 8 for h in history_lengths):
        raise ValueError("history_lengths must lie in [2, 8] (the dataset has 8 baseline epochs)")

    train_pool = {
        level: [build_bench_example(root, level, c, s, v) for v in variants for c in train_completeness for s in train_seeds]
        for level in levels
    }
    test_pool = {
        level: [build_bench_example(root, level, c, s, v) for v in variants for c in completenesses for s in test_seeds]
        for level in levels
    }

    scores: List[SequenceScore] = []
    fold_info: Dict[str, Dict[str, float]] = {}
    dropped = 0
    for held_out in levels:
        baseline_histories = [
            history[: it.dataset.baseline_epochs]
            for level in levels if level != held_out
            for it in train_pool[level]
            for history in it.fingerprints.values()
        ]
        started = time.perf_counter()
        model = fit_sequence_model(baseline_histories, hidden=hidden, epochs=epochs, seed=model_seed)
        fold_info[held_out] = {
            "training_histories": len(baseline_histories),
            "training_samples": model.training_sample_count,
            "parameters": model.parameter_count,
            "threshold": model.threshold,
            "final_loss": model.final_loss,
            "training_seconds": time.perf_counter() - started,
        }
        for item in test_pool[held_out]:
            for h in history_lengths:
                mad, novelty = _mad_detections(item, h)
                if h == max(history_lengths):
                    dropped += novelty
                for method, detected in (("mad_zscore", mad), ("lstm", _lstm_detections(item, model, h))):
                    score = score_detections(item, detected, h, method)
                    if score is not None:
                        scores.append(score)

    return SequenceBenchmarkResult(
        scores=scores, fold_info=fold_info, history_lengths=tuple(history_lengths),
        train_seeds=train_seeds, test_seeds=test_seeds, dropped_mad_novelty_detections=dropped,
    )


def _summary(scores: Sequence[SequenceScore], metric: str) -> MetricSummary:
    return summarize_values([getattr(s, metric) for s in scores])


def format_method_table(result: SequenceBenchmarkResult, variant: str, history_epochs: int) -> str:
    """One row per (topology, completeness): precision / recall / F1 / mean latency for both methods."""
    rows = [s for s in result.scores if s.variant == variant and s.history_epochs == history_epochs]
    metrics = ("precision", "recall", "f1")
    header = ["topology", "completeness"] + [f"{m} {method}" for m in metrics for method in METHODS]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    levels = list(dict.fromkeys(s.level for s in rows))
    for level in levels:
        for c in sorted({s.completeness for s in rows if s.level == level}, reverse=True):
            cell = [s for s in rows if s.level == level and s.completeness == c]
            values = [
                format_summary(_summary([s for s in cell if s.method == method], m)) for m in metrics for method in METHODS
            ]
            lines.append("| " + " | ".join([level, f"{c:g}"] + values) + " |")
    overall = [
        format_summary(_summary([s for s in rows if s.method == method], m)) for m in metrics for method in METHODS
    ]
    lines.append("| " + " | ".join(["**all**", "all"] + overall) + " |")
    return "\n".join(lines)


def format_cold_start_table(result: SequenceBenchmarkResult, variant: str) -> str:
    """Per history length and method (over every test example): recall, precision, F1, detections in clean
    epochs per check, mean detection latency."""
    header = ["history epochs", "method", "recall", "precision", "f1", "clean-epoch false-alarm rate", "latency s"]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for h in result.history_lengths:
        for method in METHODS:
            rows = [s for s in result.scores if s.variant == variant and s.history_epochs == h and s.method == method]
            checks = sum(s.clean_epoch_checks for s in rows)
            rate = (sum(s.clean_epoch_detections for s in rows) / checks) if checks else None
            lines.append("| " + " | ".join([
                str(h), method, format_summary(_summary(rows, "recall")), format_summary(_summary(rows, "precision")),
                format_summary(_summary(rows, "f1")), f"{rate:.3f}" if rate is not None else "n/a",
                format_summary(_summary(rows, "detection_latency_seconds")),
            ]) + " |")
    return "\n".join(lines)
