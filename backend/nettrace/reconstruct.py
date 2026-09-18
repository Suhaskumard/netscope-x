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

UDP session modeling (spec Phase 25, FR-1.5) layers a second heuristic on
top of the five-tuple grouping: a UDP five-tuple's packets are further
split into separate *sessions* -- each becoming its own `Flow` -- wherever
the gap to the next packet (in timestamp order) exceeds a configurable
idle-timeout (`_split_udp_sessions`, `Settings.udp_session_idle_timeout_seconds`,
NFR-4: no hardcoded thresholds). This is the "timing-window" heuristic
FR-1.5 names, alongside the "endpoint, port" heuristic the five-tuple key
already provides. TCP is unaffected -- it already has a real
session-boundary signal via Phase 24's state machine, so timing-window
splitting only applies to UDP. Canonical forward/reverse orientation is
resolved per session, not per five-tuple: UDP has no persistent notion of
"initiator" across an idle gap, so each session's own first-observed
packet defines its own forward direction, consistent with Phase 23's
"first packet observed defines canonical orientation" rule applied at
session granularity. See `docs/architecture/udp_session_modeling.md`.

`Flow.features` is a required field, but several of its sub-fields are
explicitly later phases' jobs (FR-1.8, Phase 28): `destination_diversity`/
`port_diversity` are honestly `1` (a five-tuple flow has exactly one
destination/port pair by definition -- their real "diversity across many
flows" meaning is Phase 28's cross-flow aggregation), and `is_persistent`
has no real signal available from a single capture's flow packets, so it is
a documented, conservative `False` rather than a fabricated guess. Every
other `FlowFeatures` field (packet/byte counts, duration, mean
inter-arrival, forward_byte_ratio, and burstiness as a real
coefficient-of-variation computation) is computed for real from the
packets already grouped here.

`Flow.fingerprinted_protocol` (spec Phase 26, FR-1.6) is now real: a
small, explicit (transport, well-known port) -> protocol-name lookup
(`backend.nettrace.fingerprint.fingerprint_protocol`), since `Packet`
carries no payload for deep packet inspection. Anything not in that table
stays honestly `None`, never a guess -- see
`docs/architecture/protocol_fingerprinting.md`.

`Flow.tcp_state` (spec Phase 24, FR-1.4) is now real for TCP flows: a
finite state machine (`_compute_tcp_state`) walks each flow's packets in
timestamp order using their already-resolved `PacketDirection` and their
`tcp_flags`, tracking whether a SYN was ever seen, whether the three-way
handshake completed, and which direction(s) sent a FIN, to land on one of
`TCPState`'s six values. It is retransmission-safe by construction: state
is tracked with booleans, not counters, so a retransmitted SYN/FIN/RST in
a direction already observed is a structural no-op rather than a
corrupting double-transition -- see `docs/architecture/tcp_state_tracking.md`
for the full transition table and for why real mid-stream *data*
retransmission detection (which would need TCP sequence numbers) is
honestly out of scope: `Packet` carries no sequence/ack field. UDP flows
never call the helper; `tcp_state` stays `None`, also structurally
enforced by `Flow`'s own `_tcp_state_only_for_tcp` validator.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from backend.app.models.flow import Flow, FlowFeatures, TCPState
from backend.app.models.packet import Packet, PacketDirection, TransportProtocol
from backend.nettrace.fingerprint import fingerprint_protocol
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


def _compute_tcp_state(directed_group: List[Tuple[Packet, PacketDirection]]) -> Optional[TCPState]:
    """Finite state machine over a TCP flow's packets, in timestamp order,
    using each packet's already-resolved `PacketDirection` (never
    re-derived here). Retransmission-safe by construction: every signal is
    tracked with a boolean, not a counter, so a retransmitted SYN/FIN in a
    direction already observed is a structural no-op, not a corrupting
    double-transition. See `docs/architecture/tcp_state_tracking.md` for
    the full transition table and rationale.
    """
    if not directed_group:
        return None

    saw_syn = False
    established = False
    fwd_fin = False
    rev_fin = False

    for pkt, direction in directed_group:
        flags = set((pkt.tcp_flags or "").split(",")) - {""}

        if "RST" in flags:
            return TCPState.RESET

        if "SYN" in flags:
            saw_syn = True
            continue

        if "FIN" in flags:
            if direction == PacketDirection.FORWARD:
                fwd_fin = True
            else:
                rev_fin = True
            continue

        if "ACK" in flags and saw_syn and not established and not fwd_fin and not rev_fin:
            established = True  # the third handshake leg
            continue

    if not saw_syn or not established:
        # No handshake ever observed, or it never completed within the
        # capture window -- a partial session, not a fabricated guess.
        return TCPState.PARTIAL
    if fwd_fin and rev_fin:
        return TCPState.CLOSED
    if fwd_fin or rev_fin:
        return TCPState.CLOSING
    return TCPState.ESTABLISHED


def _split_udp_sessions(group: List[Packet], idle_timeout_seconds: float) -> List[List[Packet]]:
    """Splits one UDP five-tuple's packets into separate sessions wherever
    the gap to the next packet (in timestamp order) exceeds
    `idle_timeout_seconds` -- the timing-window heuristic FR-1.5 requires
    on top of the five-tuple's own endpoint/port grouping. A gap exactly
    equal to the timeout does not split (strict `>`).
    """
    ordered = sorted(group, key=lambda p: p.timestamp)
    sessions: List[List[Packet]] = [[ordered[0]]]
    for pkt in ordered[1:]:
        gap = (pkt.timestamp - sessions[-1][-1].timestamp).total_seconds()
        if gap > idle_timeout_seconds:
            sessions.append([pkt])
        else:
            sessions[-1].append(pkt)
    return sessions


def reconstruct_flows(
    root: Path,
    capture_id: str,
    udp_session_idle_timeout_seconds: float = 30.0,
) -> List[Flow]:
    """Reads `packets_path(root, capture_id)`, groups TCP/UDP packets into
    bidirectional five-tuple flows -- further split into timing-window
    sessions for UDP (spec Phase 25, FR-1.5) -- resolves each grouped
    packet's direction, rewrites `packets_path` with the resolved
    directions, and persists the resulting flows to `flows_path`. Returns
    the flow list.
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

    # Each TCP five-tuple stays one unit; each UDP five-tuple is further
    # split into timing-window sessions (Phase 25) -- one unit per session.
    units: List[List[Packet]] = []
    for key, group in groups.items():
        if key[2] == TransportProtocol.UDP:
            units.extend(_split_udp_sessions(group, udp_session_idle_timeout_seconds))
        else:
            units.append(group)

    # Deterministic ordering: flows are numbered by their first packet's
    # timestamp across the whole capture, not dict/group iteration order.
    ordered_groups = sorted(units, key=lambda g: min(p.timestamp for p in g))

    for index, group in enumerate(ordered_groups):
        group = sorted(group, key=lambda p: p.timestamp)
        canonical = group[0]
        canonical_src = (str(canonical.src_ip), canonical.src_port)
        canonical_dst = (str(canonical.dst_ip), canonical.dst_port)

        forward_bytes = 0
        directed_group: List[Tuple[Packet, PacketDirection]] = []
        for pkt in group:
            orientation = (str(pkt.src_ip), pkt.src_port) == canonical_src and (
                str(pkt.dst_ip),
                pkt.dst_port,
            ) == canonical_dst
            direction = PacketDirection.FORWARD if orientation else PacketDirection.REVERSE
            if direction == PacketDirection.FORWARD:
                forward_bytes += pkt.size_bytes
            directed_group.append((pkt, direction))
            resolved_by_id[pkt.packet_id] = pkt.model_copy(update={"direction": direction})

        tcp_state = (
            _compute_tcp_state(directed_group)
            if canonical.protocol == TransportProtocol.TCP
            else None
        )
        fingerprinted_protocol = fingerprint_protocol(
            canonical.protocol, canonical.src_port, canonical.dst_port
        )

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
                tcp_state=tcp_state,
                fingerprinted_protocol=fingerprinted_protocol,
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
