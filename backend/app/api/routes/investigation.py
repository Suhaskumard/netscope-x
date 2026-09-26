"""POST /investigation/report (spec addendum Phase 100): a cited investigation report for one dependency.

The report is built from the real Phase 56 evidence report, Phase 99 attribution and (optionally) the real Phase 61/62
failure-propagation result for `failed_node_id`. An LLM may draft the prose only if `ANTHROPIC_API_KEY` is configured; its
text is verified sentence by sentence and otherwise replaced by the deterministic template (`source: "template"`). With no
key the template is returned; that is a complete report, not an error.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.app.api.schemas import CAPTURE_ID_PATTERN
from backend.app.core.config import get_settings
from backend.app.tenancy.deps import TenantScope, get_tenant_scope
from backend.dependency.causal_candidates import generate_causal_candidates
from backend.dependency.errors import DependencyNotFoundError
from backend.dependency.strength import estimate_dependency_strength
from backend.nettrace.capture.packets import ensure_packets
from backend.nettrace.reconstruct import reconstruct_flows
from backend.nettrace.topology.discovery import discover_nodes
from backend.nettrace.topology.edges import discover_edges
from backend.nettrace.topology.graph import build_topology_graph
from backend.nlq.llm import AnthropicClient, LLMClient, LLMUnavailableError
from backend.nlq.report import generate_report
from backend.nlq.rootcause import rank_root_causes

router = APIRouter(prefix="/investigation", tags=["investigation"])


class ReportRequest(BaseModel):
    capture_id: str = Field(..., pattern=CAPTURE_ID_PATTERN)
    dependency_id: str = Field(..., min_length=1, max_length=300)
    failed_node_id: Optional[str] = Field(default=None, max_length=300, description="Also report the impact of this node failing.")


def get_optional_llm() -> Optional[LLMClient]:
    """Overridable dependency: the real client when a key is configured, else None (template report)."""
    try:
        return AnthropicClient()
    except LLMUnavailableError:
        return None


@router.post("/report")
def investigation_report(
    body: ReportRequest, scope: TenantScope = Depends(get_tenant_scope), llm: Optional[LLMClient] = Depends(get_optional_llm),
) -> Dict[str, Any]:
    settings = get_settings()
    ensure_packets(scope.root, body.capture_id)
    reconstruct_flows(scope.root, body.capture_id, udp_session_idle_timeout_seconds=settings.udp_session_idle_timeout_seconds)
    kwargs = dict(edge_confidence_packet_scale=settings.edge_confidence_packet_scale,
                  edge_confidence_signal_strength=settings.edge_confidence_signal_strength)
    graph = build_topology_graph(scope.root, body.capture_id, graph_id=body.capture_id, **kwargs)
    dependencies = estimate_dependency_strength(
        scope.root, body.capture_id, dependency_frequency_scale=settings.dependency_frequency_scale,
        dependency_persistence_scale=settings.dependency_persistence_scale,
        dependency_signal_strength=settings.dependency_signal_strength,
        dependency_temporal_bucket_seconds=settings.dependency_temporal_bucket_seconds,
        dependency_temporal_max_lag_buckets=settings.dependency_temporal_max_lag_buckets, **kwargs,
    )
    index = next((i for i, d in enumerate(dependencies) if d.dependency_id == body.dependency_id), None)
    if index is None:
        raise DependencyNotFoundError(f"no dependency {body.dependency_id!r} found for capture_id={body.capture_id!r}")
    if body.failed_node_id is not None and body.failed_node_id not in {n.node_id for n in graph.nodes}:
        raise DependencyNotFoundError(f"failed_node_id {body.failed_node_id!r} is not a node of capture {body.capture_id!r}")
    edge = discover_edges(scope.root, body.capture_id, discover_nodes(scope.root, body.capture_id), **kwargs)[index]
    candidates = generate_causal_candidates(dependencies, strength_threshold=settings.causal_candidate_strength_threshold)
    candidate = next((c for c in candidates if c.dependency_id == body.dependency_id), None)
    return generate_report(graph, dependencies[index], edge.confidence, candidate, body.failed_node_id, settings, llm, candidates)


class RootCauseRequest(BaseModel):
    capture_id: str = Field(..., pattern=CAPTURE_ID_PATTERN)
    failed_node_id: str = Field(..., min_length=1, max_length=300)
    max_candidates: int = Field(default=50, ge=1, le=500)


@router.post("/root-cause")
def investigation_root_cause(body: RootCauseRequest, scope: TenantScope = Depends(get_tenant_scope)) -> Dict[str, Any]:
    """Phase 101: candidates ranked by what removing them would have prevented, from really executed counterfactuals."""
    settings = get_settings()
    ensure_packets(scope.root, body.capture_id)
    reconstruct_flows(scope.root, body.capture_id, udp_session_idle_timeout_seconds=settings.udp_session_idle_timeout_seconds)
    kwargs = dict(edge_confidence_packet_scale=settings.edge_confidence_packet_scale,
                  edge_confidence_signal_strength=settings.edge_confidence_signal_strength)
    graph = build_topology_graph(scope.root, body.capture_id, graph_id=body.capture_id, **kwargs)
    if body.failed_node_id not in {n.node_id for n in graph.nodes}:
        raise DependencyNotFoundError(f"failed_node_id {body.failed_node_id!r} is not a node of capture {body.capture_id!r}")
    dependencies = estimate_dependency_strength(
        scope.root, body.capture_id, dependency_frequency_scale=settings.dependency_frequency_scale,
        dependency_persistence_scale=settings.dependency_persistence_scale,
        dependency_signal_strength=settings.dependency_signal_strength,
        dependency_temporal_bucket_seconds=settings.dependency_temporal_bucket_seconds,
        dependency_temporal_max_lag_buckets=settings.dependency_temporal_max_lag_buckets, **kwargs,
    )
    candidates = generate_causal_candidates(dependencies, strength_threshold=settings.causal_candidate_strength_threshold)
    return rank_root_causes(graph, body.failed_node_id, candidates, body.max_candidates)
