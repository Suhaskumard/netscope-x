"""Multi-window behavior modeling (spec Phase 34, FR-1.12).

Decides how the three `ObservationWindow` sizes (`backend/app/models/
behavior.py`) are delimited, and invokes Phase 33's `compute_node_
behavioral_features` once per window -- Phase 33's own function is
deliberately window-agnostic; this module is where that agnosticism gets
resolved into real, concrete window boundaries.

Delimiting semantics: a TRAILING window anchored on the node's own latest
observed flow activity -- not the whole capture's latest activity, and
not calendar time. For a given node and window size, we take that node's
own touching flows (via `flows_touching_node`), find the latest
`last_seen` among them, and keep only flows within `window_seconds`
before that anchor. Anchoring per-node (rather than per-capture) means a
quiet node's window isn't dragged forward by unrelated nodes' later
traffic elsewhere in the same capture. This also makes long/medium/short
naturally NESTED (long superset of medium superset of short) rather than
mutually exclusive partitions of one fixed span -- matching RQ2's own
framing ("does *more* observation improve accuracy," an expanding-window
question, not a segmentation question).

Default durations (`DEFAULT_WINDOW_SECONDS`, mirroring `Settings`'
`behavior_window_{short,medium,long}_seconds`): 10s / 60s / 300s.
`short`/`medium` are grounded in real evidence already exercised in this
repo (`simulator/capture/live.py`'s own default capture duration; the
scale `simulator/tests/test_patterns.py` needs for burst/periodic
patterns to complete multiple cycles); `long` (300s) is an explicit
extrapolation with no direct repo evidence, documented as provisional --
see `docs/architecture/multi_window_behavior_modeling.md`.

This phase deliberately stops at a `Dict[ObservationWindow,
NodeBehavioralFeatures]` -- assembling that into a real
`BehavioralFingerprint` (with `node_id`/`window`/`computed_at` identity)
and persisting it is explicitly Phase 35's job, not reached ahead of
here.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Dict, List, Optional

from backend.app.models.behavior import ObservationWindow
from backend.app.models.flow import Flow
from backend.app.models.topology import Node
from backend.flowmind.features.node_features import (
    NodeBehavioralFeatures,
    compute_node_behavioral_features,
    flows_touching_node,
)

DEFAULT_WINDOW_SECONDS: Dict[ObservationWindow, float] = {
    ObservationWindow.SHORT: 10.0,
    ObservationWindow.MEDIUM: 60.0,
    ObservationWindow.LONG: 300.0,
}


def compute_node_features_for_window(
    flows: List[Flow],
    node: Node,
    window: ObservationWindow,
    window_seconds: Optional[Dict[ObservationWindow, float]] = None,
) -> NodeBehavioralFeatures:
    """Computes `node`'s behavioral features using only the flows within
    `window`'s trailing duration of the node's own latest observed
    activity. A node with no touching flows at all (or none within the
    window) gets the same honest all-zero `NodeBehavioralFeatures` Phase
    33 already defines for "no evidence" -- no new failure mode.
    """
    seconds = (window_seconds or DEFAULT_WINDOW_SECONDS)[window]

    touching = flows_touching_node(flows, node)
    if not touching:
        return compute_node_behavioral_features([], node)

    anchor = max(f.last_seen for f in touching)
    cutoff = anchor - timedelta(seconds=seconds)
    windowed = [f for f in touching if f.last_seen > cutoff]

    return compute_node_behavioral_features(windowed, node)


def compute_node_features_all_windows(
    flows: List[Flow],
    node: Node,
    window_seconds: Optional[Dict[ObservationWindow, float]] = None,
) -> Dict[ObservationWindow, NodeBehavioralFeatures]:
    """Computes `node`'s behavioral features over all three observation
    windows -- the spec's own "model behavior over: short, medium, long
    observation windows" (Phase 34)."""
    return {
        window: compute_node_features_for_window(flows, node, window, window_seconds)
        for window in ObservationWindow
    }
