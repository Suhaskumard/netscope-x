"""Per-signal attribution of a dependency-strength score (spec addendum Phase 99).

`combine_dependency_strength` (strength.py) is a five-signal noisy-OR: strength = 1 - prod(1 - t_i), where t_i is signal i's
standalone probability. A noisy-OR has no natural additive split, so "how much did each signal contribute" needs a definition.
This module uses the Shapley value of the set function v(S) = 1 - prod_{i in S}(1 - t_i) (v(empty) = 0, v(all) = strength):

  - exact (all 2^5 subsets, no sampling);
  - additive and efficient: the contributions sum EXACTLY to the strength (up to float rounding, reported as `residual`);
  - order independent (unlike attributing signals one after another);
  - a signal with t_i = 0 contributes exactly 0.
`without` is the drop-one strength (the score if that signal alone were absent) - a second, simpler view that does not sum.

No second scoring formula lives here: the per-signal probabilities mirror `combine_dependency_strength` and the result is
checked against it (`strength_from_terms`). This explains the SCORE; it is not evidence of causation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import combinations
from typing import Dict, List, Sequence

from backend.dependency.strength import (
    _DEFAULT_DEPENDENCY_SIGNAL_STRENGTH,
    _DEFAULT_FREQUENCY_SCALE,
    _DEFAULT_PERSISTENCE_SCALE,
    combine_dependency_strength,
)

SIGNALS = ("frequency", "persistence", "directionality", "traffic_characteristics", "temporal_precedence")
LABELS = {
    "frequency": "Frequency", "persistence": "Persistence", "directionality": "Directionality",
    "traffic_characteristics": "Traffic characteristics (edge confidence)", "temporal_precedence": "Temporal precedence",
}
UNITS = {"frequency": "events/s", "persistence": "s", "directionality": "0-1", "traffic_characteristics": "0-1",
         "temporal_precedence": "0-1"}


@dataclass(frozen=True)
class SignalAttribution:
    signal: str
    label: str
    raw: float
    unit: str
    term: float  # standalone probability t_i
    contribution: float  # Shapley value; contributions sum to strength
    without: float  # strength with this signal removed (drop-one)


@dataclass(frozen=True)
class Attribution:
    strength: float  # combine_dependency_strength(...)
    strength_from_terms: float  # 1 - prod(1 - t_i), recomputed from the terms
    sum_of_contributions: float
    residual: float  # strength - sum_of_contributions
    signals: List[SignalAttribution]
    parameters: Dict[str, float]


def signal_terms(
    frequency: float, persistence_seconds: float, directionality_score: float, edge_confidence: float,
    temporal_precedence_score: float, dependency_frequency_scale: float = _DEFAULT_FREQUENCY_SCALE,
    dependency_persistence_scale: float = _DEFAULT_PERSISTENCE_SCALE,
    dependency_signal_strength: float = _DEFAULT_DEPENDENCY_SIGNAL_STRENGTH,
) -> List[float]:
    """t_i in SIGNALS order, exactly the factors `combine_dependency_strength` multiplies."""
    s = dependency_signal_strength
    return [
        1 - math.exp(-frequency / dependency_frequency_scale),
        s * (1 - math.exp(-persistence_seconds / dependency_persistence_scale)),
        s * directionality_score,
        s * edge_confidence,
        s * temporal_precedence_score,
    ]


def _v(terms: Sequence[float], subset: Sequence[int]) -> float:
    survival = 1.0
    for i in subset:
        survival *= 1 - terms[i]
    return 1 - survival


def shapley(terms: Sequence[float]) -> List[float]:
    """Exact Shapley values of v(S) = 1 - prod_{i in S}(1 - t_i)."""
    n = len(terms)
    fact = [math.factorial(k) for k in range(n + 1)]
    out = []
    for i in range(n):
        others = [j for j in range(n) if j != i]
        total = 0.0
        for size in range(n):
            weight = fact[size] * fact[n - size - 1] / fact[n]
            for subset in combinations(others, size):
                total += weight * (_v(terms, (*subset, i)) - _v(terms, subset))
        out.append(total)
    return out


def attribute_strength(
    frequency: float, persistence_seconds: float, directionality_score: float, edge_confidence: float,
    temporal_precedence_score: float, dependency_frequency_scale: float = _DEFAULT_FREQUENCY_SCALE,
    dependency_persistence_scale: float = _DEFAULT_PERSISTENCE_SCALE,
    dependency_signal_strength: float = _DEFAULT_DEPENDENCY_SIGNAL_STRENGTH,
) -> Attribution:
    args = (frequency, persistence_seconds, directionality_score, edge_confidence, temporal_precedence_score)
    scales = (dependency_frequency_scale, dependency_persistence_scale, dependency_signal_strength)
    terms = signal_terms(*args, *scales)
    strength = combine_dependency_strength(*args, *scales)
    contributions = shapley(terms)
    raws = [frequency, persistence_seconds, directionality_score, edge_confidence, temporal_precedence_score]
    signals = [
        SignalAttribution(SIGNALS[i], LABELS[SIGNALS[i]], raws[i], UNITS[SIGNALS[i]], terms[i], contributions[i],
                          _v(terms, [j for j in range(5) if j != i]))
        for i in range(5)
    ]
    total = sum(contributions)
    return Attribution(
        strength=strength, strength_from_terms=_v(terms, range(5)), sum_of_contributions=total, residual=strength - total,
        signals=signals,
        parameters={"frequency_scale": scales[0], "persistence_scale": scales[1], "signal_strength": scales[2]},
    )
