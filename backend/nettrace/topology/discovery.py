"""Node discovery (spec Phase 29, FR-1.9).

Infers active nodes exclusively from observed packets -- never from
`simulator.ground_truth`, which `scripts/check_ground_truth_boundary.py`
statically forbids this module from importing (spec §4's ground-truth
rule).

Algorithm: read this capture's already-normalized `packets.jsonl`
(Phase 22 output, so every packet already has a resolved `src_ip`/`dst_ip`
regardless of transport), and treat every distinct IP address seen as
either a packet's source or destination as evidence that a node exists at
that address. A node's `first_observed`/`last_observed` are the earliest
and latest timestamps, across every packet naming that address in either
role, seen anywhere in the capture -- the only two timestamps the
observations actually support.

One IP address currently becomes exactly one `Node` (`ip_addresses` is a
single-element list). This is a deliberate simplification, not an
oversight: correlating multiple observed addresses as the same physical
node (e.g. NAT, or a host with several interfaces) needs *additional*
evidence this phase doesn't yet compute (shared behavioral fingerprint,
shared MAC, etc.) -- out of scope until a later phase's requirements
actually need it. See `docs/architecture/node_discovery.md`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from backend.app.models.packet import Packet
from backend.app.models.topology import Node
from experiments.artifacts.io import read_jsonl
from experiments.artifacts.paths import packets_path


def discover_nodes(root: Path, capture_id: str) -> List[Node]:
    """Reads `packets_path(root, capture_id)` and returns one `Node` per
    distinct IP address observed as a packet source or destination.
    Returns an empty list for an empty/missing capture -- never an error.

    Nodes are ordered by `first_observed` (ties broken by address) and
    given deterministic ids (`<capture_id>:node:<index>`) so re-running
    discovery over the same packets yields the same ids, following
    `reconstruct_flows`'s own `flow_id` numbering convention.
    """
    path = packets_path(root, capture_id)
    if not path.is_file():
        return []
    packets: List[Packet] = read_jsonl(path, Packet)

    first_observed: Dict[str, object] = {}
    last_observed: Dict[str, object] = {}

    for pkt in packets:
        for ip in (str(pkt.src_ip), str(pkt.dst_ip)):
            if ip not in first_observed or pkt.timestamp < first_observed[ip]:
                first_observed[ip] = pkt.timestamp
            if ip not in last_observed or pkt.timestamp > last_observed[ip]:
                last_observed[ip] = pkt.timestamp

    ordered_ips = sorted(first_observed, key=lambda ip: (first_observed[ip], ip))

    return [
        Node(
            node_id=f"{capture_id}:node:{index}",
            ip_addresses=[ip],
            first_observed=first_observed[ip],
            last_observed=last_observed[ip],
        )
        for index, ip in enumerate(ordered_ips)
    ]
