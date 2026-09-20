"""Digital Twin Model (spec Phase 57, FR-1.31 first half: "build a
computational digital twin combining topology, behavior, history,
dependencies, routing, and state").

An assembly phase, not new inference -- matching this project's
consistent pattern whenever a phase says "combine X, Y, Z" (Phase 32's
`build_topology_graph`, Phase 47's `build_topology_event_timeline`). Each
of the six named dimensions already has a real, already-built source:

- Topology -> Phase 32's `TopologyGraph`, fetched via Phase 44's
  `read_snapshot_graph` (the graph the anchoring snapshot already
  references, not recomputed).
- Behavior -> Phase 35's `BehavioralFingerprint`s, caller-supplied --
  mirroring Phase 46's own established precedent (no persisted, queryable
  fingerprint history exists anywhere in this repo; Phase 35's
  `fingerprints.jsonl` is overwrite-only).
- History -> Phase 47's `build_topology_event_timeline`, filtered to
  events at or before the anchoring snapshot's `captured_at` (a twin
  anchored at an earlier point never includes future events it couldn't
  have known about). `GraphChangeEvent.occurred_at` is already defined as
  `to_snapshot.captured_at` (Phase 45), so this filter is exact.
- Dependencies -> Phase 51-53's `estimate_dependency_strength`, called
  with `as_of=snapshot.captured_at` (Phase 43's own mechanism, already
  threaded through this function since Phase 51/52).
- Routing -> no separate field or new computation. `algorithm_selection.md`
  section 5 already selected Dijkstra/Yen's/BFS for real path analysis,
  explicitly Phase 60's job ("Dynamic Path Engine"). At this stage,
  routing is honestly represented by the topology graph's own edges (what
  can reach what) -- a deliberate, documented simplification, not glossed
  over.
- State -> the anchoring `NetworkSnapshot` itself, not a separate field.
  Confirmed, not assumed: `backend/app/models/simulation.py`'s
  `SimulationRun` (Phase 04, docstring-tagged "spec Phase 57-58, 61") has
  `twin_snapshot_id: str` -- "Digital twin state the simulation ran
  against" -- the schema itself already encodes "the twin's state = a
  NetworkSnapshot."

No new Pydantic schema -- nothing in `backend/app/models/` reserves one
for "DigitalTwin" itself, following the precedent already set by Phase
32/37/42/46/53/55's own evaluation/assembly-style outputs (a plain frozen
dataclass).

Never imports `simulator.ground_truth` (spec §4;
`scripts/check_ground_truth_boundary.py` would reject it if it did).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from backend.app.models.behavior import BehavioralFingerprint
from backend.app.models.dependency import DependencyEdge
from backend.app.models.snapshot import GraphChangeEvent, NetworkSnapshot
from backend.app.models.topology import TopologyGraph
from backend.archaeology.snapshots import read_snapshot_graph
from backend.archaeology.timeline import build_topology_event_timeline
from backend.dependency.strength import (
    _DEFAULT_DEPENDENCY_SIGNAL_STRENGTH,
    _DEFAULT_FREQUENCY_SCALE,
    _DEFAULT_PERSISTENCE_SCALE,
    estimate_dependency_strength,
)
from backend.dependency.temporal_precedence import _DEFAULT_BUCKET_SECONDS, _DEFAULT_MAX_LAG_BUCKETS
from backend.nettrace.topology.edges import _DEFAULT_PACKET_SCALE, _DEFAULT_SIGNAL_STRENGTH


@dataclass(frozen=True)
class DigitalTwin:
    capture_id: str
    snapshot: NetworkSnapshot
    topology: TopologyGraph
    behavioral_fingerprints: List[BehavioralFingerprint]
    history: List[GraphChangeEvent]
    dependencies: List[DependencyEdge]
    generated_at: datetime


def build_digital_twin(
    root: Path,
    capture_id: str,
    snapshot: NetworkSnapshot,
    behavioral_fingerprints: Optional[List[BehavioralFingerprint]] = None,
    edge_confidence_packet_scale: float = _DEFAULT_PACKET_SCALE,
    edge_confidence_signal_strength: float = _DEFAULT_SIGNAL_STRENGTH,
    dependency_frequency_scale: float = _DEFAULT_FREQUENCY_SCALE,
    dependency_persistence_scale: float = _DEFAULT_PERSISTENCE_SCALE,
    dependency_signal_strength: float = _DEFAULT_DEPENDENCY_SIGNAL_STRENGTH,
    dependency_temporal_bucket_seconds: float = _DEFAULT_BUCKET_SECONDS,
    dependency_temporal_max_lag_buckets: int = _DEFAULT_MAX_LAG_BUCKETS,
) -> DigitalTwin:
    """Assembles a `DigitalTwin` anchored at `snapshot`: the topology that
    snapshot already references, the change history up to and including
    it, and dependencies estimated as of its `captured_at` -- all fetched
    or recomputed fresh from already-real Phase 32/44/45/47/51-53
    machinery, never re-derived.

    `behavioral_fingerprints` is caller-supplied and passed straight
    through (no persisted fingerprint history exists anywhere in this
    repo to auto-fetch from, spec Phase 46's own documented limitation);
    defaults to `[]` when omitted.

    `snapshot` is not validated as genuinely belonging to `capture_id` --
    no `capture_id` field exists on `NetworkSnapshot` itself, and a
    mismatched pair fails naturally via `read_snapshot_graph`'s own file
    lookup, the same convention Phase 45's `diff_snapshots` already
    established.
    """
    topology = read_snapshot_graph(root, capture_id, snapshot)

    full_history = build_topology_event_timeline(root, capture_id)
    history = [event for event in full_history if event.occurred_at <= snapshot.captured_at]

    dependencies = estimate_dependency_strength(
        root,
        capture_id,
        as_of=snapshot.captured_at,
        edge_confidence_packet_scale=edge_confidence_packet_scale,
        edge_confidence_signal_strength=edge_confidence_signal_strength,
        dependency_frequency_scale=dependency_frequency_scale,
        dependency_persistence_scale=dependency_persistence_scale,
        dependency_signal_strength=dependency_signal_strength,
        dependency_temporal_bucket_seconds=dependency_temporal_bucket_seconds,
        dependency_temporal_max_lag_buckets=dependency_temporal_max_lag_buckets,
    )

    return DigitalTwin(
        capture_id=capture_id,
        snapshot=snapshot,
        topology=topology,
        behavioral_fingerprints=behavioral_fingerprints or [],
        history=history,
        dependencies=dependencies,
        generated_at=datetime.now(timezone.utc),
    )
