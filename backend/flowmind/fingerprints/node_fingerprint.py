"""Node behavioral fingerprint assembly (spec Phase 35, FR-1.13).

`assemble_node_fingerprint`/`assemble_all_node_fingerprints` are a plain
field-copy layer over Phase 33-34's `NodeBehavioralFeatures`: they add
the `node_id`/`window`/`computed_at` identity `BehavioralFingerprint`
(`backend/app/models/behavior.py`, Phase 04) needs, on top of the same
six feature fields Phase 33 already deliberately name-matched for exactly
this purpose. No new feature computation happens here.

`GET /behaviors/{node_id}` (`backend/app/api/routes/behaviors.py`) is NOT
wired to this module. That route's Phase-09-fixed contract
(`NodeBehavior { fingerprint, role }`) also requires a real
`RoleClassification`, which is Phase 36-37's job -- wiring the route now
would mean fabricating a role, which this project's own "no fake
metrics/no premature completion" rules forbid. This phase is a pure,
tested assembly capability, same as every other unwired phase since 29.

Never imports `simulator.ground_truth` (spec §4;
`scripts/check_ground_truth_boundary.py` would reject it if it did).
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Dict, List, Optional

from backend.app.models.behavior import BehavioralFingerprint, ObservationWindow
from backend.app.models.flow import Flow
from backend.app.models.topology import Node
from backend.flowmind.features.windows import compute_node_features_for_window


def assemble_node_fingerprint(
    flows: List[Flow],
    node: Node,
    window: ObservationWindow,
    window_seconds: Optional[Dict[ObservationWindow, float]] = None,
    computed_at: Optional[datetime] = None,
) -> BehavioralFingerprint:
    """Computes `node`'s behavioral features for `window` (Phase 34) and
    wraps them, unmodified, into a real `BehavioralFingerprint`."""
    features = compute_node_features_for_window(flows, node, window, window_seconds)
    return BehavioralFingerprint(
        node_id=node.node_id,
        window=window,
        computed_at=computed_at or datetime.now(timezone.utc),
        **asdict(features),
    )


def assemble_all_node_fingerprints(
    flows: List[Flow],
    nodes: List[Node],
    window_seconds: Optional[Dict[ObservationWindow, float]] = None,
    computed_at: Optional[datetime] = None,
) -> List[BehavioralFingerprint]:
    """Assembles one `BehavioralFingerprint` per node per observation
    window (all three -- Phase 34's own deliverable was explicitly
    per-window results, and nothing narrows this to a single window).
    Every fingerprint from one call shares the same `computed_at` --
    real batch-generation semantics, not per-fingerprint clock skew.
    Zero nodes returns an empty list, never an error.
    """
    as_of = computed_at or datetime.now(timezone.utc)
    return [
        assemble_node_fingerprint(flows, node, window, window_seconds, as_of)
        for node in nodes
        for window in ObservationWindow
    ]
