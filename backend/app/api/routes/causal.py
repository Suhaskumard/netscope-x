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

from fastapi import APIRouter, Query

from backend.app.api.schemas import CAPTURE_ID_PATTERN
from backend.app.core.config import get_settings
from backend.app.models import CausalEvidenceReport
from backend.dependency.causal_candidates import generate_causal_candidates
from backend.dependency.causal_evidence import build_dependency_evidence_report
from backend.dependency.errors import DependencyNotFoundError
from backend.dependency.strength import estimate_dependency_strength

router = APIRouter(prefix="/causal", tags=["causal"])


@router.get("/{dependency_id}", response_model=CausalEvidenceReport)
def get_causal_evidence(
    dependency_id: str,
    capture_id: str = Query(
        ..., description="Capture session dependency_id belongs to.", pattern=CAPTURE_ID_PATTERN
    ),
) -> CausalEvidenceReport:
    settings = get_settings()
    dependencies = estimate_dependency_strength(
        settings.artifact_root,
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
