"""Behavioral fingerprint and role-classification data contracts.

Serves FR-1.12-1.16 (spec Phases 33-38). Role classification is deliberately
represented as a probability distribution, never a single hard label --
spec Phase 37 requires calibrated uncertainty, not a point guess.
"""

from __future__ import annotations

import math
from datetime import datetime
from enum import Enum
from typing import Dict, List

from pydantic import BaseModel, Field, model_validator


class ServiceRole(str, Enum):
    CLIENT = "Client"
    GATEWAY = "Gateway"
    API = "API"
    DATABASE = "Database"
    CACHE = "Cache"
    DNS = "DNS"
    WORKER = "Worker"
    LOAD_BALANCER = "Load Balancer"
    UNKNOWN = "Unknown"


class ObservationWindow(str, Enum):
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"


class BehavioralFingerprint(BaseModel):
    """A node's behavioral signature over a given observation window (spec Phase 33-35)."""

    node_id: str
    window: ObservationWindow
    computed_at: datetime

    distinct_ports: List[int] = Field(default_factory=list)
    distinct_protocols: List[str] = Field(default_factory=list)
    distinct_destinations: int = Field(..., ge=0)
    mean_flow_duration_seconds: float = Field(..., ge=0)
    outbound_byte_ratio: float = Field(..., ge=0, le=1)
    is_persistent_talker: bool


class RoleClassification(BaseModel):
    """Uncertainty-aware role inference for a single node (spec Phase 36-37)."""

    node_id: str
    computed_at: datetime
    role_probabilities: Dict[ServiceRole, float] = Field(
        ..., min_length=1, description="Probability per candidate role; must sum to ~1."
    )

    @model_validator(mode="after")
    def _probabilities_sum_to_one(self) -> "RoleClassification":
        total = sum(self.role_probabilities.values())
        if not math.isclose(total, 1.0, abs_tol=1e-3):
            raise ValueError(f"role_probabilities must sum to ~1.0, got {total}")
        for role, prob in self.role_probabilities.items():
            if not (0.0 <= prob <= 1.0):
                raise ValueError(f"probability for role {role} out of [0,1]: {prob}")
        return self

    @property
    def best_role(self) -> ServiceRole:
        return max(self.role_probabilities, key=lambda r: self.role_probabilities[r])
