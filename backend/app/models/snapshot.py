"""Network snapshot and graph-diff data contracts.

Serves FR-1.20-1.24 (spec Phases 43-49, Network Archaeology).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, model_validator


class ChangeType(str, Enum):
    NODE_ADDED = "node_added"
    NODE_REMOVED = "node_removed"
    EDGE_ADDED = "edge_added"
    EDGE_REMOVED = "edge_removed"
    ATTRIBUTE_CHANGED = "attribute_changed"


class NetworkSnapshot(BaseModel):
    """A versioned point-in-time capture of the inferred topology (spec Phase 44)."""

    snapshot_id: str
    graph_id: str = Field(..., description="References the TopologyGraph this snapshot captures.")
    captured_at: datetime
    version: int = Field(..., ge=1)


class GraphChangeEvent(BaseModel):
    """A single detected structural or attribute change between two snapshots (spec Phase 45, 47-48)."""

    event_id: str
    from_snapshot_id: str
    to_snapshot_id: str
    occurred_at: datetime

    change_type: ChangeType
    affected_node_id: Optional[str] = None
    affected_edge_id: Optional[str] = None
    attribute_name: Optional[str] = None
    previous_value: Optional[str] = None
    new_value: Optional[str] = None

    evidence: List[str] = Field(
        ..., min_length=1, description="Evidence tying this change to observations (spec Phase 48)."
    )
    affected_flow_ids: List[str] = Field(
        default_factory=list,
        description=(
            "Flow ids observationally supporting this change (spec Phase 48). Empty when no "
            "directly-attributable flow evidence exists, e.g. an ICMP-only node."
        ),
    )

    @model_validator(mode="after")
    def _target_matches_change_type(self) -> "GraphChangeEvent":
        node_types = {ChangeType.NODE_ADDED, ChangeType.NODE_REMOVED}
        edge_types = {ChangeType.EDGE_ADDED, ChangeType.EDGE_REMOVED}
        if self.change_type in node_types and self.affected_node_id is None:
            raise ValueError(f"{self.change_type} requires affected_node_id")
        if self.change_type in edge_types and self.affected_edge_id is None:
            raise ValueError(f"{self.change_type} requires affected_edge_id")
        if self.change_type == ChangeType.ATTRIBUTE_CHANGED and self.attribute_name is None:
            raise ValueError("attribute_changed requires attribute_name")
        return self
