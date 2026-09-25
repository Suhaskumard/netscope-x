"""Cross-topology transfer benchmark for the role and anomaly models (spec addendum Phase 81).

Question: do models trained on some Phase 18 topology *archetypes* generalize to an archetype never seen in
training? Measured, not assumed, by leave-one-ARCHETYPE-out (`ARCHETYPES`: chain, star, multi_tier,
multi_path, redundant, dynamic). The matrix's own levels are not used as the split unit because `medium` and
`multi_service` are both stars -- holding one out would still leave the archetype in training.

For each held-out archetype H, per task (role: Phase 36 Naive Bayes; anomaly: Phase 78 LSTM, with Phase 38-40
MAD/z-score as the transfer-free comparator):
  - in_distribution: trained on H's own training seeds (the upper bound; same archetype, disjoint seeds).
  - zero_shot: trained on the other archetypes only.
  - few_shot k: zero-shot model adapted with k labeled nodes from H (role: their fingerprints are added to the
    pooled training set; anomaly: the LSTM is fine-tuned on their normal histories, threshold re-derived from
    them). The k nodes come from H's *support* seeds, disjoint from both training and test seeds, picked
    round-robin across roles (a deterministic rule that reads no test data).
  - scratch k: trained on the same k nodes alone -- shows whether the transferred model helps at all.
Degradation = in_distribution - zero_shot, reported per archetype. Roles that exist only in the held-out
archetype (e.g. the star's GATEWAY) cannot be predicted by a zero-shot model; their share is reported
(`unseen_role_share`) with accuracy over seen roles separately, so "unlearnable" is not mixed with "poor".

Data: each archetype at two sizes, on Phase 76's anomaly datasets (`build_bench_example`, completeness 1.0).
Role samples are (fingerprint, declared role) for every node at every baseline (normal) epoch; anomaly
scoring is Phase 78's shared protocol at the full 8-epoch history. Nothing is trained on a test seed, a test
epoch, or an injected label. Declared roles are evaluation labels passed as plain data.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from statistics import fmean
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from backend.app.models.behavior import BehavioralFingerprint, ServiceRole
from backend.flowmind.anomaly.sequence_model import SequenceAnomalyModel, fit_sequence_model
from backend.flowmind.classification.role_classifier import RoleModel, classify_node_role, fit_role_model
from experiments.metrics.role_calibration import evaluate_role_calibration
from experiments.sequence_anomaly_benchmark import (
    AnomalyBenchExample,
    _lstm_detections,
    _mad_detections,
    build_bench_example,
    score_detections,
)
from simulator.scenarios.topologies import (
    ScenarioEdge,
    dynamic_service_network,
    multi_path,
    multi_tier,
    redundant,
    simple_chain,
    star,
)

Topology = Tuple[Dict[str, ServiceRole], List[ScenarioEdge]]

ARCHETYPES: Dict[str, List[Callable[[], Topology]]] = {
    "chain": [lambda: simple_chain(3), lambda: simple_chain(5)],
    "star": [lambda: star(4), lambda: star(8)],
    "multi_tier": [lambda: multi_tier([2, 3, 2]), lambda: multi_tier([2, 4, 4, 2])],
    "multi_path": [lambda: multi_path(2), lambda: multi_path(3)],
    "redundant": [lambda: redundant(4), lambda: redundant(6)],
    "dynamic": [lambda: dynamic_service_network(seed=7, n=6), lambda: dynamic_service_network(seed=42, n=8)],
}
TRAIN_SEEDS: List[int] = [100, 101, 102]
SUPPORT_SEEDS: List[int] = [200, 201]
TEST_SEEDS: List[int] = [42, 43, 44, 45]
SHOTS: Tuple[int, ...] = (1, 2, 5)
HISTORY_EPOCHS = 8  # the dataset's full baseline; cold start is Phase 78's question, not this one
ROLE_MODES = ("in_distribution", "zero_shot", "few_shot", "scratch")


@dataclass(frozen=True)
class RoleTransferRow:
    archetype: str
    mode: str
    shots: int
    sample_count: int
    accuracy: float
    ece: float
    unseen_role_share: float
    seen_role_accuracy: Optional[float]


@dataclass(frozen=True)
class AnomalyTransferRow:
    archetype: str
    mode: str  # mad_zscore | lstm_in_distribution | lstm_zero_shot | lstm_few_shot | lstm_scratch
    shots: int
    precision: float
    recall: float
    f1: float
    example_count: int


@dataclass
class TransferBenchmarkResult:
    role_rows: List[RoleTransferRow]
    anomaly_rows: List[AnomalyTransferRow]
    archetypes: List[str]
    train_seeds: List[int]
    support_seeds: List[int]
    test_seeds: List[int]
    shots: Tuple[int, ...]
    fold_seconds: Dict[str, float] = field(default_factory=dict)


LabeledFingerprints = List[Tuple[BehavioralFingerprint, ServiceRole]]


def _build_pool(root: Path, archetype: str, seeds: Sequence[int]) -> List[AnomalyBenchExample]:
    return [
        build_bench_example(root, archetype, 1.0, seed, "default", topology=make())
        for make in ARCHETYPES[archetype]
        for seed in seeds
    ]


def role_samples(pool: Sequence[AnomalyBenchExample]) -> LabeledFingerprints:
    """(fingerprint, declared role) for every node at every baseline epoch -- normal behavior only."""
    return [
        (fp, item.role_by_node[node_id])
        for item in pool
        for node_id, history in item.fingerprints.items()
        if node_id in item.role_by_node
        for fp in history[: item.dataset.baseline_epochs]
    ]


def baseline_histories(pool: Sequence[AnomalyBenchExample]) -> List[List[BehavioralFingerprint]]:
    return [list(history[: item.dataset.baseline_epochs]) for item in pool for history in item.fingerprints.values()]


def select_shot_nodes(pool: Sequence[AnomalyBenchExample], k: int) -> List[Tuple[AnomalyBenchExample, str]]:
    """`k` (example, node_id) pairs from a support pool: round-robin over roles (sorted), then node id, so
    the choice depends only on declared structure -- never on test data or model output."""
    if k < 0:
        raise ValueError("k must be non-negative")
    by_role: Dict[ServiceRole, List[Tuple[AnomalyBenchExample, str]]] = {}
    for item in pool:
        for node_id in sorted(item.fingerprints):
            if node_id in item.role_by_node:
                by_role.setdefault(item.role_by_node[node_id], []).append((item, node_id))
    queues = [by_role[r] for r in sorted(by_role, key=lambda r: r.value)]
    chosen: List[Tuple[AnomalyBenchExample, str]] = []
    depth = 0
    while len(chosen) < k and any(depth < len(q) for q in queues):
        for q in queues:
            if depth < len(q) and len(chosen) < k:
                chosen.append(q[depth])
        depth += 1
    return chosen


def _shot_role_samples(shots: Sequence[Tuple[AnomalyBenchExample, str]]) -> LabeledFingerprints:
    return [
        (fp, item.role_by_node[node_id])
        for item, node_id in shots
        for fp in item.fingerprints[node_id][: item.dataset.baseline_epochs]
    ]


def _shot_histories(shots: Sequence[Tuple[AnomalyBenchExample, str]]) -> List[List[BehavioralFingerprint]]:
    return [list(item.fingerprints[node_id][: item.dataset.baseline_epochs]) for item, node_id in shots]


def score_role_model(archetype: str, mode: str, shots: int, model: RoleModel, test: LabeledFingerprints) -> RoleTransferRow:
    classifications = [classify_node_role(model, fp) for fp, _ in test]
    true_roles = [role for _, role in test]
    evaluation = evaluate_role_calibration(classifications, true_roles)
    seen = [(c, r) for c, r in zip(classifications, true_roles) if r in model.roles]
    seen_accuracy = (
        sum(1 for c, r in seen if max(c.role_probabilities, key=c.role_probabilities.get) == r) / len(seen)
        if seen
        else None
    )
    return RoleTransferRow(
        archetype=archetype, mode=mode, shots=shots, sample_count=evaluation.sample_count,
        accuracy=evaluation.accuracy, ece=evaluation.expected_calibration_error,
        unseen_role_share=1.0 - len(seen) / len(test), seen_role_accuracy=seen_accuracy,
    )


def _mean(values: Sequence[float]) -> float:
    return fmean(values) if values else 0.0


def score_anomaly_detector(
    archetype: str, mode: str, shots: int, test: Sequence[AnomalyBenchExample],
    detect: Callable[[AnomalyBenchExample], list],
) -> AnomalyTransferRow:
    scores = [
        s for item in test
        if (s := score_detections(item, detect(item), HISTORY_EPOCHS, mode)) is not None
    ]
    return AnomalyTransferRow(
        archetype=archetype, mode=mode, shots=shots,
        precision=_mean([s.precision for s in scores]), recall=_mean([s.recall for s in scores]),
        f1=_mean([s.f1 for s in scores]), example_count=len(scores),
    )


def run_transfer_benchmark(
    root: Path,
    archetypes: Optional[Sequence[str]] = None,
    train_seeds: Optional[Sequence[int]] = None,
    support_seeds: Optional[Sequence[int]] = None,
    test_seeds: Optional[Sequence[int]] = None,
    shots: Sequence[int] = SHOTS,
    hidden: int = 16,
    epochs: int = 200,
    fine_tune_epochs: int = 50,
    fine_tune_lr: float = 0.003,
    model_seed: int = 0,
    tasks: Sequence[str] = ("role", "anomaly"),
) -> TransferBenchmarkResult:
    names = list(archetypes or ARCHETYPES)
    train_seeds = list(train_seeds if train_seeds is not None else TRAIN_SEEDS)
    support_seeds = list(support_seeds if support_seeds is not None else SUPPORT_SEEDS)
    test_seeds = list(test_seeds if test_seeds is not None else TEST_SEEDS)
    if len(names) < 2:
        raise ValueError("leave-one-archetype-out needs at least two archetypes")
    unknown = [n for n in names if n not in ARCHETYPES]
    if unknown:
        raise KeyError(f"unknown archetypes {unknown}; choose from {sorted(ARCHETYPES)}")
    if len({*train_seeds, *support_seeds, *test_seeds}) != len(train_seeds) + len(support_seeds) + len(test_seeds):
        raise ValueError("train, support and test seeds must be pairwise disjoint")

    train_pool = {a: _build_pool(root, a, train_seeds) for a in names}
    support_pool = {a: _build_pool(root, a, support_seeds) for a in names}
    test_pool = {a: _build_pool(root, a, test_seeds) for a in names}

    role_rows: List[RoleTransferRow] = []
    anomaly_rows: List[AnomalyTransferRow] = []
    fold_seconds: Dict[str, float] = {}
    for held_out in names:
        started = time.perf_counter()
        others = [a for a in names if a != held_out]
        test = test_pool[held_out]
        shot_sets = {k: select_shot_nodes(support_pool[held_out], k) for k in shots}

        if "role" in tasks:
            test_role = role_samples(test)
            other_role = [s for a in others for s in role_samples(train_pool[a])]
            zero_shot = fit_role_model(other_role)
            role_rows.append(score_role_model(
                held_out, "in_distribution", 0, fit_role_model(role_samples(train_pool[held_out])), test_role))
            role_rows.append(score_role_model(held_out, "zero_shot", 0, zero_shot, test_role))
            for k, chosen in shot_sets.items():
                shot_samples = _shot_role_samples(chosen)
                if not shot_samples:
                    continue
                role_rows.append(score_role_model(
                    held_out, "few_shot", k, fit_role_model(other_role + shot_samples), test_role))
                role_rows.append(score_role_model(held_out, "scratch", k, fit_role_model(shot_samples), test_role))

        if "anomaly" in tasks:
            anomaly_rows.append(score_anomaly_detector(
                held_out, "mad_zscore", 0, test, lambda item: _mad_detections(item, HISTORY_EPOCHS)[0]))

            def lstm(model: SequenceAnomalyModel) -> Callable[[AnomalyBenchExample], list]:
                return lambda item: _lstm_detections(item, model, HISTORY_EPOCHS)

            in_dist = fit_sequence_model(
                baseline_histories(train_pool[held_out]), hidden=hidden, epochs=epochs, seed=model_seed)
            zero = fit_sequence_model(
                [h for a in others for h in baseline_histories(train_pool[a])],
                hidden=hidden, epochs=epochs, seed=model_seed)
            anomaly_rows.append(score_anomaly_detector(held_out, "lstm_in_distribution", 0, test, lstm(in_dist)))
            anomaly_rows.append(score_anomaly_detector(held_out, "lstm_zero_shot", 0, test, lstm(zero)))
            for k, chosen in shot_sets.items():
                histories = _shot_histories(chosen)
                if not histories:
                    continue
                tuned = fit_sequence_model(
                    histories, epochs=fine_tune_epochs, learning_rate=fine_tune_lr, seed=model_seed, init=zero)
                scratch = fit_sequence_model(histories, hidden=hidden, epochs=epochs, seed=model_seed)
                anomaly_rows.append(score_anomaly_detector(held_out, "lstm_few_shot", k, test, lstm(tuned)))
                anomaly_rows.append(score_anomaly_detector(held_out, "lstm_scratch", k, test, lstm(scratch)))
        fold_seconds[held_out] = time.perf_counter() - started

    return TransferBenchmarkResult(
        role_rows=role_rows, anomaly_rows=anomaly_rows, archetypes=names, train_seeds=train_seeds,
        support_seeds=support_seeds, test_seeds=test_seeds, shots=tuple(shots), fold_seconds=fold_seconds,
    )


def degradation(result: TransferBenchmarkResult) -> Dict[str, Dict[str, Optional[float]]]:
    """Per archetype: in-distribution minus zero-shot, role accuracy and LSTM F1 (positive = transfer loses)."""
    out: Dict[str, Dict[str, Optional[float]]] = {}
    for a in result.archetypes:
        role = {r.mode: r for r in result.role_rows if r.archetype == a and r.shots == 0}
        anomaly = {r.mode: r for r in result.anomaly_rows if r.archetype == a and r.shots == 0}
        out[a] = {
            "role_accuracy": role["in_distribution"].accuracy - role["zero_shot"].accuracy if role else None,
            "lstm_f1": (
                anomaly["lstm_in_distribution"].f1 - anomaly["lstm_zero_shot"].f1 if "lstm_zero_shot" in anomaly else None
            ),
        }
    return out


def _fmt(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def format_role_table(result: TransferBenchmarkResult) -> str:
    header = ["archetype", "mode", "k", "accuracy", "seen-role accuracy", "unseen-role share", "ECE"]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for r in result.role_rows:
        lines.append("| " + " | ".join([
            r.archetype, r.mode, str(r.shots), _fmt(r.accuracy), _fmt(r.seen_role_accuracy),
            _fmt(r.unseen_role_share), _fmt(r.ece)]) + " |")
    return "\n".join(lines)


def format_anomaly_table(result: TransferBenchmarkResult) -> str:
    header = ["archetype", "mode", "k", "precision", "recall", "F1"]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for r in result.anomaly_rows:
        lines.append("| " + " | ".join([
            r.archetype, r.mode, str(r.shots), _fmt(r.precision), _fmt(r.recall), _fmt(r.f1)]) + " |")
    return "\n".join(lines)


def format_degradation_table(result: TransferBenchmarkResult) -> str:
    header = ["archetype", "role accuracy: in-dist - zero-shot", "LSTM F1: in-dist - zero-shot"]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for a, d in degradation(result).items():
        lines.append(f"| {a} | {_fmt(d['role_accuracy'])} | {_fmt(d['lstm_f1'])} |")
    return "\n".join(lines)
