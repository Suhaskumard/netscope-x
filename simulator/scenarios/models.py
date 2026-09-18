"""Scenario artifact models (spec Phase 18).

`ScenarioDeclaration` is the persisted, design-level shape of a generated topology -- roles and
edges, JSON-serializable via Pydantic -- distinct from `backend.app.models.TopologyGraph`, which
requires real observed IP addresses per node. A generated scenario only gets a `TopologyGraph`
once it is actually deployed and its container IPs are looked up (see `generate.py`); most
generated scenarios are never deployed this phase, so `ScenarioDeclaration` is what actually gets
persisted for all 6 archetypes.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List

from pydantic import BaseModel

from backend.app.models import ServiceRole


class ScenarioArchetype(str, Enum):
    SIMPLE_CHAIN = "simple_chain"
    STAR = "star"
    MULTI_TIER = "multi_tier"
    REDUNDANT = "redundant"
    MULTI_PATH = "multi_path"
    DYNAMIC_SERVICE_NETWORK = "dynamic_service_network"


class ScenarioEdgeModel(BaseModel):
    source: str
    target: str
    protocols: List[str]


class ScenarioDeclaration(BaseModel):
    roles: Dict[str, ServiceRole]
    edges: List[ScenarioEdgeModel]


class ScenarioSpec(BaseModel):
    scenario_id: str
    archetype: ScenarioArchetype
    parameters: Dict[str, Any]
    node_count: int
    edge_count: int
