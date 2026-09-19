"""Reusable behavioral feature computation (spec Phase 33, FR-1.12).

`compute_node_behavioral_features(flows, node)` computes a real,
evidence-derived feature vector for one node from a caller-supplied list
of `Flow` objects -- exactly the feature vocabulary
`docs/architecture/algorithm_selection.md` §2 already commits to as the
input to a future Naive-Bayes-style role classifier (Phase 36-37): port
set entropy, protocol mix, traffic directionality, persistence, and
destination diversity.

Deliberately window-agnostic: this function filters only by "does this
flow touch this node's IPs," never by time. The caller decides which
flows to pass in -- the whole capture's flows, or a subset already
filtered to some time window. This is what makes the function reusable
across Phase 34's three observation-window sizes without modification;
Phase 34 owns deciding what those windows are and invoking this function
once per window, and Phase 35 owns assembling the result into a real
`BehavioralFingerprint` (this phase's output is deliberately NOT that
schema -- see `NodeBehavioralFeatures` below).

Never imports `simulator.ground_truth` (spec §4;
`scripts/check_ground_truth_boundary.py` would reject it if it did).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from backend.app.models.flow import Flow
from backend.app.models.topology import Node


@dataclass(frozen=True)
class NodeBehavioralFeatures:
    """One node's computed behavioral feature vector over a caller-supplied
    set of flows. Field names deliberately match `BehavioralFingerprint`'s
    own feature fields (`backend/app/models/behavior.py`) so a future phase
    can assemble one from this by a plain field copy, not a translation --
    this is NOT that schema itself, since it lacks the `node_id`/`window`/
    `computed_at` identity fields Phase 34-35 are responsible for."""

    distinct_ports: List[int]
    distinct_protocols: List[str]
    distinct_destinations: int
    mean_flow_duration_seconds: float
    outbound_byte_ratio: float
    is_persistent_talker: bool
    # Total bytes across every touching flow (spec Phase 40's "traffic
    # volume" dimension). Defaulted so existing callers/fixtures that never
    # cared about volume don't need updating -- computed for real by
    # compute_node_behavioral_features whenever flows are present.
    total_byte_count: int = 0


def flows_touching_node(flows: List[Flow], node: Node) -> List[Flow]:
    """Returns every flow in `flows` whose `src_ip`/`dst_ip` matches one of
    `node.ip_addresses`. Extracted so Phase 34's window-filtering code can
    reuse the exact same node-membership test this function already uses
    internally, rather than duplicating it."""
    node_ips = {str(ip) for ip in node.ip_addresses}
    return [f for f in flows if str(f.src_ip) in node_ips or str(f.dst_ip) in node_ips]


def compute_node_behavioral_features(flows: List[Flow], node: Node) -> NodeBehavioralFeatures:
    """Computes `node`'s behavioral features from every flow in `flows`
    that touches one of `node.ip_addresses`, either as source or
    destination. Flows touching neither are ignored. A node with no
    touching flows gets the honest "no evidence" zero value on every
    field -- never a fabricated default, never an error.
    """
    node_ips = {str(ip) for ip in node.ip_addresses}

    touching = flows_touching_node(flows, node)

    if not touching:
        return NodeBehavioralFeatures(
            distinct_ports=[],
            distinct_protocols=[],
            distinct_destinations=0,
            mean_flow_duration_seconds=0.0,
            outbound_byte_ratio=0.0,
            is_persistent_talker=False,
        )

    # "Listening" ports: dst_port on flows where this node IS the destination --
    # a server's own small, stable port set is real role signal; a client's
    # ephemeral source ports would only dilute it (see architecture doc).
    listening_ports = {
        f.dst_port for f in touching if str(f.dst_ip) in node_ips and f.dst_port is not None
    }

    protocols = {f.protocol.value for f in touching}

    # Outbound fan-out: distinct destinations this node, as source, reaches.
    destinations = {str(f.dst_ip) for f in touching if str(f.src_ip) in node_ips}

    mean_duration = sum(f.features.duration_seconds for f in touching) / len(touching)

    sent_bytes = 0.0
    total_bytes = 0.0
    for f in touching:
        byte_count = f.features.byte_count
        total_bytes += byte_count
        if str(f.src_ip) in node_ips:
            sent_bytes += byte_count * f.features.forward_byte_ratio
        else:
            sent_bytes += byte_count * (1 - f.features.forward_byte_ratio)
    outbound_ratio = (sent_bytes / total_bytes) if total_bytes else 0.0

    is_persistent = any(f.features.is_persistent for f in touching)

    return NodeBehavioralFeatures(
        distinct_ports=sorted(listening_ports),
        distinct_protocols=sorted(protocols),
        distinct_destinations=len(destinations),
        mean_flow_duration_seconds=mean_duration,
        outbound_byte_ratio=outbound_ratio,
        is_persistent_talker=is_persistent,
        total_byte_count=int(total_bytes),
    )
