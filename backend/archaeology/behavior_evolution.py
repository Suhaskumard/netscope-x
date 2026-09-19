"""Behavioral Evolution Tracking (spec Phase 46, FR-1.22 first half:
"track behavioral evolution per node over time").

The first Network Archaeology phase to operate on FLOWMIND's
`BehavioralFingerprint` (Phase 33-35) rather than NETTRACE's `TopologyGraph`
(Phase 43-45). Deliberately mirrors Phase 45's `diff_snapshots` shape --
a pure structural comparison producing concrete, evidenced change events
-- applied to a node's own fingerprint history instead of a topology
snapshot pair.

Not a duplicate of Phase 39's `track_node_drift`: that function classifies
a *sequence* of new values against a static baseline as `CONCEPT_DRIFT` or
`TRANSIENT_ANOMALY` -- a FLOWMIND anomaly-detection judgment. This phase
makes no statistical judgment at all; it simply records, chronologically
and pairwise, which concrete fingerprint fields actually changed between
each consecutive observation, with real before/after evidence -- a plain
historical record, not a detector. A caller wanting drift classification
on top of this record already has `track_node_drift` for that.

No Phase 04 schema is reserved for this (unlike `GraphChangeEvent`, whose
own docstring scopes it to "spec Phase 45, 47-48" -- not 46), so this
follows the Phase 38 (`NodeBehavioralBaseline`)/Phase 39
(`DriftTrackingResult`) precedent: a plain `@dataclass`, and a pure
function over a caller-supplied, time-ordered list of the SAME node's
fingerprints. No new persistent fingerprint-history store is built --
Phase 35's `fingerprints.jsonl` is overwritten per batch (not appended),
so no real cross-batch history exists on disk yet; building one is out of
scope here, same as Phase 38/39 already decided for their own history
parameters.

Never imports `simulator.ground_truth` (spec §4;
`scripts/check_ground_truth_boundary.py` would reject it if it did).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List

from backend.app.models.behavior import BehavioralFingerprint, ObservationWindow


@dataclass(frozen=True)
class BehavioralEvolutionEvent:
    """A single detected change in one node's behavioral fingerprint
    between two consecutive observations (spec Phase 46)."""

    event_id: str
    node_id: str
    window: ObservationWindow
    from_computed_at: datetime
    to_computed_at: datetime
    feature_name: str
    previous_value: str
    new_value: str
    evidence: List[str]


def _event(
    node_id: str,
    window: ObservationWindow,
    prev: BehavioralFingerprint,
    curr: BehavioralFingerprint,
    feature_name: str,
    previous_value: str,
    new_value: str,
    note: str,
) -> BehavioralEvolutionEvent:
    return BehavioralEvolutionEvent(
        event_id=f"{node_id}:{window.value}:{curr.computed_at.isoformat()}:{feature_name}",
        node_id=node_id,
        window=window,
        from_computed_at=prev.computed_at,
        to_computed_at=curr.computed_at,
        feature_name=feature_name,
        previous_value=previous_value,
        new_value=new_value,
        evidence=[
            f"node {node_id} {feature_name} changed from {previous_value} to {new_value} {note}"
        ],
    )


def _set_events(
    node_id: str,
    window: ObservationWindow,
    prev: BehavioralFingerprint,
    curr: BehavioralFingerprint,
    feature_name: str,
    previous_values: List,
    new_values: List,
) -> List[BehavioralEvolutionEvent]:
    before = set(previous_values)
    after = set(new_values)
    if before == after:
        return []

    added = sorted(after - before, key=str)
    removed = sorted(before - after, key=str)
    parts = []
    if added:
        parts.append(f"added {added}")
    if removed:
        parts.append(f"removed {removed}")
    note = "(" + ", ".join(parts) + ")"

    return [
        _event(
            node_id,
            window,
            prev,
            curr,
            feature_name,
            str(sorted(before, key=str)),
            str(sorted(after, key=str)),
            note,
        )
    ]


def _pair_events(
    node_id: str, window: ObservationWindow, prev: BehavioralFingerprint, curr: BehavioralFingerprint
) -> List[BehavioralEvolutionEvent]:
    events: List[BehavioralEvolutionEvent] = []

    events.extend(
        _set_events(node_id, window, prev, curr, "distinct_ports", prev.distinct_ports, curr.distinct_ports)
    )
    events.extend(
        _set_events(
            node_id,
            window,
            prev,
            curr,
            "distinct_protocols",
            prev.distinct_protocols,
            curr.distinct_protocols,
        )
    )

    for feature_name, previous_value, new_value in (
        ("distinct_destinations", prev.distinct_destinations, curr.distinct_destinations),
        ("mean_flow_duration_seconds", prev.mean_flow_duration_seconds, curr.mean_flow_duration_seconds),
        ("outbound_byte_ratio", prev.outbound_byte_ratio, curr.outbound_byte_ratio),
        ("total_byte_count", prev.total_byte_count, curr.total_byte_count),
        ("is_persistent_talker", prev.is_persistent_talker, curr.is_persistent_talker),
    ):
        if previous_value != new_value:
            events.append(
                _event(
                    node_id,
                    window,
                    prev,
                    curr,
                    feature_name,
                    str(previous_value),
                    str(new_value),
                    f"between {prev.computed_at.isoformat()} and {curr.computed_at.isoformat()}",
                )
            )

    return events


def track_node_behavioral_evolution(
    fingerprints: List[BehavioralFingerprint],
) -> List[BehavioralEvolutionEvent]:
    """Computes every field-level change across a single node's own
    time-ordered `BehavioralFingerprint` history (all fingerprints must
    share the same `node_id`/`window` -- a real correctness guard, the
    same spirit as Phase 38's `build_node_baseline` mixed-history guard).

    Compares each consecutive pair in the given order (the caller's own
    chronological order, the same convention Phase 39's `track_node_drift`
    already documents and relies on). A single fingerprint has nothing to
    compare against yet and returns `[]`, not an error; `[]` on empty
    input raises `ValueError` (nothing to track from no observations at
    all, mirroring every other "cannot compute from nothing" function
    already in this project).

    Returns events deterministically ordered by `(to_computed_at,
    feature_name)`.
    """
    if not fingerprints:
        raise ValueError("track_node_behavioral_evolution requires at least one fingerprint")

    node_id = fingerprints[0].node_id
    window = fingerprints[0].window
    for fp in fingerprints:
        if fp.node_id != node_id:
            raise ValueError(f"fingerprint node_id {fp.node_id!r} does not match {node_id!r}")
        if fp.window != window:
            raise ValueError(f"fingerprint window {fp.window!r} does not match {window!r}")

    events: List[BehavioralEvolutionEvent] = []
    for prev, curr in zip(fingerprints, fingerprints[1:]):
        events.extend(_pair_events(node_id, window, prev, curr))

    return sorted(events, key=lambda e: (e.to_computed_at, e.feature_name))
