"""Experiment data contract.

Serves REPRO-1 (docs/requirements/system_requirements.md) and spec Phase 20
(Research Reproducibility): every experiment must carry the full
reproducibility field set, all required (not optional), so an experiment
missing a random_seed or dataset_version cannot be recorded at all.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from pydantic import BaseModel, Field


class Experiment(BaseModel):
    experiment_id: str
    dataset_version: str
    code_version: str = Field(..., description="Git commit hash or equivalent version marker.")
    configuration: Dict[str, Any] = Field(..., description="Full configuration used for this run.")
    random_seed: int
    timestamp: datetime
    environment: str = Field(..., description="e.g. 'docker-lab', 'ci', 'local'.")
    parameters: Dict[str, Any] = Field(default_factory=dict)
    results: Dict[str, Any] = Field(
        default_factory=dict, description="Populated once the experiment completes; empty while running."
    )
