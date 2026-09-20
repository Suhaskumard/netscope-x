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

## Lag-encoded intensity pulses (spec Phase 70)

Phase 68's own architecture doc diagnosed a real degeneracy: `causal_analysis`
scored `0.0` in every matrix cell because every declared edge's traffic
was one simultaneous jittered burst, giving Phase 52's
`estimate_temporal_precedence` (`backend/dependency/temporal_precedence.py`)
neither the per-bucket variance nor the cross-node lag it needs to detect
anything. `generate_packets_for_scenario`'s optional `pulse_*` parameters
add a second, independent traffic component engineered specifically to
give that detector genuine signal to find -- an evaluation-fixture
design, not a traffic-realism claim, exactly like this module's own
existing "minimum-viable synthesis" framing.

Mechanism: `_compute_tiers` assigns every declared node a BFS hop-distance
("tier") from a root (the first name in `roles`, matching every Phase 18
generator's own "client/hub/source first" convention), over the
**undirected** adjacency of declared edges -- robust to any topology
shape, including `redundant`'s reintroduced cycle. For each of
`pulse_cycles` cycles, one shared random intensity multiplier is drawn
and applied to *every* node's own pulse-packet count, but each node's
pulse is timestamped `tier(node) * pulse_lag_seconds` after its cycle's
start. Two nodes at tiers differing by `k` therefore carry the *same*
underlying intensity sequence, shifted by exactly `k` buckets --
precisely the lagged-correlation structure `estimate_temporal_precedence`
searches for (`pulse_lag_seconds` defaults to `10.0`, Phase 52's own
bucket width, so the lag lands exactly on a bucket boundary instead of
being partially smeared across two).

`estimate_dependency_strength` calls `estimate_temporal_precedence` with
the *discovered* `Edge`'s own `source_node_id`/`target_node_id` (assigned
by `discover_edges`'s own id-ordering, not this module's synthetic "true"
causal direction) -- so only edges where that assignment happens to agree
with a node's real lower tier being labeled "source" will score a
positive `temporal_precedence_score`. This is expected and honest: Phase
70's job is to make the score *sometimes* exceed `0.0` (previously it
never did, anywhere), not to guarantee every edge -- a partial, correctly
attributable signal is the real fix, not a perfect one.

Disabled by default (`pulse_cycles=0`) -- every existing caller/test that
doesn't ask for pulses sees byte-identical behavior to before Phase 70.

Never imports `simulator.ground_truth` (spec §4;
`scripts/check_ground_truth_boundary.py` would reject it if it did) --
this module is evaluation/experiment-only scaffolding, structurally
identical in spirit but independent in code.
"""

from __future__ import annotations

import random
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

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


def _adjacency(names: List[str], edges: List[ScenarioEdge]) -> Dict[str, List[str]]:
    adjacency: Dict[str, List[str]] = {name: [] for name in names}
    for e in edges:
        adjacency[e.source].append(e.target)
        adjacency[e.target].append(e.source)
    return {name: sorted(set(neighbors)) for name, neighbors in adjacency.items()}


def _compute_tiers(roles: Dict[str, ServiceRole], edges: List[ScenarioEdge]) -> Dict[str, int]:
    """BFS hop-distance from a root (the first declared name) over the
    undirected adjacency of `edges`. A node unreachable from the root
    (should not happen for any Phase 18 generator's own connected output)
    gets tier `0` -- an honest fallback, not a crash.
    """
    names = list(roles.keys())
    if not names:
        return {}
    root = names[0]
    adjacency = _adjacency(names, edges)

    tiers: Dict[str, int] = {root: 0}
    queue: deque = deque([root])
    while queue:
        node = queue.popleft()
        for neighbor in adjacency[node]:
            if neighbor not in tiers:
                tiers[neighbor] = tiers[node] + 1
                queue.append(neighbor)

    for name in names:
        tiers.setdefault(name, 0)
    return tiers


def _pulse_packets(
    roles: Dict[str, ServiceRole],
    edges: List[ScenarioEdge],
    ip_by_name: Dict[str, str],
    capture_id: str,
    rng: random.Random,
    counter_start: int,
    pulse_cycles: int,
    pulse_packets_per_node: int,
    pulse_intensity_range,
    pulse_lag_seconds: float,
    pulse_start_seconds: float,
) -> List[Packet]:
    tiers = _compute_tiers(roles, edges)
    adjacency = _adjacency(list(roles.keys()), edges)
    max_tier = max(tiers.values(), default=0)
    cycle_period = (max_tier + 2) * pulse_lag_seconds

    # `estimate_temporal_precedence` buckets by *flow* count (`Flow.first_seen`), not packet
    # count -- so intensity must vary the NUMBER OF DISTINCT FLOWS per bucket (a fresh
    # src_port per unit), not the packet count within one flow. Packets sharing a 5-tuple
    # reconstruct into a single flow regardless of how many there are, which would make
    # intensity invisible to the bucket-count series this detector actually reads.
    packets: List[Packet] = []
    counter = counter_start
    for cycle in range(pulse_cycles):
        intensity = rng.randint(*pulse_intensity_range)
        cycle_start = pulse_start_seconds + cycle * cycle_period
        for name in roles:
            neighbors = adjacency.get(name, [])
            if not neighbors:
                continue
            partner = neighbors[0]
            src_ip, dst_ip = ip_by_name[name], ip_by_name[partner]
            dst_port = _port_for(roles[partner])
            protocol = _protocol_for(roles[partner])
            # Deliberately NOT randomly jittered (unlike the structural baseline): every pulse
            # for a given tier must land at the exact same offset-from-start fractional
            # position as every other tier's pulse (both nominal times differ by an exact
            # multiple of `pulse_lag_seconds` == the detector's own bucket width), so the two
            # nodes' bucket indices differ by exactly `tier_diff` regardless of where the
            # bucketing `start` reference (set by the jittered structural baseline) happens to
            # fall. A few ms of random jitter here previously let one side independently tip
            # across its own bucket boundary, corrupting the intended lag -- see Phase 70.
            unit_count = pulse_packets_per_node * intensity
            for unit in range(unit_count):
                t = BASE_TIME + timedelta(
                    seconds=cycle_start + tiers[name] * pulse_lag_seconds,
                    milliseconds=unit * 2,
                )
                src_port = 30000 + rng.randint(0, 30000)  # fresh port per unit -> a distinct flow
                packets.append(
                    Packet(
                        packet_id=f"{capture_id}:pulse{counter}",
                        capture_id=capture_id,
                        timestamp=t,
                        src_ip=src_ip,
                        dst_ip=dst_ip,
                        src_port=src_port,
                        dst_port=dst_port,
                        protocol=protocol,
                        size_bytes=100 + rng.randint(0, 400),
                        direction=PacketDirection.UNKNOWN,
                    )
                )
                counter += 1
                packets.append(
                    Packet(
                        packet_id=f"{capture_id}:pulse{counter}",
                        capture_id=capture_id,
                        timestamp=t + timedelta(milliseconds=1),
                        src_ip=dst_ip,
                        dst_ip=src_ip,
                        src_port=dst_port,
                        dst_port=src_port,
                        protocol=protocol,
                        size_bytes=100 + rng.randint(0, 400),
                        direction=PacketDirection.UNKNOWN,
                    )
                )
                counter += 1
    return packets


def generate_packets_for_scenario(
    roles: Dict[str, ServiceRole],
    edges: List[ScenarioEdge],
    ip_by_name: Dict[str, str],
    capture_id: str,
    seed: int,
    packets_per_edge: int = 20,
    wave_2_edges: int = 0,
    wave_gap_seconds: float = 300.0,
    pulse_cycles: int = 0,
    pulse_packets_per_node: int = 4,
    pulse_intensity_range: "tuple[int, int]" = (1, 4),
    pulse_lag_seconds: float = 10.0,
    pulse_start_seconds: Optional[float] = None,
) -> List[Packet]:
    """`packets_per_edge` bidirectional request/response pairs per declared
    edge, jittered timestamps, deterministic per `seed`.

    `wave_2_edges` (the trailing N edges of `edges`, in the order given)
    are timestamped `wave_gap_seconds` after every other edge's traffic --
    a real, honest "topology grew" event the matrix runner uses to label
    ground truth for `temporal_analysis` evaluation, not a synthetic
    artifact bolted onto the timeline after the fact.

    `pulse_cycles > 0` additionally emits lag-encoded intensity pulses
    (spec Phase 70; see module docstring) -- disabled by default so
    existing callers see identical output to before Phase 70.
    `pulse_start_seconds` defaults to `wave_gap_seconds + 120.0`, safely
    after the structural baseline's own traffic (including any
    `wave_2_edges` growth event) so pulses never register as spurious
    topology growth.
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

    if pulse_cycles > 0:
        start = pulse_start_seconds if pulse_start_seconds is not None else wave_gap_seconds + 120.0
        packets.extend(
            _pulse_packets(
                roles,
                edges,
                ip_by_name,
                capture_id,
                rng,
                counter,
                pulse_cycles,
                pulse_packets_per_node,
                pulse_intensity_range,
                pulse_lag_seconds,
                start,
            )
        )

    return sorted(packets, key=lambda p: p.timestamp)
