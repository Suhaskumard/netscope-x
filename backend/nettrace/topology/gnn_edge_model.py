"""GNN-based edge existence / confidence model (spec addendum Phase 77).

An alternative to Phase 31's noisy-OR edge-confidence heuristic (`edges.py`), implemented in plain numpy
(no torch: it is not a project dependency) with hand-written backpropagation, verified against numerical
gradients in `backend/tests/test_gnn_edge_model.py`.

What it does that the heuristic cannot: the heuristic only scores node pairs that already have flows; this
model scores *every* node pair, so it can propose an edge no flow evidence supports (link prediction) and
can down-weight an observed one. Whether that helps is an empirical question answered by
`experiments/gnn_benchmark.py`, not assumed.

Architecture (small on purpose -- the matrix topologies have 3-40 nodes):
    A_hat = D^-1/2 (A + I) D^-1/2          A = heuristic confidence of each *observed* node pair
    H1    = relu(A_hat X W1 + b1)
    H2    = A_hat H1 W2 + b2
    logit(u, v) = w . [H2_u * H2_v, |H2_u - H2_v|, P_uv] + b        P_uv = pair evidence features
The elementwise product/absolute-difference readout is symmetric in (u, v) and node-permutation
equivariant, so scores do not depend on node ordering.

Inputs come only from observed evidence (`GraphExample`): flows and the heuristic graph. Training labels
are a plain array supplied by the caller -- this module never imports `simulator.ground_truth` (spec §4;
`scripts/check_ground_truth_boundary.py` would reject it), exactly like `fit_role_model`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

import numpy as np

from backend.app.models.flow import Flow
from backend.app.models.topology import Edge, Node
from backend.flowmind.features.node_features import compute_node_behavioral_features

NODE_FEATURE_NAMES: Tuple[str, ...] = (
    "distinct_destinations",
    "outbound_byte_ratio",
    "log_total_bytes",
    "listening_port_count",
    "observed_degree",
    "observed_weighted_degree",
)
PAIR_FEATURE_NAMES: Tuple[str, ...] = ("log_observation_count", "heuristic_confidence", "observed")


@dataclass(frozen=True)
class GraphExample:
    """One capture's observed evidence: what the model sees. Contains no ground truth."""

    node_ids: Tuple[str, ...]
    node_features: np.ndarray  # [n, len(NODE_FEATURE_NAMES)]
    adjacency: np.ndarray  # [n, n] symmetric, heuristic confidence of observed pairs, zero diagonal
    pair_features: np.ndarray  # [n, n, len(PAIR_FEATURE_NAMES)] symmetric

    @property
    def node_count(self) -> int:
        return len(self.node_ids)


def example_from_observations(nodes: Sequence[Node], edges: Sequence[Edge], flows: Sequence[Flow]) -> GraphExample:
    """Builds a `GraphExample` from a capture's discovered nodes, heuristic edges and flows.

    Node order is `nodes` order. Edges whose endpoints are not in `nodes` are ignored.
    """
    node_ids = tuple(n.node_id for n in nodes)
    index = {node_id: i for i, node_id in enumerate(node_ids)}
    n = len(node_ids)

    adjacency = np.zeros((n, n))
    pair_features = np.zeros((n, n, len(PAIR_FEATURE_NAMES)))
    for edge in edges:
        u, v = index.get(edge.source_node_id), index.get(edge.target_node_id)
        if u is None or v is None or u == v:
            continue
        values = (math.log1p(edge.observation_count), edge.confidence, 1.0)
        adjacency[u, v] = adjacency[v, u] = edge.confidence
        pair_features[u, v] = pair_features[v, u] = values

    features = np.zeros((n, len(NODE_FEATURE_NAMES)))
    for i, node in enumerate(nodes):
        f = compute_node_behavioral_features(list(flows), node)
        features[i] = (
            f.distinct_destinations,
            f.outbound_byte_ratio,
            math.log1p(f.total_byte_count),
            len(f.distinct_ports),
            float((adjacency[i] > 0).sum()),
            float(adjacency[i].sum()),
        )
    return GraphExample(node_ids, features, adjacency, pair_features)


def pair_indices(n: int) -> Tuple[np.ndarray, np.ndarray]:
    """All unordered node pairs (u < v), the units the model scores."""
    return np.triu_indices(n, k=1)


def _normalized_adjacency(adjacency: np.ndarray) -> np.ndarray:
    a = adjacency + np.eye(adjacency.shape[0])
    d = a.sum(axis=1)
    inv_sqrt = 1.0 / np.sqrt(d)
    return a * inv_sqrt[:, None] * inv_sqrt[None, :]


@dataclass
class EdgeGNNModel:
    params: Dict[str, np.ndarray]
    x_mean: np.ndarray
    x_std: np.ndarray
    p_mean: np.ndarray
    p_std: np.ndarray
    hidden: int
    embedding: int
    training_pair_count: int
    training_example_count: int
    final_loss: float

    @property
    def parameter_count(self) -> int:
        return int(sum(p.size for p in self.params.values()))


_PARAM_ORDER = ("W1", "b1", "W2", "b2", "w", "b")


def _init_params(feature_dim: int, pair_dim: int, hidden: int, embedding: int, rng: np.random.Generator) -> Dict[str, np.ndarray]:
    def glorot(rows: int, cols: int) -> np.ndarray:
        limit = math.sqrt(6.0 / (rows + cols))
        return rng.uniform(-limit, limit, size=(rows, cols))

    readout_dim = 2 * embedding + pair_dim
    return {
        "W1": glorot(feature_dim, hidden),
        "b1": np.zeros(hidden),
        "W2": glorot(hidden, embedding),
        "b2": np.zeros(embedding),
        "w": rng.uniform(-0.1, 0.1, size=readout_dim),
        "b": np.zeros(1),
    }


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -60.0, 60.0)))


def _forward(params: Dict[str, np.ndarray], x: np.ndarray, a_hat: np.ndarray, pair_x: np.ndarray, iu: np.ndarray, iv: np.ndarray):
    ax = a_hat @ x
    z1 = ax @ params["W1"] + params["b1"]
    h1 = np.maximum(z1, 0.0)
    ah1 = a_hat @ h1
    h2 = ah1 @ params["W2"] + params["b2"]
    prod = h2[iu] * h2[iv]
    diff = h2[iu] - h2[iv]
    g = np.concatenate([prod, np.abs(diff), pair_x[iu, iv]], axis=1)
    logit = g @ params["w"] + params["b"][0]
    return logit, (ax, z1, h1, ah1, h2, diff, g)


def _loss_and_grads(
    params: Dict[str, np.ndarray],
    prepared: Sequence[Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]],
    pos_weight: float,
    l2: float,
    embedding: int,
) -> Tuple[float, Dict[str, np.ndarray]]:
    """Class-weighted mean BCE over every pair of every example, plus L2 on the weight matrices."""
    grads = {k: np.zeros_like(v) for k, v in params.items()}
    total_weight = 0.0
    total_loss = 0.0
    for _, _, _, _, y, _ in prepared:
        total_weight += float((np.where(y > 0.5, pos_weight, 1.0)).sum())

    for x, a_hat, pair_x, _, y, (iu, iv) in prepared:
        logit, (ax, z1, h1, ah1, h2, diff, g) = _forward(params, x, a_hat, pair_x, iu, iv)
        p = _sigmoid(logit)
        weight = np.where(y > 0.5, pos_weight, 1.0)
        eps = 1e-12
        total_loss += float((weight * -(y * np.log(p + eps) + (1 - y) * np.log(1 - p + eps))).sum())

        dlogit = weight * (p - y) / total_weight
        grads["w"] += g.T @ dlogit
        grads["b"] += dlogit.sum()
        dg = dlogit[:, None] * params["w"][None, :]
        d_prod, d_abs = dg[:, :embedding], dg[:, embedding : 2 * embedding]

        dh2 = np.zeros_like(h2)
        np.add.at(dh2, iu, h2[iv] * d_prod + np.sign(diff) * d_abs)
        np.add.at(dh2, iv, h2[iu] * d_prod - np.sign(diff) * d_abs)

        grads["W2"] += ah1.T @ dh2
        grads["b2"] += dh2.sum(axis=0)
        dh1 = a_hat.T @ (dh2 @ params["W2"].T)
        dz1 = dh1 * (z1 > 0)
        grads["W1"] += ax.T @ dz1
        grads["b1"] += dz1.sum(axis=0)

    loss = total_loss / total_weight
    for name in ("W1", "W2", "w"):
        loss += 0.5 * l2 * float((params[name] ** 2).sum())
        grads[name] += l2 * params[name]
    return loss, grads


def _prepare(example: GraphExample, x_mean, x_std, p_mean, p_std, labels: np.ndarray | None):
    x = (example.node_features - x_mean) / x_std
    pair_x = (example.pair_features - p_mean) / p_std
    a_hat = _normalized_adjacency(example.adjacency)
    iu, iv = pair_indices(example.node_count)
    y = labels[iu, iv].astype(float) if labels is not None else np.zeros(len(iu))
    return x, a_hat, pair_x, None, y, (iu, iv)


def fit_edge_model(
    examples: Sequence[GraphExample],
    labels: Sequence[np.ndarray],
    hidden: int = 16,
    embedding: int = 8,
    epochs: int = 300,
    learning_rate: float = 0.02,
    l2: float = 1e-3,
    seed: int = 0,
) -> EdgeGNNModel:
    """Trains on `examples` with `labels[i][u, v] = 1` iff nodes u, v of example i truly share an edge
    (a plain boolean/0-1 matrix supplied by the caller). Full-batch Adam, class-balanced BCE, deterministic
    per `seed`. Raises `ValueError` on empty input, mismatched shapes, or no positive/negative pair."""
    if not examples:
        raise ValueError("fit_edge_model requires at least one training example")
    if len(examples) != len(labels):
        raise ValueError("examples and labels must have the same length")
    for example, y in zip(examples, labels):
        if y.shape != (example.node_count, example.node_count):
            raise ValueError(f"label matrix shape {y.shape} does not match {example.node_count} nodes")

    all_x = np.concatenate([e.node_features for e in examples])
    all_p = np.concatenate([e.pair_features.reshape(-1, e.pair_features.shape[-1]) for e in examples])
    x_mean, x_std = all_x.mean(axis=0), np.maximum(all_x.std(axis=0), 1e-6)
    p_mean, p_std = all_p.mean(axis=0), np.maximum(all_p.std(axis=0), 1e-6)

    prepared = [_prepare(e, x_mean, x_std, p_mean, p_std, y) for e, y in zip(examples, labels)]
    positives = sum(float(item[4].sum()) for item in prepared)
    pairs = sum(len(item[4]) for item in prepared)
    negatives = pairs - positives
    if positives == 0 or negatives == 0:
        raise ValueError("training labels need at least one edge and one non-edge")
    pos_weight = negatives / positives

    rng = np.random.default_rng(seed)
    params = _init_params(all_x.shape[1], all_p.shape[1], hidden, embedding, rng)
    m = {k: np.zeros_like(v) for k, v in params.items()}
    s = {k: np.zeros_like(v) for k, v in params.items()}
    beta1, beta2, eps = 0.9, 0.999, 1e-8
    loss = float("nan")
    for step in range(1, epochs + 1):
        loss, grads = _loss_and_grads(params, prepared, pos_weight, l2, embedding)
        for name in params:
            m[name] = beta1 * m[name] + (1 - beta1) * grads[name]
            s[name] = beta2 * s[name] + (1 - beta2) * grads[name] ** 2
            m_hat = m[name] / (1 - beta1**step)
            s_hat = s[name] / (1 - beta2**step)
            params[name] = params[name] - learning_rate * m_hat / (np.sqrt(s_hat) + eps)

    return EdgeGNNModel(
        params=params,
        x_mean=x_mean,
        x_std=x_std,
        p_mean=p_mean,
        p_std=p_std,
        hidden=hidden,
        embedding=embedding,
        training_pair_count=int(pairs),
        training_example_count=len(examples),
        final_loss=float(loss),
    )


def predict_edge_probabilities(model: EdgeGNNModel, example: GraphExample) -> np.ndarray:
    """Symmetric [n, n] matrix of edge probabilities for every node pair (zero diagonal)."""
    n = example.node_count
    probabilities = np.zeros((n, n))
    if n < 2:
        return probabilities
    x, a_hat, pair_x, _, _, (iu, iv) = _prepare(example, model.x_mean, model.x_std, model.p_mean, model.p_std, None)
    logit, _ = _forward(model.params, x, a_hat, pair_x, iu, iv)
    p = _sigmoid(logit)
    probabilities[iu, iv] = p
    probabilities[iv, iu] = p
    return probabilities


def loss_for_gradient_check(
    params: Dict[str, np.ndarray],
    example: GraphExample,
    labels: np.ndarray,
    model: EdgeGNNModel,
    pos_weight: float,
    l2: float = 0.0,
) -> Tuple[float, Dict[str, np.ndarray]]:
    """Exposes the internal loss/gradient pair for the numerical-gradient test."""
    prepared = [_prepare(example, model.x_mean, model.x_std, model.p_mean, model.p_std, labels)]
    return _loss_and_grads(params, prepared, pos_weight, l2, model.embedding)
