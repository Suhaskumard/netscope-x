"""POST /counterfactual. Backing implementation: spec Phase 64-66 (Counterfactual Scenario
Language, Counterfactual Graph Engine, Counterfactual Impact Analysis).

Known simplification: the request body currently mirrors the full
CounterfactualScenario domain object (including server-assignable fields
like scenario_id/isolated_graph_id) rather than a dedicated "create"
request DTO. This is acceptable for a not-yet-implemented contract; a
slimmer request schema should be introduced alongside the real
implementation in Phase 64-66 if server-side ID assignment is adopted."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.app.api.errors import NotYetImplemented
from backend.app.api.schemas import CAPTURE_ID_PATTERN
from backend.app.core.config import get_settings
from backend.app.models import CounterfactualScenario
from backend.app.tenancy.deps import TenantScope, get_tenant_scope
from backend.dependency.causal_candidates import generate_causal_candidates
from backend.dependency.strength import estimate_dependency_strength
from backend.nettrace.capture.packets import ensure_packets
from backend.nettrace.reconstruct import reconstruct_flows
from backend.nettrace.topology.graph import build_topology_graph
from backend.nlq.ask import ask_counterfactual
from backend.nlq.llm import AnthropicClient, LLMClient

router = APIRouter(prefix="/counterfactual", tags=["counterfactual"])


@router.post("", response_model=CounterfactualScenario, status_code=202)
def run_counterfactual(scenario: CounterfactualScenario) -> CounterfactualScenario:
    raise NotYetImplemented("counterfactual engine (spec Phase 64-66)")


class AskRequest(BaseModel):
    capture_id: str = Field(..., pattern=CAPTURE_ID_PATTERN)
    question: str = Field(..., min_length=3, max_length=500)


def get_llm() -> LLMClient:
    """Overridable dependency; raises LLMUnavailableError (-> 503 llm_unavailable) without ANTHROPIC_API_KEY."""
    return AnthropicClient()


@router.post("/ask", tags=["counterfactual"])
def ask(body: AskRequest, scope: TenantScope = Depends(get_tenant_scope), llm: LLMClient = Depends(get_llm)) -> Dict[str, Any]:
    """Phase 98: a natural-language what-if question. The LLM only translates it into a structured scenario over the
    capture's real topology and words the real result; see docs/architecture/nl_counterfactual.md."""
    settings = get_settings()
    ensure_packets(scope.root, body.capture_id)
    reconstruct_flows(scope.root, body.capture_id, udp_session_idle_timeout_seconds=settings.udp_session_idle_timeout_seconds)
    graph = build_topology_graph(
        scope.root, body.capture_id, graph_id=body.capture_id,
        edge_confidence_packet_scale=settings.edge_confidence_packet_scale,
        edge_confidence_signal_strength=settings.edge_confidence_signal_strength,
    )
    candidates = generate_causal_candidates(estimate_dependency_strength(scope.root, body.capture_id))
    return ask_counterfactual(body.question, graph, llm, candidates=candidates)
