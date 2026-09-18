"""Edge discovery (spec Phase 30, FR-1.9/FR-1.10).

Infers communication relationships exclusively from a capture's already-
reconstructed flows -- never from `simulator.ground_truth`
(`scripts/check_ground_truth_boundary.py` statically forbids this module
from importing it, spec §4's ground-truth rule).

Source: `flows.jsonl`, not raw packets. `Flow` (Phase 23-28) already
carries `protocol`, `first_seen`/`last_seen`, and `features.packet_count`
-- exactly what an `Edge`'s `protocols`/`first_observed`/`last_observed`/
`evidence` need, and only flow-level aggregation provides them. This is a
deliberate asymmetry with `backend.nettrace.topology.discovery.discover_nodes`
(which reads packets directly): ICMP/OTHER traffic, excluded from flow
reconstruction by `reconstruct_flows`'s own documented scope, can produce
*nodes* but never *edges* here. See `docs/architecture/node_discovery.md`
(which already commits to this design) and `docs/architecture/edge_discovery.md`.

Node-id resolution: `discover_edges` takes the caller's own
`discover_nodes(...)` output as a parameter rather than re-deriving nodes
internally, keeping this a pure function of its inputs. A flow whose
`src_ip`/`dst_ip` doesn't resolve against the supplied `nodes` is treated
as caller-misuse and silently skipped -- never raised, consistent with
`discover_nodes`'s own "never raise on bad/missing input" philosophy. A
flow whose `src_ip == dst_ip` (self-referential) is skipped too: an `Edge`
cannot self-loop (`Edge._no_self_loop`), and self-communication isn't a
relationship between two nodes.

Edges are undirected: `source_node_id`/`target_node_id` are assigned by
sorted `node_id` (a deterministic tie-break), not a best-effort initiator
guess. When multiple flows between a pair disagree on who initiated (e.g.
separate UDP sessions, different ports), there is no single honest "true"
initiator to report at the edge level -- each flow's own `src_ip`/
`direction` still captures real per-flow initiation; it is just not
collapsed into one edge-level claim.

Confidence is a provisional, evidence-backed heuristic, not yet Phase-31-
calibrated: `confidence = 1 - exp(-total_packet_count / packet_scale)`,
where `total_packet_count` sums `Flow.features.packet_count` across every
flow aggregated into this edge. Strictly monotonic and saturating (never
reaches exactly 1.0), so "more observed evidence never lowers confidence"
holds by construction, not just via `Edge.confidence`'s `[0, 1]` range
validator. See `docs/architecture/edge_discovery.md` for the full
justification of why this single-signal formula was chosen over a
multi-signal weighted score.
"""

from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

from backend.app.models.flow import Flow
from backend.app.models.topology import Edge, Node
from experiments.artifacts.io import read_jsonl
from experiments.artifacts.paths import flows_path

_DEFAULT_PACKET_SCALE = 20.0  # mirrors Settings.edge_confidence_packet_scale's own default


def _evidence_line(flow: Flow) -> str:
    return (
        f"flow {flow.flow_id}: {flow.protocol.value} "
        f"{flow.src_ip}:{flow.src_port}->{flow.dst_ip}:{flow.dst_port}, "
        f"{flow.features.packet_count} packets, {flow.features.byte_count} bytes"
    )


def discover_edges(
    root: Path,
    capture_id: str,
    nodes: List[Node],
    edge_confidence_packet_scale: float = _DEFAULT_PACKET_SCALE,
) -> List[Edge]:
    """Reads `flows_path(root, capture_id)` and aggregates flows sharing a
    node pair into one `Edge` each. `nodes` must be (an equivalent IP
    coverage of) `discover_nodes(root, capture_id)`'s own output for the
    same capture. Returns `[]` for a missing/empty `flows.jsonl`, or a
    capture with no TCP/UDP flows (e.g. ICMP-only) -- never an error.
    """
    ip_to_node_id: Dict[str, str] = {
        str(ip): node.node_id for node in nodes for ip in node.ip_addresses
    }

    path = flows_path(root, capture_id)
    if not path.is_file():
        return []
    flows: List[Flow] = read_jsonl(path, Flow)

    buckets: Dict[Tuple[str, str], List[Flow]] = defaultdict(list)
    for flow in flows:
        src_node_id = ip_to_node_id.get(str(flow.src_ip))
        dst_node_id = ip_to_node_id.get(str(flow.dst_ip))
        if src_node_id is None or dst_node_id is None or src_node_id == dst_node_id:
            continue
        key = tuple(sorted((src_node_id, dst_node_id)))
        buckets[key].append(flow)

    aggregated = []
    for (source_node_id, target_node_id), bucket_flows in buckets.items():
        ordered_flows = sorted(bucket_flows, key=lambda f: (f.first_seen, f.flow_id))
        total_packet_count = sum(f.features.packet_count for f in bucket_flows)
        confidence = 1 - math.exp(-total_packet_count / edge_confidence_packet_scale)

        aggregated.append(
            {
                "source_node_id": source_node_id,
                "target_node_id": target_node_id,
                "confidence": confidence,
                "evidence": [_evidence_line(f) for f in ordered_flows],
                "observation_count": len(bucket_flows),
                "first_observed": min(f.first_seen for f in bucket_flows),
                "last_observed": max(f.last_seen for f in bucket_flows),
                "protocols": sorted({f.protocol.value for f in bucket_flows}),
            }
        )

    ordered = sorted(
        aggregated,
        key=lambda a: (a["first_observed"], a["source_node_id"], a["target_node_id"]),
    )

    return [
        Edge(edge_id=f"{capture_id}:edge:{index}", **fields)
        for index, fields in enumerate(ordered)
    ]
