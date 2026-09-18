"""Ground-truth generation manifest (spec Phase 17: "version and hash ground-truth artifacts").

A single capture_id can be regenerated more than once (e.g. re-running the lab). Phase 10's
`write_ground_truth`/`read_ground_truth` already hash-protect a single artifact file, but say
nothing about *which generation* that file belongs to -- a second run simply overwrote the first.
This manifest records every generation as an immutable, numbered entry so that regenerating
ground truth never silently destroys the previous one.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List

from pydantic import BaseModel


class GroundTruthManifestEntry(BaseModel):
    version: int
    generated_at: datetime
    files: Dict[str, str]  # artifact filename (e.g. "topology.json") -> sha256 hex digest


class GroundTruthManifest(BaseModel):
    capture_id: str
    generations: List[GroundTruthManifestEntry] = []

    @property
    def latest_version(self) -> int:
        if not self.generations:
            raise ValueError(f"no ground-truth generations recorded for capture_id={self.capture_id!r}")
        return max(g.version for g in self.generations)

    def entry_for(self, version: int) -> GroundTruthManifestEntry:
        for g in self.generations:
            if g.version == version:
                return g
        raise ValueError(f"no generation version={version} recorded for capture_id={self.capture_id!r}")
