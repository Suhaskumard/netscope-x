"""Digital Twin Synchronization (spec Phase 58, FR-1.31 second half: "kept
synchronized with new observations, including additions, removals,
behavior changes, and confidence changes").

An assembly phase, not new inference -- matching this project's
consistent pattern (Phase 32/45/46/47/57's own "combine/diff already-real
artifacts" shape). FR-1.31's four named signals each already have a real,
already-built source, called here rather than re-derived:

- Additions, removals, confidence changes -> Phase 45's `diff_snapshots`,
  called between the twin's own anchoring snapshot and the new one. Its
  `_edge_attribute_events` already diffs `Edge.confidence` (and
  `protocols`) on every surviving edge -- this *is* "confidence changes",
  already real, nothing new to build for it.
- Behavior changes -> Phase 46's `track_node_behavioral_evolution`,
  called once per `(node_id, window)` because it requires every
  fingerprint it's given to share one node/window (a real correctness
  guard, not relaxed here).

Rebuilds the twin via Phase 57's own `build_digital_twin` rather than
mutating the old one in place -- the same "recompute fresh from
persisted artifacts" convention `create_snapshot`/`diff_snapshots`
themselves already rely on, not a new incremental-update mechanism.

No new Pydantic schema (same precedent as Phase 57's own `DigitalTwin`),
no persistence of the result, no API route -- nothing in Phase 09's fixed
endpoint surface names a twin-sync resource.

Never imports `simulator.ground_truth` (spec §4;
`scripts/check_ground_truth_boundary.py` would reject it if it did).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from backend.app.models.behavior import BehavioralFingerprint, ObservationWindow
from backend.app.models.snapshot import GraphChangeEvent, NetworkSnapshot
from backend.archaeology.behavior_evolution import (
    BehavioralEvolutionEvent,
    track_node_behavioral_evolution,
)
from backend.archaeology.diff import diff_snapshots
from backend.dependency.strength import (
    _DEFAULT_DEPENDENCY_SIGNAL_STRENGTH,
    _DEFAULT_FREQUENCY_SCALE,
    _DEFAULT_PERSISTENCE_SCALE,
)
from backend.dependency.temporal_precedence import _DEFAULT_BUCKET_SECONDS, _DEFAULT_MAX_LAG_BUCKETS
from backend.digital_twin.twin import DigitalTwin, build_digital_twin
from backend.nettrace.topology.edges import _DEFAULT_PACKET_SCALE, _DEFAULT_SIGNAL_STRENGTH


@dataclass(frozen=True)
class TwinSyncResult:
    twin: DigitalTwin
    structural_changes: List[GraphChangeEvent]
    behavior_changes: List[BehavioralEvolutionEvent]


def _fingerprint_key(fp: BehavioralFingerprint) -> Tuple[str, ObservationWindow]:
    return (fp.node_id, fp.window)


def sync_digital_twin(
    root: Path,
    twin: DigitalTwin,
    new_snapshot: NetworkSnapshot,
    new_behavioral_fingerprints: Optional[List[BehavioralFingerprint]] = None,
    edge_confidence_packet_scale: float = _DEFAULT_PACKET_SCALE,
    edge_confidence_signal_strength: float = _DEFAULT_SIGNAL_STRENGTH,
    dependency_frequency_scale: float = _DEFAULT_FREQUENCY_SCALE,
    dependency_persistence_scale: float = _DEFAULT_PERSISTENCE_SCALE,
    dependency_signal_strength: float = _DEFAULT_DEPENDENCY_SIGNAL_STRENGTH,
    dependency_temporal_bucket_seconds: float = _DEFAULT_BUCKET_SECONDS,
    dependency_temporal_max_lag_buckets: int = _DEFAULT_MAX_LAG_BUCKETS,
) -> TwinSyncResult:
    """Advances `twin` to `new_snapshot`, returning the rebuilt twin
    alongside real, evidenced records of what changed.

    `new_behavioral_fingerprints` is caller-supplied, same convention as
    `build_digital_twin` itself (no persisted fingerprint history exists
    anywhere in this repo to auto-fetch from). A fingerprint's
    `(node_id, window)` not re-supplied this round hasn't stopped being
    the node's last-known state -- carried forward unchanged into the
    rebuilt twin, not dropped; a re-supplied one replaces its
    predecessor. Behavior-change events are only produced where *both* a
    previous and a new fingerprint exist for the same `(node_id,
    window)` -- a node observed for the first time this round has
    nothing to diff against yet (Phase 46's own "single fingerprint,
    nothing to compare" convention), not an error.
    """
    structural_changes = diff_snapshots(root, twin.capture_id, twin.snapshot, new_snapshot)

    new_fingerprints = new_behavioral_fingerprints or []
    previous_by_key: Dict[Tuple[str, ObservationWindow], BehavioralFingerprint] = {
        _fingerprint_key(fp): fp for fp in twin.behavioral_fingerprints
    }

    behavior_changes: List[BehavioralEvolutionEvent] = []
    merged_by_key: Dict[Tuple[str, ObservationWindow], BehavioralFingerprint] = dict(previous_by_key)
    for fp in new_fingerprints:
        key = _fingerprint_key(fp)
        previous = previous_by_key.get(key)
        if previous is not None:
            behavior_changes.extend(track_node_behavioral_evolution([previous, fp]))
        merged_by_key[key] = fp

    behavior_changes.sort(key=lambda e: (e.to_computed_at, e.node_id, e.feature_name))
    merged_fingerprints = [
        merged_by_key[key] for key in sorted(merged_by_key.keys(), key=lambda k: (k[0], k[1].value))
    ]

    updated_twin = build_digital_twin(
        root,
        twin.capture_id,
        new_snapshot,
        merged_fingerprints,
        edge_confidence_packet_scale=edge_confidence_packet_scale,
        edge_confidence_signal_strength=edge_confidence_signal_strength,
        dependency_frequency_scale=dependency_frequency_scale,
        dependency_persistence_scale=dependency_persistence_scale,
        dependency_signal_strength=dependency_signal_strength,
        dependency_temporal_bucket_seconds=dependency_temporal_bucket_seconds,
        dependency_temporal_max_lag_buckets=dependency_temporal_max_lag_buckets,
    )

    return TwinSyncResult(
        twin=updated_twin,
        structural_changes=structural_changes,
        behavior_changes=behavior_changes,
    )
