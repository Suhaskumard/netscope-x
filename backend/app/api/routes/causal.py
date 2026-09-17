"""GET /causal/{dependency_id}. Backing implementation: spec Phase 56 (Causal Evidence Report).

Every response is a CausalEvidenceReport (relationship, evidence,
confidence, counter_evidence, limitations) -- never a bare causal claim."""

from __future__ import annotations

from fastapi import APIRouter

from backend.app.api.errors import NotYetImplemented
from backend.app.models import CausalEvidenceReport

router = APIRouter(prefix="/causal", tags=["causal"])


@router.get("/{dependency_id}", response_model=CausalEvidenceReport)
def get_causal_evidence(dependency_id: str) -> CausalEvidenceReport:
    raise NotYetImplemented("causal evidence reporting (spec Phase 56)")
