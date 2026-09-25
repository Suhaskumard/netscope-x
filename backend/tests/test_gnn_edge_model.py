"""Phase 77: numpy GNN edge model -- gradient correctness, determinism, symmetry, learning."""

from __future__ import annotations

import numpy as np
import pytest

from backend.nettrace.topology.gnn_edge_model import (
    NODE_FEATURE_NAMES,
    PAIR_FEATURE_NAMES,
    GraphExample,
    _init_params,
    fit_edge_model,
    loss_for_gradient_check,
    pair_indices,
    predict_edge_probabilities,
)


def _random_example(n: int, seed: int) -> tuple[GraphExample, np.ndarray]:
    rng = np.random.default_rng(seed)
    truth = np.triu(rng.random((n, n)) < 0.4, k=1)
    truth = truth | truth.T
    observed = truth & (rng.random((n, n)) < 0.7)
    observed = np.triu(observed, k=1)
    observed = observed | observed.T
    adjacency = observed * rng.uniform(0.3, 0.9, size=(n, n))
    adjacency = np.triu(adjacency, k=1)
    adjacency = adjacency + adjacency.T
    pair = np.zeros((n, n, len(PAIR_FEATURE_NAMES)))
    pair[..., 0] = observed * rng.uniform(0.5, 3.0, size=(n, n))
    pair[..., 1] = adjacency
    pair[..., 2] = observed
    pair = np.maximum(pair, np.transpose(pair, (1, 0, 2)))
    features = rng.normal(size=(n, len(NODE_FEATURE_NAMES)))
    example = GraphExample(tuple(f"n{i}" for i in range(n)), features, adjacency, pair)
    return example, truth


def test_manual_backprop_matches_numerical_gradients() -> None:
    example, truth = _random_example(6, seed=1)
    model = fit_edge_model([example], [truth], epochs=1, seed=3)
    rng = np.random.default_rng(9)
    params = {k: v + rng.normal(scale=0.3, size=v.shape) for k, v in model.params.items()}
    pos_weight = 2.5
    _, analytic = loss_for_gradient_check(params, example, truth, model, pos_weight, l2=0.01)

    for name, value in params.items():
        numeric = np.zeros_like(value)
        it = np.nditer(value, flags=["multi_index"])
        for _ in it:
            idx = it.multi_index
            original = value[idx]
            value[idx] = original + 1e-6
            plus, _ = loss_for_gradient_check(params, example, truth, model, pos_weight, l2=0.01)
            value[idx] = original - 1e-6
            minus, _ = loss_for_gradient_check(params, example, truth, model, pos_weight, l2=0.01)
            value[idx] = original
            numeric[idx] = (plus - minus) / 2e-6
        assert np.allclose(analytic[name], numeric, rtol=1e-4, atol=1e-7), name


def test_deterministic_per_seed_and_probabilities_are_valid() -> None:
    example, truth = _random_example(7, seed=2)
    a = predict_edge_probabilities(fit_edge_model([example], [truth], epochs=30, seed=5), example)
    b = predict_edge_probabilities(fit_edge_model([example], [truth], epochs=30, seed=5), example)
    c = predict_edge_probabilities(fit_edge_model([example], [truth], epochs=30, seed=6), example)
    assert np.array_equal(a, b)
    assert not np.array_equal(a, c)
    assert np.array_equal(a, a.T) and np.all(np.diag(a) == 0)
    iu, iv = pair_indices(7)
    assert np.all((a[iu, iv] > 0) & (a[iu, iv] < 1))


def test_scores_are_node_permutation_equivariant() -> None:
    example, truth = _random_example(6, seed=3)
    model = fit_edge_model([example], [truth], epochs=20, seed=1)
    perm = np.random.default_rng(4).permutation(6)
    permuted = GraphExample(
        tuple(example.node_ids[i] for i in perm),
        example.node_features[perm],
        example.adjacency[np.ix_(perm, perm)],
        example.pair_features[np.ix_(perm, perm)],
    )
    original = predict_edge_probabilities(model, example)
    assert np.allclose(predict_edge_probabilities(model, permuted), original[np.ix_(perm, perm)])


def test_training_reduces_loss_and_fits_a_learnable_graph() -> None:
    example, truth = _random_example(10, seed=5)
    short = fit_edge_model([example], [truth], epochs=2, seed=0)
    long = fit_edge_model([example], [truth], epochs=400, seed=0)
    assert long.final_loss < short.final_loss
    p = predict_edge_probabilities(long, example)
    iu, iv = pair_indices(10)
    predicted = p[iu, iv] >= 0.5
    actual = truth[iu, iv]
    assert (predicted == actual).mean() > 0.9


def test_parameter_count_and_training_metadata() -> None:
    example, truth = _random_example(5, seed=6)
    model = fit_edge_model([example], [truth], hidden=4, embedding=3, epochs=2)
    f, k = len(NODE_FEATURE_NAMES), len(PAIR_FEATURE_NAMES)
    expected = f * 4 + 4 + 4 * 3 + 3 + (2 * 3 + k) + 1
    assert model.parameter_count == expected
    assert model.training_pair_count == 10 and model.training_example_count == 1


def test_invalid_training_inputs_are_rejected() -> None:
    example, truth = _random_example(5, seed=7)
    with pytest.raises(ValueError):
        fit_edge_model([], [])
    with pytest.raises(ValueError):
        fit_edge_model([example], [truth[:3, :3]])
    with pytest.raises(ValueError):
        fit_edge_model([example], [np.zeros_like(truth)])  # no positive pair
    with pytest.raises(ValueError):
        fit_edge_model([example], [np.ones_like(truth)])  # no negative pair


def test_init_params_shapes() -> None:
    params = _init_params(6, 3, 16, 8, np.random.default_rng(0))
    assert params["W1"].shape == (6, 16) and params["w"].shape == (2 * 8 + 3,)
