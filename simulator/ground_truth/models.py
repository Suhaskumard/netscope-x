"""Ground-truth artifact wrapper models (spec Phase 16).

Local to this package -- not promoted to backend/app/models, since these
wrap ground-truth artifacts specifically (roles-by-node, expected-paths-
by-pair), not general domain data contracts every module needs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List

from pydantic import BaseModel

from backend.app.models import RoleClassification


class GroundTruthRoles(BaseModel):
    generated_at: datetime
    roles: Dict[str, RoleClassification]


class GroundTruthPaths(BaseModel):
    generated_at: datetime
    paths: Dict[str, List[str]]
