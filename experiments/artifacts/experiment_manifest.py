"""Experiment run manifest (spec addendum Phase 75: "experiment idempotency and versioning").

Mirrors Phase 17's `GroundTruthManifest`: re-running the same matrix cell (same
`experiment_id`, i.e. same topology_level/completeness/ablation/variant/seed) used to
silently overwrite the previous run's `experiment.json`/`metrics.jsonl`. This manifest
records every run as an immutable, numbered entry under its own `v<N>/` directory, so a
re-run can never destroy an earlier run's results.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List

from pydantic import BaseModel


class ExperimentManifestEntry(BaseModel):
    version: int
    recorded_at: datetime
    capture_id: str  # the capture this run's packets/flows/snapshots were written under
    files: Dict[str, str]  # run filename (e.g. "metrics.jsonl") -> sha256 hex digest


class ExperimentManifest(BaseModel):
    experiment_id: str
    runs: List[ExperimentManifestEntry] = []

    @property
    def latest_version(self) -> int:
        if not self.runs:
            raise ValueError(f"no runs recorded for experiment_id={self.experiment_id!r}")
        return max(r.version for r in self.runs)

    def entry_for(self, version: int) -> ExperimentManifestEntry:
        for r in self.runs:
            if r.version == version:
                return r
        raise ValueError(f"no run version={version} recorded for experiment_id={self.experiment_id!r}")
