"""GET /causal/{dependency_id}. Backing implementation: spec Phase 56 (Causal Evidence Report).

Every response is a CausalEvidenceReport (relationship, evidence,
confidence, counter_evidence, limitations) -- never a bare causal claim.

Takes an explicit `capture_id` query parameter, deliberately deviating from
the bare `/causal/{dependency_id}` path shown above -- every sibling route
(GET /flows, GET /topology, GET /dependencies) takes `capture_id` as an
explicit query parameter rather than parsing it out of another id's
internal string format; `dependency_id`'s `f"{capture_id}:dependency:
{index}"` shape was never meant to be a public parsing contract.

Recomputes `estimate_dependency_strength`/`generate_causal_candidates`
fresh on every call, the same convention GET /dependencies already
established. An unknown `dependency_id` -- whether because the capture
doesn't exist or the capture exists but that id doesn't match -- raises
DependencyNotFoundError (404), mirroring GET /flows/GET /topology's own
single-resource-by-id 404 convention (distinct from GET /dependencies/
GET /history's empty-list-means-200 convention, which only applies to
paginated list routes)."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict

from fastapi import Depends, APIRouter, Query

from backend.app.api.schemas import CAPTURE_ID_PATTERN
from backend.app.core.config import get_settings
from backend.app.tenancy.deps import TenantScope, get_tenant_scope
from backend.app.models import CausalEvidenceReport
from backend.dependency.causal_candidates import generate_causal_candidates
from backend.dependency.causal_evidence import build_dependency_evidence_report
from backend.dependency.errors import DependencyNotFoundError
from backend.dependency.attribution import attribute_strength
from backend.dependency.strength import estimate_dependency_strength
from backend.nettrace.topology.discovery import discover_nodes
from backend.nettrace.topology.edges import discover_edges

router = APIRouter(prefix="/causal", tags=["causal"])


@router.get("/{dependency_id}", response_model=CausalEvidenceReport)
def get_causal_evidence(
    dependency_id: str,
    capture_id: str = Query(
        ..., description="Capture session dependency_id belongs to.", pattern=CAPTURE_ID_PATTERN
    ),
    scope: TenantScope = Depends(get_tenant_scope),
) -> CausalEvidenceReport:
    settings = get_settings()
    dependencies = estimate_dependency_strength(
        scope.root,
        capture_id,
        edge_confidence_packet_scale=settings.edge_confidence_packet_scale,
        edge_confidence_signal_strength=settings.edge_confidence_signal_strength,
        dependency_frequency_scale=settings.dependency_frequency_scale,
        dependency_persistence_scale=settings.dependency_persistence_scale,
        dependency_signal_strength=settings.dependency_signal_strength,
        dependency_temporal_bucket_seconds=settings.dependency_temporal_bucket_seconds,
        dependency_temporal_max_lag_buckets=settings.dependency_temporal_max_lag_buckets,
    )
    dependency = next((d for d in dependencies if d.dependency_id == dependency_id), None)
    if dependency is None:
        raise DependencyNotFoundError(
            f"no dependency {dependency_id!r} found for capture_id={capture_id!r}"
        )

    candidates = generate_causal_candidates(
        dependencies, strength_threshold=settings.causal_candidate_strength_threshold
    )
    candidate = next((c for c in candidates if c.dependency_id == dependency_id), None)

    return build_dependency_evidence_report(dependency, candidate)


@router.get("/{dependency_id}/attribution")
def get_causal_attribution(
    dependency_id: str,
    capture_id: str = Query(..., description="Capture session dependency_id belongs to.", pattern=CAPTURE_ID_PATTERN),
    scope: TenantScope = Depends(get_tenant_scope),
) -> Dict[str, Any]:
    """Phase 99: the per-signal breakdown of one dependency's strength (exact Shapley attribution of the noisy-OR; the
    contributions sum to `strength`, `residual` shows any float error). The fifth signal, the pair's Phase 31 edge confidence,
    is read from `discover_edges` (dependency i <-> edge i by construction in `estimate_dependency_strength`)."""
    settings = get_settings()
    kwargs = dict(
        edge_confidence_packet_scale=settings.edge_confidence_packet_scale,
        edge_confidence_signal_strength=settings.edge_confidence_signal_strength,
    )
    dependencies = estimate_dependency_strength(
        scope.root, capture_id,
        dependency_frequency_scale=settings.dependency_frequency_scale,
        dependency_persistence_scale=settings.dependency_persistence_scale,
        dependency_signal_strength=settings.dependency_signal_strength,
        dependency_temporal_bucket_seconds=settings.dependency_temporal_bucket_seconds,
        dependency_temporal_max_lag_buckets=settings.dependency_temporal_max_lag_buckets,
        **kwargs,
    )
    index = next((i for i, d in enumerate(dependencies) if d.dependency_id == dependency_id), None)
    if index is None:
        raise DependencyNotFoundError(f"no dependency {dependency_id!r} found for capture_id={capture_id!r}")
    dependency = dependencies[index]
    edge = discover_edges(scope.root, capture_id, discover_nodes(scope.root, capture_id), **kwargs)[index]
    attribution = attribute_strength(
        dependency.frequency, dependency.persistence_seconds, dependency.directionality_score, edge.confidence,
        dependency.temporal_precedence_score, settings.dependency_frequency_scale,
        settings.dependency_persistence_scale, settings.dependency_signal_strength,
    )
    candidates = generate_causal_candidates(dependencies, strength_threshold=settings.causal_candidate_strength_threshold)
    report = build_dependency_evidence_report(dependency, next((c for c in candidates if c.dependency_id == dependency_id), None))
    return {
        "dependency_id": dependency_id, "source_node_id": dependency.source_node_id,
        "target_node_id": dependency.target_node_id, "stored_strength": dependency.strength,
        **asdict(attribution), "report": report.model_dump(mode="json"),
    }
