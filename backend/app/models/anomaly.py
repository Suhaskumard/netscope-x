"""Anomaly data contract.

Serves FR-1.16-1.19 (spec Phases 39-42). `evidence` is required and
non-empty by construction (min_length=1) so that "anomaly asserted without
evidence" -- explicitly forbidden by spec Phase 41 -- cannot even be
constructed, let alone stored or displayed.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Dict, List

from pydantic import BaseModel, Field


class AnomalyDimension(str, Enum):
    TRAFFIC_VOLUME = "traffic_volume"
    DESTINATIONS = "destinations"
    PORTS = "ports"
    PROTOCOLS = "protocols"
    TIMING = "timing"
    TOPOLOGY = "topology"
    BEHAVIOR = "behavior"


class AnomalyClass(str, Enum):
    """Distinguishes a transient anomaly from persistent behavioral evolution (spec Phase 39)."""

    TRANSIENT_ANOMALY = "transient_anomaly"
    CONCEPT_DRIFT = "concept_drift"


class Anomaly(BaseModel):
    node_id: str
    anomaly_id: str
    detected_at: datetime
    dimension: AnomalyDimension
    anomaly_class: AnomalyClass

    evidence: List[str] = Field(
        ..., min_length=1, description="Concrete supporting facts, e.g. 'new port 4444 observed'."
    )
    evidence_values: Dict[str, str] = Field(
        default_factory=dict,
        description="Structured evidence, e.g. {'historical_destinations': '4', 'current_destinations': '9'}.",
    )

    score: float = Field(..., ge=0, le=1, description="Anomaly severity/confidence score.")
