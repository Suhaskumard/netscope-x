"""Topology Event Timeline (spec Phase 47, FR-1.22 second half: "expose a
chronological topology event timeline").

Reuses `backend/app/models/snapshot.py`'s `GraphChangeEvent`/`ChangeType`
unmodified -- its own docstring already scopes it to "spec Phase 45,
47-48", so no new schema is needed here. The building block is Phase 45's
`diff_snapshots`, a pure, two-snapshot, unpersisted comparison;
this phase's job (per `docs/architecture/graph_difference_engine.md`'s own
forward-reference: "persisting/querying a change-event history is
naturally Phase 47's job") is to chain that comparison across every
consecutive pair of a capture's own `NetworkSnapshot`s (Phase 44) and
persist the result as one flat, chronological stream.

`GET /history` (`backend/app/api/routes/history.py`) is explicitly Phase
49's route ("Backing implementation: spec Phase 49 (Historical
Investigation Engine)") and stays an untouched 501 stub -- this phase
builds the capability Phase 49 will eventually query, the same
build-now-wire-later precedent already set by Phase 35's
`fingerprints.jsonl` (unwired until Phase 36-37) and Phase 44's
`NetworkSnapshot` (unwired until this phase and Phase 45 consumed it).

Never imports `simulator.ground_truth` (spec §4;
`scripts/check_ground_truth_boundary.py` would reject it if it did).
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from backend.app.models.snapshot import GraphChangeEvent
from backend.archaeology.diff import diff_snapshots
from backend.archaeology.snapshots import list_snapshots
from experiments.artifacts.io import read_jsonl, write_jsonl
from experiments.artifacts.paths import events_path


def build_topology_event_timeline(root: Path, capture_id: str) -> List[GraphChangeEvent]:
    """Builds `capture_id`'s full chronological `GraphChangeEvent` stream by
    diffing every consecutive pair of its persisted `NetworkSnapshot`s (via
    Phase 44's `list_snapshots`, already ordered by `version` ascending --
    generation order) through Phase 45's `diff_snapshots`, unmodified, and
    concatenating the results in that same pair order.

    Deliberately chains by *generation* order, not by re-sorting on
    `captured_at`: `create_snapshot`'s own docstring already documents that
    version numbering is generation order, "not `captured_at` order" --
    creating snapshots out of chronological sequence is unusual but not
    prevented. Normal usage (snapshots created in the order they're
    captured) makes the two equivalent; out-of-order generation is an
    explicit, documented caveat here, the same style of honestly-flagged
    edge case as Phase 45's own "removals are structurally real but
    practically vacuous under normal usage" note.

    Within each consecutive pair, `diff_snapshots`'s own existing
    deterministic `(change_type, target_id, attribute_name)` ordering is
    preserved unchanged -- no new sorting logic is introduced here.

    Fewer than 2 snapshots (`0` or `1`) returns `[]` -- nothing to diff yet,
    never an error, mirroring `create_snapshot`/`list_snapshots`'s own
    "missing/insufficient means empty" convention.

    Write-through: always (re)persists the freshly computed result via
    `events_path`, the same "recompute fresh and persist every call, not a
    cache" convention Phase 32's `GET /topology` already established for
    `topology_path`.
    """
    snapshots = list_snapshots(root, capture_id)

    events: List[GraphChangeEvent] = []
    for earlier, later in zip(snapshots, snapshots[1:]):
        events.extend(diff_snapshots(root, capture_id, earlier, later))

    write_jsonl(events_path(root, capture_id), events)
    return events


def read_topology_event_timeline(root: Path, capture_id: str) -> List[GraphChangeEvent]:
    """Reads `capture_id`'s persisted topology event timeline back from
    disk. Returns `[]` for a capture with no timeline built yet -- never an
    error, mirroring `list_snapshots`'s own missing-directory convention.
    """
    path = events_path(root, capture_id)
    if not path.exists():
        return []
    return read_jsonl(path, GraphChangeEvent)
