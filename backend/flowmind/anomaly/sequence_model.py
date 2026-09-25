"""LSTM sequence model for per-node anomaly detection (spec addendum Phase 78).

An alternative to Phase 38-40's median/MAD baseline + z-score detector (`node_baseline.py`,
`node_anomaly.py`): instead of comparing a node's newest fingerprint to a fixed robust summary of its
history, a small LSTM reads the node's fingerprint *sequence* and predicts the next epoch's behavior; a
large prediction residual is the anomaly signal. Plain numpy with hand-written BPTT (torch is not a
project dependency), verified against numerical gradients in `backend/tests/test_sequence_anomaly_model.py`.

Scope, stated honestly:
  - It covers the four continuous features the MAD detector uses (`distinct_destinations`,
    `mean_flow_duration_seconds`, `outbound_byte_ratio`, `total_byte_count` -> DESTINATIONS, TIMING,
    BEHAVIOR, TRAFFIC_VOLUME). PORTS/PROTOCOLS are set-novelty checks with nothing to predict; the
    sequence model does not produce them.
  - Each node's sequence is normalized by that node's *own* history (median, MAD-based scale with
    provisional floors), so the network learns temporal dynamics of normalized deviation, not absolute
    volumes, and one model can serve nodes of very different size.
  - It is trained on NORMAL history only (`fit_sequence_model` is given histories the caller vouches are
    normal) and never sees an anomaly or a label. Its residual scale and alarm threshold are read off the
    training residuals, not tuned on test data.
  - Needs at least `min_history` (default 2) prior epochs to score at all -- a different cold-start
    requirement from the MAD baseline's 5 (Phase 38); whether that is an advantage is measured in
    `experiments/sequence_anomaly_benchmark.py`, not asserted.
  - Interpretability is weaker than Phase 41's evidence reports: the evidence states observed vs
    model-expected value and the residual, but "expected" is a learned function of the sequence, not a
    named historical statistic.

Never imports `simulator.ground_truth` (spec §4; `scripts/check_ground_truth_boundary.py`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

import numpy as np

from backend.app.models.anomaly import Anomaly, AnomalyClass, AnomalyDimension
from backend.app.models.behavior import BehavioralFingerprint

FEATURES: Tuple[Tuple[str, AnomalyDimension, str], ...] = (
    ("distinct_destinations", AnomalyDimension.DESTINATIONS, "destinations"),
    ("mean_flow_duration_seconds", AnomalyDimension.TIMING, "duration_seconds"),
    ("outbound_byte_ratio", AnomalyDimension.BEHAVIOR, "outbound_byte_ratio"),
    ("log_total_byte_count", AnomalyDimension.TRAFFIC_VOLUME, "byte_count"),
)
FEATURE_COUNT = len(FEATURES)
# Provisional scale floors, per feature, so a perfectly flat history does not make every change infinite
# (the same reason `node_anomaly.py` has `mad_floor`): the larger of 5% of the median and this absolute value.
_ABSOLUTE_SCALE_FLOOR = np.array([0.5, 1e-3, 0.02, 0.05])
_RELATIVE_SCALE_FLOOR = 0.05
_MAD_TO_SIGMA = 1.4826
# Normalized values are clipped to +/- this many scales. A short history (2-3 epochs) has a poorly
# estimated scale, so an ordinary next value can normalize to thousands; unclipped, those few samples
# dominate the squared error and the network learns nothing else. A genuine anomaly still lands at the
# clip boundary, far above the threshold.
_NORMALIZED_CLIP = 10.0


def fingerprint_features(fingerprint: BehavioralFingerprint) -> np.ndarray:
    return np.array(
        [
            float(fingerprint.distinct_destinations),
            float(fingerprint.mean_flow_duration_seconds),
            float(fingerprint.outbound_byte_ratio),
            math.log1p(float(fingerprint.total_byte_count)),
        ]
    )


def _normalizer(history: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """(median, scale) of a [T, d] history, per feature."""
    median = np.median(history, axis=0)
    mad = np.median(np.abs(history - median), axis=0)
    scale = np.maximum.reduce([_MAD_TO_SIGMA * mad, _RELATIVE_SCALE_FLOOR * np.abs(median), _ABSOLUTE_SCALE_FLOOR])
    return median, scale


def _normalize(values: np.ndarray, median: np.ndarray, scale: np.ndarray) -> np.ndarray:
    return np.clip((values - median) / scale, -_NORMALIZED_CLIP, _NORMALIZED_CLIP)


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -60.0, 60.0)))


def _init_params(hidden: int, rng: np.random.Generator) -> Dict[str, np.ndarray]:
    fan_in = FEATURE_COUNT + hidden
    limit = math.sqrt(6.0 / (fan_in + 4 * hidden))
    bias = np.zeros(4 * hidden)
    bias[hidden : 2 * hidden] = 1.0  # forget-gate bias: remember by default
    return {
        "W": rng.uniform(-limit, limit, size=(fan_in, 4 * hidden)),
        "b": bias,
        "Wy": rng.uniform(-0.1, 0.1, size=(hidden, FEATURE_COUNT)),
        "by": np.zeros(FEATURE_COUNT),
    }


def _forward(params: Dict[str, np.ndarray], x: np.ndarray):
    """x: [B, L, d] -> prediction [B, d] of the step after the window, plus the cache BPTT needs."""
    batch, length, _ = x.shape
    hidden = params["Wy"].shape[0]
    h = np.zeros((batch, hidden))
    c = np.zeros((batch, hidden))
    cache = []
    for t in range(length):
        z = np.concatenate([x[:, t, :], h], axis=1)
        gates = z @ params["W"] + params["b"]
        i = _sigmoid(gates[:, :hidden])
        f = _sigmoid(gates[:, hidden : 2 * hidden])
        g = np.tanh(gates[:, 2 * hidden : 3 * hidden])
        o = _sigmoid(gates[:, 3 * hidden :])
        c_prev = c
        c = f * c_prev + i * g
        tanh_c = np.tanh(c)
        h = o * tanh_c
        cache.append((z, i, f, g, o, c_prev, tanh_c))
    return h @ params["Wy"] + params["by"], (h, cache)


def _loss_and_grads(
    params: Dict[str, np.ndarray], groups: Sequence[Tuple[np.ndarray, np.ndarray]], l2: float
) -> Tuple[float, Dict[str, np.ndarray]]:
    """Mean squared next-step error over every sample of every length group, plus L2 on the weights."""
    grads = {k: np.zeros_like(v) for k, v in params.items()}
    hidden = params["Wy"].shape[0]
    total = float(sum(y.size for _, y in groups))
    loss = 0.0
    for x, y in groups:
        prediction, (h_last, cache) = _forward(params, x)
        error = prediction - y
        loss += float((error**2).sum())

        dy = 2.0 * error / total
        grads["Wy"] += h_last.T @ dy
        grads["by"] += dy.sum(axis=0)
        dh = dy @ params["Wy"].T
        dc = np.zeros_like(dh)
        for z, i, f, g, o, c_prev, tanh_c in reversed(cache):
            d_o = dh * tanh_c
            dc = dc + dh * o * (1.0 - tanh_c**2)
            d_i, d_f, d_g = dc * g, dc * c_prev, dc * i
            dgates = np.concatenate(
                [d_i * i * (1 - i), d_f * f * (1 - f), d_g * (1 - g**2), d_o * o * (1 - o)], axis=1
            )
            grads["W"] += z.T @ dgates
            grads["b"] += dgates.sum(axis=0)
            dh = (dgates @ params["W"].T)[:, FEATURE_COUNT:]
            dc = dc * f
    loss /= total
    for name in ("W", "Wy"):
        loss += 0.5 * l2 * float((params[name] ** 2).sum())
        grads[name] += l2 * params[name]
    return loss, grads


def _samples(histories: Sequence[Sequence[BehavioralFingerprint]], min_history: int):
    """(normalized input window [L, d], normalized target [d]) for every prefix of every history, each
    normalized with only that prefix's own statistics -- exactly what inference has available."""
    samples = []
    for history in histories:
        raw = np.array([fingerprint_features(fp) for fp in history])
        for t in range(min_history, len(raw)):
            median, scale = _normalizer(raw[:t])
            samples.append((_normalize(raw[:t], median, scale), _normalize(raw[t], median, scale)))
    return samples


def _group_by_length(samples) -> List[Tuple[np.ndarray, np.ndarray]]:
    by_length: Dict[int, List] = {}
    for window, target in samples:
        by_length.setdefault(len(window), []).append((window, target))
    return [
        (np.stack([w for w, _ in items]), np.stack([t for _, t in items])) for _, items in sorted(by_length.items())
    ]


@dataclass
class SequenceAnomalyModel:
    params: Dict[str, np.ndarray]
    residual_scale: np.ndarray  # per-feature std of training residuals (normalized units)
    threshold: float  # alarm level on |residual| / residual_scale
    hidden: int
    min_history: int
    training_sample_count: int
    final_loss: float

    @property
    def parameter_count(self) -> int:
        return int(sum(p.size for p in self.params.values()))


def fit_sequence_model(
    histories: Sequence[Sequence[BehavioralFingerprint]],
    hidden: int = 16,
    epochs: int = 300,
    learning_rate: float = 0.01,
    l2: float = 1e-4,
    threshold_quantile: float = 0.99,
    min_history: int = 2,
    seed: int = 0,
) -> SequenceAnomalyModel:
    """Trains on `histories` -- one time-ordered fingerprint list per node, which the caller vouches are
    NORMAL. Full-batch Adam, deterministic per `seed`. The alarm threshold is the `threshold_quantile` of
    the pooled training residuals in per-feature scale units, fixed here, not tuned on test data. Raises
    `ValueError` if no history is long enough to form a training sample."""
    if min_history < 1:
        raise ValueError("min_history must be at least 1")
    samples = _samples(histories, min_history)
    if not samples:
        raise ValueError(f"fit_sequence_model needs at least one history longer than min_history={min_history}")
    groups = _group_by_length(samples)

    rng = np.random.default_rng(seed)
    params = _init_params(hidden, rng)
    m = {k: np.zeros_like(v) for k, v in params.items()}
    s = {k: np.zeros_like(v) for k, v in params.items()}
    beta1, beta2, eps = 0.9, 0.999, 1e-8
    loss = float("nan")
    for step in range(1, epochs + 1):
        loss, grads = _loss_and_grads(params, groups, l2)
        for name in params:
            m[name] = beta1 * m[name] + (1 - beta1) * grads[name]
            s[name] = beta2 * s[name] + (1 - beta2) * grads[name] ** 2
            params[name] = params[name] - learning_rate * (m[name] / (1 - beta1**step)) / (
                np.sqrt(s[name] / (1 - beta2**step)) + eps
            )

    residuals = np.concatenate([_forward(params, x)[0] - y for x, y in groups])
    residual_scale = np.maximum(residuals.std(axis=0), 1e-6)
    threshold = float(np.quantile(np.abs(residuals / residual_scale), threshold_quantile))
    return SequenceAnomalyModel(
        params=params,
        residual_scale=residual_scale,
        threshold=threshold,
        hidden=hidden,
        min_history=min_history,
        training_sample_count=len(samples),
        final_loss=float(loss),
    )


def feature_residuals(
    model: SequenceAnomalyModel, history: Sequence[BehavioralFingerprint], fingerprint: BehavioralFingerprint
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(scaled residuals, observed raw features, model-expected raw features) for `fingerprint`, judged
    against the node's preceding `history`. Raises `ValueError` if `history` is shorter than
    `model.min_history`."""
    if len(history) < model.min_history:
        raise ValueError(f"need at least {model.min_history} prior epochs, got {len(history)}")
    raw = np.array([fingerprint_features(fp) for fp in history])
    median, scale = _normalizer(raw)
    window = _normalize(raw, median, scale)[None, :, :]
    predicted_normalized = _forward(model.params, window)[0][0]
    observed = fingerprint_features(fingerprint)
    residual = _normalize(observed, median, scale) - predicted_normalized
    return residual / model.residual_scale, observed, median + predicted_normalized * scale


def _display(name: str, value: float) -> str:
    if name == "log_total_byte_count":
        value = math.expm1(value)
    return f"{int(round(value))}" if abs(value - round(value)) < 1e-9 or abs(value) >= 100 else f"{value:.3f}"


def detect_sequence_anomalies(
    model: SequenceAnomalyModel, history: Sequence[BehavioralFingerprint], fingerprint: BehavioralFingerprint
) -> List[Anomaly]:
    """One `Anomaly` per feature whose scaled residual exceeds the model's threshold. Returns `[]` if
    `history` is shorter than `model.min_history` (cold start). `detected_at` is the fingerprint's
    `computed_at`; `anomaly_class` is the same provisional `TRANSIENT_ANOMALY` `detect_node_anomalies`
    assigns to a single observation."""
    if len(history) < model.min_history:
        return []
    scaled, observed, expected = feature_residuals(model, history, fingerprint)

    anomalies: List[Anomaly] = []
    for k, (name, dimension, label) in enumerate(FEATURES):
        magnitude = abs(float(scaled[k]))
        if magnitude < model.threshold:
            continue
        observed_str, expected_str = _display(name, observed[k]), _display(name, expected[k])
        anomalies.append(
            Anomaly(
                node_id=fingerprint.node_id,
                anomaly_id=f"{fingerprint.node_id}:{dimension.value}:seq:{fingerprint.computed_at.isoformat()}",
                detected_at=fingerprint.computed_at,
                dimension=dimension,
                anomaly_class=AnomalyClass.TRANSIENT_ANOMALY,
                evidence=[
                    f"{label} observed {observed_str} but the sequence model expected {expected_str} from the "
                    f"preceding {len(history)} epochs (residual {magnitude:.2f} scale units, "
                    f"threshold {model.threshold:.2f})"
                ],
                evidence_values={
                    f"observed_{label}": observed_str,
                    f"expected_{label}": expected_str,
                    "scaled_residual": f"{float(scaled[k]):.3f}",
                },
                score=float(1.0 - math.exp(-magnitude / model.threshold)),
            )
        )
    return anomalies
