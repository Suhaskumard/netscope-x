"""Five-tuple flow reconstruction (spec Phase 23, FR-1.3).

Pure, host-agnostic logic, following `backend.nettrace.normalize`'s own
convention: reads the normalized `packets.jsonl` Phase 22 produced, groups
TCP/UDP packets into bidirectional five-tuple flows (spec
`docs/architecture/algorithm_selection.md` §1's selected algorithm: a
five-tuple hash table normalized to a canonical direction), and resolves
each grouped packet's `PacketDirection` -- the thing Phase 22 explicitly
left `UNKNOWN` because direction only means something relative to a flow.

Scope: only TCP and UDP are grouped into flows (FR-1.3's literal wording).
ICMP/OTHER packets are excluded and keep `direction=UNKNOWN`.

`Flow.features` is a required field, but several of its sub-fields are
explicitly later phases' jobs (FR-1.8, Phase 28): `destination_diversity`/
`port_diversity` are honestly `1` (a five-tuple flow has exactly one
destination/port pair by definition -- their real "diversity across many
flows" meaning is Phase 28's cross-flow aggregation), and `is_persistent`
has no real signal available from a single capture's flow packets, so it is
a documented, conservative `False` rather than a fabricated guess.
`tcp_state`/`fingerprinted_protocol` stay `None`, matching the model's own
"`None` means not yet determined" design (see `Flow`'s own docstring) --
those are Phase 24/26's jobs. Every other `FlowFeatures` field
(packet/byte counts, duration, mean inter-arrival, forward_byte_ratio, and
burstiness as a real coefficient-of-variation computation) is computed for
real from the packets already grouped here.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

from backend.app.models.flow import Flow, FlowFeatures
from backend.app.models.packet import Packet, PacketDirection, TransportProtocol
from experiments.artifacts.io import read_jsonl, write_jsonl
from experiments.artifacts.paths import flows_path, packets_path

_FLOW_PROTOCOLS = {TransportProtocol.TCP, TransportProtocol.UDP}

# (ip, port) pair identifying one endpoint of a five-tuple.
_Endpoint = Tuple[str, int]
_FlowKey = Tuple[_Endpoint, _Endpoint, TransportProtocol]


def _flow_key(pkt: Packet) -> _FlowKey:
    a: _Endpoint = (str(pkt.src_ip), pkt.src_port or 0)
    b: _Endpoint = (str(pkt.dst_ip), pkt.dst_port or 0)
    # Sorted so A->B and B->A packets land in the same bucket; this key is
    # only used for grouping, never for labeling the Flow's own src/dst.
    endpoints = tuple(sorted((a, b)))
    return (endpoints[0], endpoints[1], pkt.protocol)


def _compute_features(group: List[Packet], forward_bytes: int) -> FlowFeatures:
    packet_count = len(group)
    byte_count = sum(p.size_bytes for p in group)
    first_seen = group[0].timestamp
    last_seen = group[-1].timestamp
    duration_seconds = (last_seen - first_seen).total_seconds()

    inter_arrivals = [
        (group[i].timestamp - group[i - 1].timestamp).total_seconds() for i in range(1, packet_count)
    ]
    mean_inter_arrival = statistics.fmean(inter_arrivals) if inter_arrivals else 0.0
    # Coefficient of variation needs at least 2 gaps to have a meaningful
    # spread; with fewer, there is no real burstiness signal to report.
    if len(inter_arrivals) >= 2 and mean_inter_arrival > 0:
        burstiness = statistics.pstdev(inter_arrivals) / mean_inter_arrival
    else:
        burstiness = 0.0

    return FlowFeatures(
        packet_count=packet_count,
        byte_count=byte_count,
        duration_seconds=duration_seconds,
        burstiness=burstiness,
        mean_inter_arrival_seconds=mean_inter_arrival,
        forward_byte_ratio=(forward_bytes / byte_count) if byte_count else 0.0,
        # A five-tuple flow has exactly one destination and one port pair by
        # definition -- real cross-flow diversity is Phase 28's job.
        destination_diversity=1,
        port_diversity=1,
        # No cross-window recurrence signal exists within one capture's flow
        # packets; Phase 28 owns the real computation.
        is_persistent=False,
    )


def reconstruct_flows(root: Path, capture_id: str) -> List[Flow]:
    """Reads `packets_path(root, capture_id)`, groups TCP/UDP packets into
    bidirectional five-tuple flows, resolves each grouped packet's
    direction, rewrites `packets_path` with the resolved directions, and
    persists the resulting flows to `flows_path`. Returns the flow list.
    """
    packets = read_jsonl(packets_path(root, capture_id), Packet)

    groups: Dict[_FlowKey, List[Packet]] = defaultdict(list)
    passthrough: List[Packet] = []
    for pkt in packets:
        if pkt.protocol in _FLOW_PROTOCOLS:
            groups[_flow_key(pkt)].append(pkt)
        else:
            passthrough.append(pkt)

    flows: List[Flow] = []
    resolved_by_id: Dict[str, Packet] = {}

    # Deterministic ordering: flows are numbered by their first packet's
    # timestamp across the whole capture, not dict/group iteration order.
    ordered_groups = sorted(groups.values(), key=lambda g: min(p.timestamp for p in g))

    for index, group in enumerate(ordered_groups):
        group = sorted(group, key=lambda p: p.timestamp)
        canonical = group[0]
        canonical_src = (str(canonical.src_ip), canonical.src_port)
        canonical_dst = (str(canonical.dst_ip), canonical.dst_port)

        forward_bytes = 0
        for pkt in group:
            orientation = (str(pkt.src_ip), pkt.src_port) == canonical_src and (
                str(pkt.dst_ip),
                pkt.dst_port,
            ) == canonical_dst
            direction = PacketDirection.FORWARD if orientation else PacketDirection.REVERSE
            if direction == PacketDirection.FORWARD:
                forward_bytes += pkt.size_bytes
            resolved_by_id[pkt.packet_id] = pkt.model_copy(update={"direction": direction})

        flows.append(
            Flow(
                flow_id=f"{capture_id}:flow:{index}",
                capture_id=capture_id,
                src_ip=canonical.src_ip,
                dst_ip=canonical.dst_ip,
                src_port=canonical.src_port,
                dst_port=canonical.dst_port,
                protocol=canonical.protocol,
                first_seen=group[0].timestamp,
                last_seen=group[-1].timestamp,
                tcp_state=None,
                fingerprinted_protocol=None,
                features=_compute_features(group, forward_bytes),
            )
        )

    for pkt in passthrough:
        resolved_by_id[pkt.packet_id] = pkt

    # Preserve the original capture order on rewrite -- only `direction`
    # changes, never packet ordering.
    resolved_packets = [resolved_by_id[pkt.packet_id] for pkt in packets]
    write_jsonl(packets_path(root, capture_id), resolved_packets)
    write_jsonl(flows_path(root, capture_id), flows)
    return flows
