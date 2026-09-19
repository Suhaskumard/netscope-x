"""Change Attribution (spec Phase 48, FR-1.23: "attribute detected changes
to observation evidence, timestamps, and affected flows/nodes, and shall
not claim a causal explanation without sufficient evidence").

Three of FR-1.23's four named items were already real by Phase 45:
`GraphChangeEvent.occurred_at` (timestamp), `affected_node_id`/
`affected_edge_id`, and `evidence` (observation evidence). The missing
piece -- affected flows -- is closed by `backend/archaeology/diff.py`'s
new `affected_flow_ids` field, populated in `diff_snapshots` itself
(extended in place, the same "extend an earlier phase's schema once a
later phase's requirement needs it" precedent Phase 40 already set for
`NodeBehavioralFeatures`/`BehavioralFingerprint`).

This module is the presentation layer, mirroring Phase 41's
`format_anomaly_report`: pure rendering over already-real data, no new
detection or inference. Its job is the second half of FR-1.23 -- "shall
not claim a causal explanation without sufficient evidence." This system
has no causal-inference mechanism at all yet (that begins at Phase 50-56,
"Dependency and causal reasoning"), so the only honest way to satisfy this
clause today is structural: every rendered report ends with a fixed,
unconditional disclaimer stating plainly that no causal explanation is
being made. There is no confidence threshold or evidence-sufficiency
check gating the disclaimer on or off, because there is no causal claim
anywhere in this system for a threshold to gate -- the disclaimer is
unconditional specifically because the alternative (a causal claim it
would need to justify) does not exist.

No API wiring -- a pure, unpersisted rendering function, mirroring Phase
41/42/45/47's own precedent. `GET /history` remains Phase 49's untouched
501 stub.

Never imports `simulator.ground_truth` (spec §4).
"""

from __future__ import annotations

from typing import List

from backend.app.models.snapshot import GraphChangeEvent

CAUSAL_DISCLAIMER = (
    "This report attributes the change to concrete observations (evidence, timestamp, "
    "affected flows/nodes) only. It is not, and does not claim to be, a causal explanation "
    "for why the underlying traffic pattern changed."
)


def format_change_attribution(event: GraphChangeEvent) -> str:
    """Renders one `GraphChangeEvent`'s full attribution: what changed, when, what
    it affected, what evidence supports it, and the mandatory non-causal disclaimer.
    """
    lines: List[str] = [
        f"Change: {event.change_type.value} ({event.event_id})",
        f"Occurred at: {event.occurred_at.isoformat()}",
    ]

    if event.affected_node_id is not None:
        lines.append(f"Affected node: {event.affected_node_id}")
    if event.affected_edge_id is not None:
        lines.append(f"Affected edge: {event.affected_edge_id}")
    if event.attribute_name is not None:
        lines.append(
            f"Attribute: {event.attribute_name}: {event.previous_value} -> {event.new_value}"
        )

    lines.append("Observation evidence:")
    lines.extend(f"  - {item}" for item in event.evidence)

    if event.affected_flow_ids:
        lines.append(f"Affected flows: {', '.join(event.affected_flow_ids)}")
    else:
        lines.append("Affected flows: none directly attributable")

    lines.append(CAUSAL_DISCLAIMER)

    return "\n".join(lines)


def format_timeline_attribution(events: List[GraphChangeEvent]) -> str:
    """Renders a full chronological event list (e.g. Phase 47's topology event
    timeline) as one report -- each event's own attribution, in order,
    separated by a blank line. Returns an empty string for an empty timeline,
    never an error.
    """
    return "\n\n".join(format_change_attribution(event) for event in events)
