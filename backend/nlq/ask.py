"""Question in, grounded answer out: translate -> execute (real Phase 65) -> compare (real Phase 66) -> explain (verified)."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List, Optional

from backend.app.models.behavior import RoleClassification
from backend.app.models.topology import TopologyGraph
from backend.dependency.causal_candidates import CausalCandidate
from backend.nlq.explain import explain_result
from backend.nlq.llm import LLMClient
from backend.nlq.translate import NeedsClarification, Rejected, Translated, translate_question
from backend.simulation.counterfactual_comparison import compare_counterfactual_outcome
from backend.simulation.counterfactual_engine import execute_counterfactual_scenario


def ask_counterfactual(
    question: str,
    graph: TopologyGraph,
    llm: LLMClient,
    roles: Optional[Dict[str, str]] = None,
    candidates: Optional[List[CausalCandidate]] = None,
    role_classifications: Optional[Dict[str, RoleClassification]] = None,
) -> Dict[str, Any]:
    """`status` is "answered", "needs_clarification" or "rejected". Only "answered" carries a scenario/result."""
    outcome = translate_question(question, graph, llm, roles)
    if isinstance(outcome, Rejected):
        return {"status": "rejected", "reason": outcome.reason, "detail": outcome.detail,
                "supported_actions": outcome.supported_actions}
    if isinstance(outcome, NeedsClarification):
        return {"status": "needs_clarification", "question": outcome.question, "candidates": outcome.candidates}
    assert isinstance(outcome, Translated)
    try:
        execution = execute_counterfactual_scenario(graph, outcome.scenario)
    except ValueError as exc:  # e.g. ADD_ROUTE between already-connected nodes
        return {"status": "rejected", "reason": "invalid_scenario", "detail": str(exc), "scenario": outcome.scenario.model_dump(mode="json")}
    result = compare_counterfactual_outcome(graph, execution, candidates, role_classifications)
    explanation = explain_result(graph, result, question, llm)
    return {
        "status": "answered",
        "scenario": outcome.scenario.model_dump(mode="json"),
        "refers_to": outcome.refers_to,
        "facts": [asdict(f) | {"entities": sorted(f.entities), "numbers": sorted(f.numbers)} for f in explanation.facts],
        "explanation": explanation.text,
        "explanation_source": explanation.source,
        "explanation_violations": explanation.violations,
    }
