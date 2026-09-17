"""Dependency and causal-evidence data contracts.

Serves FR-1.25-1.30 (spec Phases 50-56). The central design point (spec
Phase 50, RQ5 in docs/research/research_questions.md): "A communicates with
B" and "A depends on B" are modeled as two distinct types, so a caller can
never accidentally treat mere communication as a dependency claim.
"""

from __future__ import annotations

from datetime import datetime
from typing import List

from pydantic import BaseModel, Field, model_validator


class CommunicationRelationship(BaseModel):
    """Observed communication between two nodes -- carries no dependency claim."""

    source_node_id: str
    target_node_id: str
    frequency: float = Field(..., ge=0, description="Observed communication frequency (events/sec).")
    persistence_seconds: float = Field(..., ge=0)


class DependencyEdge(BaseModel):
    """An inferred dependency, distinct from mere communication (spec Phase 50-51)."""

    dependency_id: str
    source_node_id: str
    target_node_id: str

    strength: float = Field(..., ge=0, le=1, description="Estimated dependency strength.")
    frequency: float = Field(..., ge=0)
    persistence_seconds: float = Field(..., ge=0)
    directionality_score: float = Field(
        ..., ge=0, le=1, description="How one-directional the traffic is; 1.0 = fully one-way."
    )
    temporal_precedence_score: float = Field(
        default=0.0,
        ge=0,
        le=1,
        description="Strength of evidence that source-side changes precede target-side changes (spec Phase 52).",
    )

    @model_validator(mode="after")
    def _no_self_dependency(self) -> "DependencyEdge":
        if self.source_node_id == self.target_node_id:
            raise ValueError("a node cannot depend on itself")
        return self


class CausalEvidenceReport(BaseModel):
    """Required accompaniment for any inferred dependency/propagation claim (spec Phase 56)."""

    report_id: str
    relationship: str = Field(..., description="Human-readable statement of the claimed relationship.")
    evidence: List[str] = Field(..., min_length=1)
    confidence: float = Field(..., ge=0, le=1)
    counter_evidence: List[str] = Field(
        default_factory=list, description="Evidence against the claim; empty list means none observed."
    )
    limitations: List[str] = Field(
        ..., min_length=1, description="At least one limitation must always be stated (spec Phase 56)."
    )
    generated_at: datetime
