"""GET /behaviors/{node_id}. Backing implementation: spec Phase 35-37
(Node Behavioral Fingerprints, Service Role Inference, Uncertainty-Aware Classification)."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from backend.app.api.errors import NotYetImplemented
from backend.app.models import BehavioralFingerprint, RoleClassification

router = APIRouter(prefix="/behaviors", tags=["behaviors"])


class NodeBehavior(BaseModel):
    fingerprint: BehavioralFingerprint
    role: RoleClassification


@router.get("/{node_id}", response_model=NodeBehavior)
def get_node_behavior(node_id: str) -> NodeBehavior:
    raise NotYetImplemented("behavioral fingerprinting and role inference (spec Phase 35-37)")
