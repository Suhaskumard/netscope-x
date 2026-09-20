"""Failure-injection and propagation-impact data contracts.

Serves FR-1.28, FR-1.32-1.35 (spec Phases 54, 59-62).
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, model_validator


class FailureType(str, Enum):
    NODE_FAILURE = "node_failure"
    EDGE_FAILURE = "edge_failure"
    LATENCY_INJECTION = "latency_injection"
    PACKET_LOSS = "packet_loss"
    BANDWIDTH_REDUCTION = "bandwidth_reduction"
    SERVICE_DEGRADATION = "service_degradation"


class FailureScenario(BaseModel):
    """A controlled failure-injection request (spec Phase 59)."""

    scenario_id: str
    failure_type: FailureType
    target_node_id: Optional[str] = None
    target_edge_id: Optional[str] = None

    latency_ms: Optional[float] = Field(default=None, ge=0)
    packet_loss_ratio: Optional[float] = Field(default=None, ge=0, le=1)
    bandwidth_reduction_ratio: Optional[float] = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def _target_matches_failure_type(self) -> "FailureScenario":
        node_types = {
            FailureType.NODE_FAILURE,
            FailureType.LATENCY_INJECTION,
            FailureType.SERVICE_DEGRADATION,
        }
        if self.failure_type in node_types and self.target_node_id is None:
            raise ValueError(f"{self.failure_type} requires target_node_id")
        if self.failure_type == FailureType.EDGE_FAILURE and self.target_edge_id is None:
            raise ValueError("edge_failure requires target_edge_id")
        if self.failure_type == FailureType.PACKET_LOSS and self.packet_loss_ratio is None:
            raise ValueError("packet_loss requires packet_loss_ratio")
        if self.failure_type == FailureType.BANDWIDTH_REDUCTION and self.bandwidth_reduction_ratio is None:
            raise ValueError("bandwidth_reduction requires bandwidth_reduction_ratio")
        return self


class ImpactOrder(str, Enum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    TERTIARY = "tertiary"


class PropagationImpact(BaseModel):
    """A single node/service impacted by a failure, at a given propagation order (spec Phase 54, 61)."""

    scenario_id: str
    affected_node_id: str
    order: ImpactOrder
    caused_by_node_id: Optional[str] = Field(
        default=None, description="Upstream node whose impact propagated to this one; None for primary."
    )
    evidence: List[str] = Field(..., min_length=1)

    @model_validator(mode="after")
    def _primary_has_no_cause(self) -> "PropagationImpact":
        if self.order == ImpactOrder.PRIMARY and self.caused_by_node_id is not None:
            raise ValueError("a primary impact cannot have a caused_by_node_id")
        if self.order != ImpactOrder.PRIMARY and self.caused_by_node_id is None:
            raise ValueError(f"{self.order} impact requires caused_by_node_id")
        return self


class ResilienceIndicators(BaseModel):
    """Measured resilience metrics after a simulated failure (spec Phase 62)."""

    scenario_id: str
    connectivity_ratio: float = Field(..., ge=0, le=1)
    reachable_node_ratio: float = Field(..., ge=0, le=1)
    affected_service_count: int = Field(..., ge=0)
    path_degradation_score: float = Field(..., ge=0)
    bottleneck_node_ids: List[str] = Field(default_factory=list)
    alternative_path_available: bool
