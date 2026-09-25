"""Phase 78: numpy LSTM anomaly model -- BPTT correctness, learning, detection, cold start."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

import numpy as np
import pytest

from backend.app.models.anomaly import AnomalyDimension
from backend.app.models.behavior import BehavioralFingerprint, ObservationWindow
from backend.flowmind.anomaly.sequence_model import (
    FEATURE_COUNT,
    _forward,
    _group_by_length,
    _init_params,
    _loss_and_grads,
    _samples,
    detect_sequence_anomalies,
    feature_residuals,
    fit_sequence_model,
)

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _fp(epoch: int, destinations: int = 3, total_bytes: int = 10_000, ratio: float = 0.5,
        duration: float = 0.5, node: str = "n0") -> BehavioralFingerprint:
    return BehavioralFingerprint(
        node_id=node, window=ObservationWindow.SHORT, computed_at=BASE + timedelta(seconds=60 * (epoch + 1)),
        distinct_ports=[80], distinct_protocols=["tcp"], distinct_destinations=destinations,
        mean_flow_duration_seconds=duration, outbound_byte_ratio=ratio, is_persistent_talker=False,
        total_byte_count=total_bytes,
    )


def _normal_history(seed: int, length: int = 8, node: str = "n0") -> List[BehavioralFingerprint]:
    rng = np.random.default_rng(seed)
    return [
        _fp(e, destinations=3, total_bytes=int(10_000 * rng.uniform(0.9, 1.1)),
            ratio=0.5 + float(rng.uniform(-0.03, 0.03)), duration=0.5 + float(rng.uniform(-0.02, 0.02)), node=node)
        for e in range(length)
    ]


def test_bptt_matches_numerical_gradients() -> None:
    histories = [_normal_history(s, length=6) for s in range(3)]
    groups = _group_by_length(_samples(histories, 2))
    rng = np.random.default_rng(0)
    params = {k: v + rng.normal(scale=0.2, size=v.shape) for k, v in _init_params(4, rng).items()}
    _, analytic = _loss_and_grads(params, groups, l2=0.01)

    for name, value in params.items():
        numeric = np.zeros_like(value)
        it = np.nditer(value, flags=["multi_index"])
        for _ in it:
            idx = it.multi_index
            original = value[idx]
            value[idx] = original + 1e-6
            plus, _ = _loss_and_grads(params, groups, l2=0.01)
            value[idx] = original - 1e-6
            minus, _ = _loss_and_grads(params, groups, l2=0.01)
            value[idx] = original
            numeric[idx] = (plus - minus) / 2e-6
        assert np.allclose(analytic[name], numeric, rtol=1e-4, atol=1e-7), name


def test_prediction_shape_and_length_grouping() -> None:
    samples = _samples([_normal_history(1, length=6)], min_history=2)
    assert sorted({len(w) for w, _ in samples}) == [2, 3, 4, 5]  # every prefix, each with its own statistics
    (x2, y2), *_ = _group_by_length(samples)
    prediction, _ = _forward(_init_params(5, np.random.default_rng(0)), x2)
    assert prediction.shape == y2.shape == (1, FEATURE_COUNT)


def test_deterministic_per_seed() -> None:
    histories = [_normal_history(s) for s in range(4)]
    a = fit_sequence_model(histories, hidden=6, epochs=20, seed=3)
    b = fit_sequence_model(histories, hidden=6, epochs=20, seed=3)
    c = fit_sequence_model(histories, hidden=6, epochs=20, seed=4)
    assert all(np.array_equal(a.params[k], b.params[k]) for k in a.params)
    assert not np.array_equal(a.params["W"], c.params["W"])


def test_training_reduces_loss() -> None:
    histories = [_normal_history(s) for s in range(6)]
    assert fit_sequence_model(histories, hidden=8, epochs=200, seed=0).final_loss < fit_sequence_model(
        histories, hidden=8, epochs=1, seed=0).final_loss


def test_flags_a_volume_spike_but_not_a_repeat_of_normal_behaviour() -> None:
    model = fit_sequence_model([_normal_history(s) for s in range(30)], hidden=8, epochs=250, seed=0)
    history = _normal_history(1000)
    clean = _fp(8, destinations=3, total_bytes=10_000)
    spike = _fp(8, destinations=3, total_bytes=60_000)  # 6x volume

    assert detect_sequence_anomalies(model, history, clean) == []
    found = detect_sequence_anomalies(model, history, spike)
    assert AnomalyDimension.TRAFFIC_VOLUME in {a.dimension for a in found}
    volume = next(a for a in found if a.dimension == AnomalyDimension.TRAFFIC_VOLUME)
    assert volume.detected_at == spike.computed_at and volume.node_id == "n0"
    assert volume.evidence and "expected" in volume.evidence[0] and "60000" in volume.evidence[0]
    assert 0 < volume.score <= 1


def test_new_destination_burst_is_flagged_on_the_destinations_dimension() -> None:
    model = fit_sequence_model([_normal_history(s) for s in range(30)], hidden=8, epochs=250, seed=0)
    found = detect_sequence_anomalies(model, _normal_history(1001), _fp(8, destinations=9))
    assert AnomalyDimension.DESTINATIONS in {a.dimension for a in found}


def test_cold_start_below_min_history_returns_nothing_and_residuals_raise() -> None:
    model = fit_sequence_model([_normal_history(s) for s in range(5)], hidden=4, epochs=5, min_history=2)
    short = _normal_history(7, length=1)
    assert detect_sequence_anomalies(model, short, _fp(1, total_bytes=999_999)) == []
    with pytest.raises(ValueError):
        feature_residuals(model, short, _fp(1))
    # 2 epochs of history is enough -- unlike Phase 38's 5-observation MAD baseline
    assert isinstance(detect_sequence_anomalies(model, _normal_history(7, length=2), _fp(2)), list)


def test_invalid_training_input_is_rejected() -> None:
    with pytest.raises(ValueError):
        fit_sequence_model([])
    with pytest.raises(ValueError):
        fit_sequence_model([_normal_history(1, length=2)], min_history=2)  # no prefix longer than min_history
    with pytest.raises(ValueError):
        fit_sequence_model([_normal_history(1)], min_history=0)
