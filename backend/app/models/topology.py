"""Node and edge data contracts for the probabilistic network graph.

Serves FR-1.9-1.11 (spec Phases 29-32). Ground-truth topology (spec §4) is
deliberately NOT modeled here -- ground truth lives in a separate evaluation
artifact (introduced in a later phase) and must never be importable by the
inference pipeline.
"""

from __future__ import annotations

from datetime import datetime
from typing import List

from pydantic import BaseModel, Field, IPvAnyAddress, model_validator


class Node(BaseModel):
    """An inferred network node (spec Phase 29)."""

    node_id: str
    ip_addresses: List[IPvAnyAddress] = Field(
        ..., min_length=1, description="One or more observed addresses for this inferred node."
    )
    first_observed: datetime
    last_observed: datetime

    @model_validator(mode="after")
    def _last_not_before_first(self) -> "Node":
        if self.last_observed < self.first_observed:
            raise ValueError("last_observed cannot precede first_observed")
        return self


class Edge(BaseModel):
    """An inferred communication relationship between two nodes (spec Phase 30-31).

    Confidence must always be backed by evidence -- spec Phase 31 explicitly
    forbids arbitrary confidence values, so `evidence` and `observation_count`
    are required, not optional.
    """

    edge_id: str
    source_node_id: str
    target_node_id: str

    confidence: float = Field(..., ge=0, le=1)
    evidence: List[str] = Field(
        ..., min_length=1, description="Human-readable evidence items supporting this edge's existence."
    )
    observation_count: int = Field(..., ge=1)
    first_observed: datetime
    last_observed: datetime
    protocols: List[str] = Field(..., min_length=1)

    @model_validator(mode="after")
    def _no_self_loop(self) -> "Edge":
        if self.source_node_id == self.target_node_id:
            raise ValueError("an edge cannot connect a node to itself")
        return self

    @model_validator(mode="after")
    def _last_not_before_first(self) -> "Edge":
        if self.last_observed < self.first_observed:
            raise ValueError("last_observed cannot precede first_observed")
        return self


class TopologyGraph(BaseModel):
    """The complete inferred probabilistic topology at a point in time (spec Phase 32)."""

    graph_id: str
    generated_at: datetime
    nodes: List[Node]
    edges: List[Edge]

    @model_validator(mode="after")
    def _edges_reference_known_nodes(self) -> "TopologyGraph":
        node_ids = {n.node_id for n in self.nodes}
        for edge in self.edges:
            if edge.source_node_id not in node_ids or edge.target_node_id not in node_ids:
                raise ValueError(
                    f"edge {edge.edge_id} references a node_id not present in this graph's nodes"
                )
        return self
