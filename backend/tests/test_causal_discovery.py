"""Phase 79: time-series PC causal discovery on series with known structure."""

from __future__ import annotations

import numpy as np
import pytest

from backend.dependency.causal_candidates import CAUSAL_CANDIDATE_DISCLAIMER, format_causal_candidate
from backend.dependency.causal_discovery import (
    ASSUMPTIONS,
    discover_from_series,
    fisher_z_p_value,
    to_causal_candidates,
)
from experiments.metrics.causal_evaluation import evaluate_causal_analysis


def _pairs(result):
    return {(e.source_node_id, e.target_node_id): e for e in result.edges}


def test_fisher_z_p_value() -> None:
    assert fisher_z_p_value(0.0, 103, 0) == pytest.approx(1.0)
    assert fisher_z_p_value(0.1, 103, 0) == pytest.approx(0.3157, abs=1e-3)
    assert fisher_z_p_value(0.5, 103, 0) < 1e-6
    assert fisher_z_p_value(0.99, 5, 3) == 1.0  # no degrees of freedom -> no evidence


def test_chain_recovers_direction_and_lag() -> None:
    rng = np.random.default_rng(0)
    x = rng.normal(size=400)
    y = np.zeros(400)
    y[1:] = 0.8 * x[:-1] + 0.5 * rng.normal(size=399)
    found = _pairs(discover_from_series(np.column_stack([x, y]), ["X", "Y"]))
    assert ("X", "Y") in found and found[("X", "Y")].lag_buckets == 1
    assert ("Y", "X") not in found  # time orders the arrow: an effect cannot precede its cause


def test_common_cause_is_not_reported_as_a_direct_link() -> None:
    rng = np.random.default_rng(1)
    n = 600
    z = rng.normal(size=n)
    x, y = np.zeros(n), np.zeros(n)
    x[1:] = 0.8 * z[:-1] + 0.5 * rng.normal(size=n - 1)
    y[2:] = 0.8 * z[:-2] + 0.5 * rng.normal(size=n - 2)
    found = _pairs(discover_from_series(np.column_stack([z, x, y]), ["Z", "X", "Y"]))
    assert found[("Z", "X")].lag_buckets == 1
    assert found[("Z", "Y")].lag_buckets == 2
    # X(t-1) is correlated with Y(t) only through Z(t-2); conditioning on Z removes it
    assert ("X", "Y") not in found


def test_false_edges_on_independent_series_scale_with_alpha() -> None:
    """There is no multiple-testing correction (as in PCMCI): with 5 independent series there are 100
    candidate lagged parents, and conditioning cannot remove a chance association that is not explained
    by anything, so about alpha x 100 spurious parents survive. Documented behavior, not a bug."""
    series = np.random.default_rng(2).normal(size=(300, 5))
    loose = discover_from_series(series, list("ABCDE"), alpha=0.05)
    strict = discover_from_series(series, list("ABCDE"), alpha=0.01)
    assert loose.total_tests > 0
    assert len(loose.edges) <= 10  # expectation ~5 of 100 at alpha 0.05
    assert len(strict.edges) <= 4  # expectation ~1 of 100 at alpha 0.01
    assert len(strict.edges) <= len(loose.edges)


def test_perfect_delayed_copies_are_undefined_not_silently_resolved() -> None:
    rng = np.random.default_rng(3)
    driver = rng.normal(size=200)
    a = driver.copy()
    b = np.roll(driver, 1)
    c = np.roll(driver, 2)
    result = discover_from_series(np.column_stack([a, b, c]), ["A", "B", "C"])
    assert result.undefined_tests > 0  # exact copies cannot be told apart; counted, never hidden
    assert ("A", "C") in _pairs(result) or ("B", "C") in _pairs(result)  # a parent is kept for the effect


def test_constant_series_is_dropped_and_counted() -> None:
    rng = np.random.default_rng(4)
    series = np.column_stack([rng.normal(size=200), np.full(200, 3.0), rng.normal(size=200)])
    result = discover_from_series(series, ["A", "FLAT", "C"])
    assert result.constant_series > 0
    assert all(e.source_node_id != "FLAT" and e.target_node_id != "FLAT" for e in result.edges)


def test_too_few_buckets_returns_no_edges_and_bad_parameters_raise() -> None:
    assert discover_from_series(np.zeros((5, 3)), ["A", "B", "C"]).edges == []
    with pytest.raises(ValueError):
        discover_from_series(np.zeros((50, 2)), ["A", "B"], alpha=0.0)
    with pytest.raises(ValueError):
        discover_from_series(np.zeros((50, 2)), ["A"])


def test_deterministic() -> None:
    series = np.random.default_rng(5).normal(size=(250, 4))
    a = discover_from_series(series, list("ABCD"))
    b = discover_from_series(series, list("ABCD"))
    assert a == b


def test_candidates_carry_the_assumptions_and_the_disclaimer_and_are_scored_by_phase_68() -> None:
    rng = np.random.default_rng(0)
    x = rng.normal(size=400)
    y = np.zeros(400)
    y[1:] = 0.8 * x[:-1] + 0.5 * rng.normal(size=399)
    candidates = to_causal_candidates(discover_from_series(np.column_stack([x, y]), ["X", "Y"]).edges)

    assert [(c.source_node_id, c.target_node_id) for c in candidates] == [("X", "Y")]
    assert ASSUMPTIONS in candidates[0].rationale[1] and "p=" in candidates[0].rationale[0]
    assert CAUSAL_CANDIDATE_DISCLAIMER in format_causal_candidate(candidates[0])
    score = evaluate_causal_analysis(candidates, [("X", "Y")])
    assert score.dependency_f1 == 1.0
    assert evaluate_causal_analysis(candidates, [("Y", "X")]).dependency_f1 == 0.0  # direction matters
