"""Small Gaussian-process Bayesian optimizer in numpy (spec Phase 82; no new dependency).

Maximizes a noisy scalar objective over a box: Matern-5/2 GP on the unit cube (log-scaled dimensions are
searched in log space, integer ones rounded), expected improvement over a random candidate pool plus local
perturbations of the incumbent, deterministic per `seed`. The caller's `start` point (the current default) is
always evaluated first, so the reported best on the tuning data is never worse than the baseline.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence

import numpy as np


@dataclass(frozen=True)
class Dimension:
    name: str
    low: float
    high: float
    log: bool = False
    integer: bool = False

    def __post_init__(self) -> None:
        if not self.high > self.low:
            raise ValueError(f"{self.name}: high must exceed low")
        if self.log and self.low <= 0:
            raise ValueError(f"{self.name}: log scale needs a positive lower bound")

    def from_unit(self, u: float) -> float:
        u = min(1.0, max(0.0, float(u)))
        if self.log:
            value = math.exp(math.log(self.low) + u * (math.log(self.high) - math.log(self.low)))
        else:
            value = self.low + u * (self.high - self.low)
        return int(round(value)) if self.integer else value

    def to_unit(self, value: float) -> float:
        if self.log:
            return (math.log(value) - math.log(self.low)) / (math.log(self.high) - math.log(self.low))
        return (value - self.low) / (self.high - self.low)


@dataclass
class BOResult:
    best_params: Dict[str, float]
    best_value: float
    history: List[Dict] = field(default_factory=list)  # every evaluation: {"params", "value"}
    evaluations: int = 0


def _matern52(a: np.ndarray, b: np.ndarray, length: float) -> np.ndarray:
    d = np.sqrt(np.maximum(((a[:, None, :] - b[None, :, :]) ** 2).sum(-1), 0.0)) / length
    return (1.0 + math.sqrt(5.0) * d + 5.0 / 3.0 * d**2) * np.exp(-math.sqrt(5.0) * d)


def _fit_gp(x: np.ndarray, y: np.ndarray, noise: float):
    """Normalized-target GP; lengthscale picked from a small grid by log marginal likelihood."""
    mean, std = float(y.mean()), float(y.std()) or 1.0
    yn = (y - mean) / std
    best = None
    for length in (0.15, 0.3, 0.6, 1.2):
        k = _matern52(x, x, length) + (noise + 1e-8) * np.eye(len(x))
        try:
            chol = np.linalg.cholesky(k)
        except np.linalg.LinAlgError:
            continue
        alpha = np.linalg.solve(chol.T, np.linalg.solve(chol, yn))
        lml = -0.5 * float(yn @ alpha) - float(np.log(np.diag(chol)).sum())
        if best is None or lml > best[0]:
            best = (lml, length, chol, alpha)
    if best is None:
        raise np.linalg.LinAlgError("GP covariance not positive definite")
    _, length, chol, alpha = best
    return length, chol, alpha, mean, std


def _expected_improvement(candidates, x, gp, incumbent: float) -> np.ndarray:
    length, chol, alpha, mean, std = gp
    ks = _matern52(candidates, x, length)
    mu = ks @ alpha
    v = np.linalg.solve(chol, ks.T)
    sigma = np.sqrt(np.maximum(1.0 - (v**2).sum(0), 1e-12))
    z = (mu - (incumbent - mean) / std) / sigma
    cdf = 0.5 * (1.0 + np.vectorize(math.erf)(z / math.sqrt(2.0)))
    pdf = np.exp(-0.5 * z**2) / math.sqrt(2.0 * math.pi)
    return sigma * (z * cdf + pdf)


def optimize(
    objective: Callable[[Dict[str, float]], float],
    dimensions: Sequence[Dimension],
    n_init: int = 6,
    n_iter: int = 18,
    seed: int = 0,
    start: Optional[Dict[str, float]] = None,
    noise: float = 1e-4,
) -> BOResult:
    """Maximizes `objective(params)`. Evaluations = `n_init` (including `start`) + `n_iter`, minus repeats: a
    point whose rounded params were already evaluated is not evaluated again."""
    if not dimensions:
        raise ValueError("optimize needs at least one dimension")
    if n_init < 1 or n_iter < 0:
        raise ValueError("n_init must be >= 1 and n_iter >= 0")
    rng = np.random.default_rng(seed)
    d = len(dimensions)

    def decode(u: np.ndarray) -> Dict[str, float]:
        return {dim.name: dim.from_unit(u[i]) for i, dim in enumerate(dimensions)}

    def encode(params: Dict[str, float]) -> np.ndarray:
        return np.array([min(1.0, max(0.0, dim.to_unit(params[dim.name]))) for dim in dimensions])

    def key_of(params: Dict[str, float]) -> tuple:
        return tuple(params[dim.name] for dim in dimensions)

    seen: set = set()
    xs: List[np.ndarray] = []
    ys: List[float] = []
    history: List[Dict] = []

    def evaluate(u: np.ndarray) -> bool:
        params = decode(u)
        key = key_of(params)
        if key in seen:
            return False
        seen.add(key)
        value = float(objective(params))
        xs.append(encode(params))  # re-encoded so integer rounding is what the GP sees
        ys.append(value)
        history.append({"params": params, "value": value})
        return True

    if start is not None:
        evaluate(encode(start))
    attempts = 0
    while len(xs) < n_init and attempts < 200 * n_init:
        evaluate(rng.random(d))
        attempts += 1

    for _ in range(n_iter):
        x, y = np.array(xs), np.array(ys)
        try:
            gp = _fit_gp(x, y, noise)
        except np.linalg.LinAlgError:
            evaluate(rng.random(d))
            continue
        pool = rng.random((1500, d))
        local = np.clip(x[int(np.argmax(y))] + rng.normal(0.0, 0.08, size=(500, d)), 0.0, 1.0)
        candidates = np.vstack([pool, local])
        ei = _expected_improvement(candidates, x, gp, float(y.max()))
        for idx in np.argsort(-ei)[:50]:  # first candidate that is not a repeat after rounding
            if evaluate(candidates[idx]):
                break
        else:
            break  # everything promising has been evaluated (small integer space)

    best = int(np.argmax(ys))
    return BOResult(best_params=history[best]["params"], best_value=ys[best], history=history, evaluations=len(ys))
