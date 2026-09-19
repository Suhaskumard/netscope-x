"""Network Snapshot Engine (spec Phase 44, FR-1.21: "generate versioned
network snapshots").

The first real code in `backend/archaeology/` (deliberately deferred from
Phase 43 -- see `docs/architecture/temporal_graph_model.md`'s own note that
this package "stays justified for Phase 44"). Wires together three pieces
that were each already designed for this moment but never connected:
`backend/app/models/snapshot.py`'s `NetworkSnapshot` (Phase 04, never
constructed for real anywhere until now), `experiments/artifacts/
paths.py`'s `snapshot_path` (reserved since Phase 10's original artifact
layout, never called anywhere until now), and Phase 43's `as_of`-aware
`build_topology_graph` (the mechanism that lets a snapshot's claimed
capture time genuinely match the evidence its graph contains).

Never imports `simulator.ground_truth` (`scripts/check_ground_truth_boundary.py`
statically forbids it, spec §4's ground-truth rule).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from backend.app.models.snapshot import NetworkSnapshot
from backend.app.models.topology import TopologyGraph
from backend.nettrace.topology.edges import _DEFAULT_PACKET_SCALE, _DEFAULT_SIGNAL_STRENGTH
from backend.nettrace.topology.graph import build_topology_graph
from experiments.artifacts.io import read_json, write_json
from experiments.artifacts.paths import snapshot_path, snapshots_dir, topology_path


def list_snapshots(root: Path, capture_id: str) -> List[NetworkSnapshot]:
    """Reads every persisted `NetworkSnapshot` for `capture_id` back from
    disk, ordered by `version` ascending. Returns `[]` for a capture with
    no snapshots yet -- never an error, consistent with `discover_nodes`/
    `discover_edges`'s established "missing means empty" convention.
    """
    directory = snapshots_dir(root, capture_id)
    if not directory.is_dir():
        return []
    snapshots = [read_json(path, NetworkSnapshot) for path in sorted(directory.glob("*.json"))]
    return sorted(snapshots, key=lambda s: s.version)


def read_snapshot_graph(root: Path, capture_id: str, snapshot: NetworkSnapshot) -> TopologyGraph:
    """Reads back the `TopologyGraph` `snapshot.graph_id` references."""
    return read_json(topology_path(root, capture_id, snapshot.graph_id), TopologyGraph)


def create_snapshot(
    root: Path,
    capture_id: str,
    captured_at: Optional[datetime] = None,
    edge_confidence_packet_scale: float = _DEFAULT_PACKET_SCALE,
    edge_confidence_signal_strength: float = _DEFAULT_SIGNAL_STRENGTH,
) -> NetworkSnapshot:
    """Generates and persists the next versioned `NetworkSnapshot` for
    `capture_id`.

    `captured_at` (default `datetime.now(timezone.utc)`) plays two roles at
    once: it's the label stored in `NetworkSnapshot.captured_at`, *and* the
    `as_of` bound passed straight into `build_topology_graph` -- so a
    snapshot's claimed capture time always genuinely matches what evidence
    its graph includes, never a label decoupled from content.

    Version numbering is per-`capture_id`, sequential by *generation
    order* (via `list_snapshots`): `1` if none exist yet, else
    `max(existing versions) + 1`. This is generation order, not
    `captured_at` order -- creating snapshots out of chronological order
    is unusual but not prevented, and `version` would still reflect call
    order, not timestamp order; documented here, not silently assumed
    away. `snapshot_id = graph_id = f"{capture_id}-snapshot-{version}"` --
    a `-`-separated id, unlike `Node`/`Edge`/`Flow`'s `:`-separated
    `<capture_id>:<type>:<index>` convention, because this id is used
    directly as a filename component (`topology_path`/`snapshot_path`)
    and `:` is invalid in a Windows path.

    Every call creates a genuinely new version, even if nothing actually
    changed since the last one -- deduplicating unchanged snapshots is not
    attempted here (the spec says "generate," not "generate only on
    change"; *whether* something changed is Phase 45's job).

    Never raises for a missing/empty capture -- mirrors
    `build_topology_graph`'s own "empty graph, never an error" stance,
    producing a valid, empty-graph version-1 snapshot instead.
    """
    if captured_at is None:
        captured_at = datetime.now(timezone.utc)

    existing = list_snapshots(root, capture_id)
    version = (existing[-1].version + 1) if existing else 1
    snapshot_id = f"{capture_id}-snapshot-{version}"

    graph = build_topology_graph(
        root,
        capture_id,
        graph_id=snapshot_id,
        edge_confidence_packet_scale=edge_confidence_packet_scale,
        edge_confidence_signal_strength=edge_confidence_signal_strength,
        as_of=captured_at,
    )
    write_json(topology_path(root, capture_id, graph.graph_id), graph)

    snapshot = NetworkSnapshot(
        snapshot_id=snapshot_id,
        graph_id=graph.graph_id,
        captured_at=captured_at,
        version=version,
    )
    write_json(snapshot_path(root, capture_id, snapshot_id), snapshot)
    return snapshot
