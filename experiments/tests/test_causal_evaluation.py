"""Phase 68 causal-analysis evaluation unit tests (pure, no Docker)."""

from __future__ import annotations

from experiments.metrics.causal_evaluation import evaluate_causal_analysis
from backend.dependency.causal_candidates import CausalCandidate


def _candidate(source: str, target: str) -> CausalCandidate:
    return CausalCandidate(
        dependency_id=f"{source}->{target}",
        source_node_id=source,
        target_node_id=target,
        strength=0.9,
        temporal_precedence_score=0.8,
        rationale=["synthetic"],
    )


def test_perfect_match_scores_one() -> None:
    candidates = [_candidate("a", "b"), _candidate("b", "c")]
    ground_truth = [("a", "b"), ("b", "c")]

    result = evaluate_causal_analysis(candidates, ground_truth)

    assert result.dependency_precision == 1.0
    assert result.dependency_recall == 1.0
    assert result.dependency_f1 == 1.0
    assert result.matched_count == 2


def test_direction_matters() -> None:
    candidates = [_candidate("a", "b")]
    ground_truth = [("b", "a")]  # reversed direction -- should not match

    result = evaluate_causal_analysis(candidates, ground_truth)

    assert result.matched_count == 0
    assert result.dependency_precision == 0.0
    assert result.dependency_recall == 0.0


def test_empty_vs_empty_is_perfect_agreement() -> None:
    result = evaluate_causal_analysis([], [])
    assert (result.dependency_precision, result.dependency_recall, result.dependency_f1) == (1.0, 1.0, 1.0)


def test_predicted_extra_candidate_lowers_precision_not_recall() -> None:
    candidates = [_candidate("a", "b"), _candidate("x", "y")]
    ground_truth = [("a", "b")]

    result = evaluate_causal_analysis(candidates, ground_truth)

    assert result.dependency_recall == 1.0
    assert result.dependency_precision == 0.5


def test_missed_ground_truth_dependency_lowers_recall_not_precision() -> None:
    candidates = [_candidate("a", "b")]
    ground_truth = [("a", "b"), ("c", "d")]

    result = evaluate_causal_analysis(candidates, ground_truth)

    assert result.dependency_precision == 1.0
    assert result.dependency_recall == 0.5
