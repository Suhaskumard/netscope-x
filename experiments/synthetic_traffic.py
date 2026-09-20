"""Minimal synthetic traffic generation for a declared scenario (spec
Phase 68's matrix runner).

`simulator/traffic/generate.py` (Phase 14) requires a real, live HTTP
target -- Docker-only, and unusable in this session. There is no existing
"declared topology -> synthetic `packets.jsonl`" generator that works
outside Docker; every phase's own tests instead hand-write a handful of
literal `Packet` objects per fixture. This module generalizes that same
approach to an arbitrary Phase 18 `(roles, edges)` declaration, so the
Phase 68 matrix can drive the real pipeline (normalize -> reconstruct ->
discover -> ...) over many different generated topologies without Docker.

Deliberately simpler than the real lab traffic generator: fixed
request/response pair count per edge, jittered but not realistically
bursty timing, well-known ports chosen by the target's declared
`ServiceRole` (reusing `backend/nettrace/fingerprint.py`'s own port
table, not inventing a new one) -- a minimum-viable synthesis sufficient
to drive real topology/role/dependency inference, not a traffic-realism
claim. Deterministic and seeded (`random.Random(seed)`), matching
`sample_packets`'s own determinism convention.

Also builds the matching ground-truth `TopologyGraph` for the same
declared scenario, mirroring `simulator/ground_truth/generate.py::
build_topology_graph`'s exact pattern (`node_id=<declared name>`,
`confidence=1.0`, `evidence=["ground truth: ..."]`) but parameterized on
a Phase 18 scenario's own `(roles, edges)` instead of the fixed lab's
`SERVICE_ROLES`/`DECLARED_EDGES` module constants. IP assignment is a
simple, deterministic `10.0.<hi>.<lo>` sequence over sorted service
names -- the only requirement `topology_comparison.py`'s ip-set matching
needs is that it's stable and unique per name.

Never imports `simulator.ground_truth` (spec §4;
`scripts/check_ground_truth_boundary.py` would reject it if it did) --
this module is evaluation/experiment-only scaffolding, structurally
identical in spirit but independent in code.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Dict, List

from backend.app.models.behavior import ServiceRole
from backend.app.models.packet import Packet, PacketDirection, TransportProtocol
from backend.app.models.topology import Edge, Node, TopologyGraph
from simulator.scenarios.topologies import ScenarioEdge

_ROLE_PORT: Dict[ServiceRole, int] = {
    ServiceRole.DATABASE: 5432,
    ServiceRole.CACHE: 6379,
    ServiceRole.DNS: 53,
}
_DEFAULT_PORT = 80

BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)


def assign_ips(names: List[str]) -> Dict[str, str]:
    """Deterministic, unique IP per declared service name, sorted for
    reproducibility regardless of dict insertion order."""
    ips: Dict[str, str] = {}
    for index, name in enumerate(sorted(names)):
        hi, lo = divmod(index, 254)
        ips[name] = f"10.0.{hi}.{lo + 1}"
    return ips


def build_ground_truth_graph(
    roles: Dict[str, ServiceRole], edges: List[ScenarioEdge], ip_by_name: Dict[str, str], graph_id: str
) -> TopologyGraph:
    """The declared scenario's own topology, treated as ground truth --
    same role `simulator.ground_truth` plays for the fixed lab, generalized
    to a Phase 18-generated scenario."""
    now = datetime.now(timezone.utc)
    nodes = [
        Node(node_id=name, ip_addresses=[ip_by_name[name]], first_observed=now, last_observed=now)
        for name in roles
    ]
    graph_edges = [
        Edge(
            edge_id=f"{e.source}->{e.target}",
            source_node_id=e.source,
            target_node_id=e.target,
            confidence=1.0,
            evidence=["ground truth: declared Phase 18 scenario topology"],
            observation_count=1,
            first_observed=now,
            last_observed=now,
            protocols=e.protocols,
        )
        for e in edges
    ]
    return TopologyGraph(graph_id=graph_id, generated_at=now, nodes=nodes, edges=graph_edges)


def _port_for(role: ServiceRole) -> int:
    return _ROLE_PORT.get(role, _DEFAULT_PORT)


def _protocol_for(role: ServiceRole) -> TransportProtocol:
    return TransportProtocol.UDP if role == ServiceRole.DNS else TransportProtocol.TCP


def generate_packets_for_scenario(
    roles: Dict[str, ServiceRole],
    edges: List[ScenarioEdge],
    ip_by_name: Dict[str, str],
    capture_id: str,
    seed: int,
    packets_per_edge: int = 20,
    wave_2_edges: int = 0,
    wave_gap_seconds: float = 300.0,
) -> List[Packet]:
    """`packets_per_edge` bidirectional request/response pairs per declared
    edge, jittered timestamps, deterministic per `seed`.

    `wave_2_edges` (the trailing N edges of `edges`, in the order given)
    are timestamped `wave_gap_seconds` after every other edge's traffic --
    a real, honest "topology grew" event the matrix runner uses to label
    ground truth for `temporal_analysis` evaluation, not a synthetic
    artifact bolted onto the timeline after the fact.
    """
    rng = random.Random(seed)
    wave_2_pairs = (
        {(e.source, e.target) for e in edges[len(edges) - wave_2_edges :]} if wave_2_edges > 0 else set()
    )

    packets: List[Packet] = []
    counter = 0
    for edge in edges:
        wave_offset = (
            timedelta(seconds=wave_gap_seconds) if (edge.source, edge.target) in wave_2_pairs else timedelta()
        )
        target_port = _port_for(roles[edge.target])
        protocol = _protocol_for(roles[edge.target])
        client_port_base = 20000 + rng.randint(0, 5000)

        for i in range(packets_per_edge):
            t = BASE_TIME + wave_offset + timedelta(milliseconds=rng.randint(0, 5000) + i * 10)
            src_ip, dst_ip = ip_by_name[edge.source], ip_by_name[edge.target]
            packets.append(
                Packet(
                    packet_id=f"{capture_id}:p{counter}",
                    capture_id=capture_id,
                    timestamp=t,
                    src_ip=src_ip,
                    dst_ip=dst_ip,
                    src_port=client_port_base + i,
                    dst_port=target_port,
                    protocol=protocol,
                    size_bytes=100 + rng.randint(0, 400),
                    direction=PacketDirection.UNKNOWN,
                )
            )
            counter += 1
            packets.append(
                Packet(
                    packet_id=f"{capture_id}:p{counter}",
                    capture_id=capture_id,
                    timestamp=t + timedelta(milliseconds=1),
                    src_ip=dst_ip,
                    dst_ip=src_ip,
                    src_port=target_port,
                    dst_port=client_port_base + i,
                    protocol=protocol,
                    size_bytes=100 + rng.randint(0, 400),
                    direction=PacketDirection.UNKNOWN,
                )
            )
            counter += 1

    return sorted(packets, key=lambda p: p.timestamp)
