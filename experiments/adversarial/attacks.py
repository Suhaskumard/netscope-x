"""Crafted-traffic attacks against topology inference, role classification and anomaly detection (spec Phase 84).

Every attack is a pure function over `Packet`s (inputs are never mutated; packets are frozen) so it runs through
the real, unmodified pipeline exactly like a Phase 68 / Phase 76 cell. Each attack states the capability it
assumes: *forged* traffic needs only the ability to inject packets; *compromised-host* traffic (a real two-way
conversation) needs control of an actual node. Deterministic per `seed`. Ground truth is never read here.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import timedelta
from typing import Dict, List, Optional, Sequence, Tuple

from backend.app.models.behavior import ServiceRole
from backend.app.models.packet import Packet, PacketDirection, TransportProtocol
from experiments.anomaly_injection import BASELINE_EPOCHS, EPOCH_SECONDS, TEST_EPOCHS, VOLUME_JITTER, _shift
from experiments.synthetic_traffic import BASE_TIME, _port_for, _protocol_for, generate_packets_for_scenario
from simulator.scenarios.topologies import ScenarioEdge

FAKE_IP_PREFIX = "10.99.0."


@dataclass(frozen=True)
class Attack:
    name: str
    stage: str  # topology | role | anomaly
    capability: str  # "forged" (inject packets) | "compromised host" (controls a real node)


ATTACKS: Tuple[Attack, ...] = (
    Attack("spoofed_sources", "topology", "forged"),
    Attack("decoy_chatter", "topology", "compromised host"),
    Attack("ip_aliasing", "topology", "compromised host"),
    Attack("role_mimicry", "role", "compromised host"),
    Attack("fingerprint_noise", "role", "compromised host"),
    Attack("low_and_slow", "anomaly", "compromised host"),
    Attack("baseline_poisoning", "anomaly", "compromised host"),
    Attack("minimal_burst", "anomaly", "compromised host"),
)


def _pkt(tag: str, i: int, t, src: str, dst: str, sport: int, dport: int, proto: TransportProtocol, size: int) -> Packet:
    return Packet(
        packet_id=f"adv:{tag}:p{i}", capture_id="adv", timestamp=t, src_ip=src, dst_ip=dst, src_port=sport,
        dst_port=dport, protocol=proto, size_bytes=size, direction=PacketDirection.UNKNOWN,
    )


def _sorted(packets: Sequence[Packet]) -> List[Packet]:
    return sorted(packets, key=lambda p: p.timestamp)


def _late(packets: Sequence[Packet]):
    """A start time inside the trailing window role fingerprints are computed over (`windows.py` anchors each
    node's window on its own LATEST activity, so an attacker who wants to move its fingerprint acts last)."""
    return max((p.timestamp for p in packets), default=BASE_TIME) - timedelta(seconds=10)


def _conversation(tag: str, start: int, rng: random.Random, a: str, b: str, port: int, proto: TransportProtocol,
                  count: int, base_client_port: int = 30000, t0=None) -> List[Packet]:
    """`count` request/response pairs a -> b, sized and jittered like the honest generator's traffic."""
    out: List[Packet] = []
    for i in range(count):
        t = (t0 or BASE_TIME) + timedelta(milliseconds=rng.randint(0, 5000) + i * 10)
        cport = base_client_port + i
        out.append(_pkt(tag, start + 2 * i, t, a, b, cport, port, proto, 100 + rng.randint(0, 400)))
        out.append(_pkt(tag, start + 2 * i + 1, t + timedelta(milliseconds=1), b, a, port, cport, proto,
                        100 + rng.randint(0, 400)))
    return out


# ---------------------------------------------------------------- topology inference
def spoofed_sources(packets: Sequence[Packet], real_ips: Sequence[str], seed: int, n_fake: int = 5,
                    per_source: int = 25) -> List[Packet]:
    """Forged one-way packets from `n_fake` unused IPs to real nodes. Phantom NODES, and phantom edges to real ones.
    Capability: packet injection only (no replies can be forged without seeing the victim's traffic)."""
    rng = random.Random(seed * 31 + 1)
    extra: List[Packet] = []
    n = 0
    for k in range(n_fake):
        fake = f"{FAKE_IP_PREFIX}{k + 1}"
        for _ in range(per_source):
            dst = rng.choice(list(real_ips))
            t = BASE_TIME + timedelta(milliseconds=rng.randint(0, 5000))
            extra.append(_pkt("spoof", n, t, fake, dst, 40000 + rng.randint(0, 999), 443, TransportProtocol.TCP,
                              100 + rng.randint(0, 400)))
            n += 1
    return _sorted([*packets, *extra])


def decoy_chatter(packets: Sequence[Packet], ip_by_name: Dict[str, str], declared: Sequence[ScenarioEdge], seed: int,
                  n_pairs: int = 3, per_pair: int = 40) -> List[Packet]:
    """Full two-way conversations between real node pairs that have NO declared edge (needs control of both
    endpoints or a tap). Phantom EDGES between real nodes."""
    rng = random.Random(seed * 31 + 2)
    linked = {frozenset((e.source, e.target)) for e in declared}
    names = sorted(ip_by_name)
    free = [(a, b) for i, a in enumerate(names) for b in names[i + 1:] if frozenset((a, b)) not in linked]
    rng.shuffle(free)
    extra: List[Packet] = []
    for j, (a, b) in enumerate(free[:n_pairs]):
        extra += _conversation(f"decoy{j}", len(extra), rng, ip_by_name[a], ip_by_name[b], 8080, TransportProtocol.TCP,
                               per_pair)
    return _sorted([*packets, *extra])


def ip_aliasing(packets: Sequence[Packet], victim_ip: str, seed: int, n_aliases: int = 3) -> List[Packet]:
    """One real node's traffic is re-sourced round-robin across `n_aliases` fresh IPs (both directions kept
    consistent per flow). One NODE appears as several. Capability: control of the victim host's addressing."""
    alias = [f"{FAKE_IP_PREFIX}{200 + k}" for k in range(n_aliases)]
    out: List[Packet] = []
    for p in packets:
        src, dst = str(p.src_ip), str(p.dst_ip)
        key = (p.dst_port if src == victim_ip else p.src_port) or 0
        if src == victim_ip:
            out.append(p.model_copy(update={"src_ip": alias[key % n_aliases]}))
        elif dst == victim_ip:
            out.append(p.model_copy(update={"dst_ip": alias[key % n_aliases]}))
        else:
            out.append(p)
    return out


# ---------------------------------------------------------------- role classification
def role_mimicry(packets: Sequence[Packet], attacker_ip: str, peers: Sequence[str], mimic_role: ServiceRole,
                 seed: int, per_peer: int = 25) -> List[Packet]:
    """The attacker starts SERVING `mimic_role`'s well-known port to every peer with real two-way traffic, so its
    port and fan-in profile resembles that role's."""
    rng = random.Random(seed * 31 + 3)
    port, proto = _port_for(mimic_role), _protocol_for(mimic_role)
    t0 = _late(packets)
    extra: List[Packet] = []
    for peer in peers:
        if peer != attacker_ip:
            extra += _conversation("mimic", len(extra), rng, peer, attacker_ip, port, proto, per_peer, t0=t0)
    return _sorted([*packets, *extra])


def fingerprint_noise(packets: Sequence[Packet], attacker_ip: str, real_ips: Sequence[str], seed: int,
                      n_packets: int = 120) -> List[Packet]:
    """The attacker sprays small one-way packets at many peers on random ports, inflating its destination and
    port counts and distorting its byte ratio."""
    rng = random.Random(seed * 31 + 4)
    peers = [ip for ip in real_ips if ip != attacker_ip]
    t0 = _late(packets)
    extra = [
        _pkt("noise", i, t0 + timedelta(milliseconds=rng.randint(0, 5000)), attacker_ip, rng.choice(peers),
             30000 + rng.randint(0, 999), rng.randint(1024, 65000), TransportProtocol.TCP, 60 + rng.randint(0, 40))
        for i in range(n_packets)
    ]
    return _sorted([*packets, *extra])


# ---------------------------------------------------------------- anomaly detection
@dataclass
class AttackDataset:
    """An epoch timeline (Phase 76's layout) plus the labeled (node name, dimension) deviations that were genuinely
    injected. `label_epoch` is when the deviation first exists at full strength."""

    packets: List[Packet]
    actor: str
    label_pairs: List[Tuple[str, str]]  # (node name, AnomalyDimension value)
    label_epoch: int
    epoch_seconds: float = EPOCH_SECONDS
    baseline_epochs: int = BASELINE_EPOCHS
    test_epochs: int = TEST_EPOCHS

    @property
    def total_epochs(self) -> int:
        return self.baseline_epochs + self.test_epochs

    def epoch_start(self, epoch: int):
        return BASE_TIME + timedelta(seconds=epoch * self.epoch_seconds)

    def epoch_end(self, epoch: int):
        return self.epoch_start(epoch + 1)


def normal_epochs(roles, edges, ip_by_name, capture_id: str, seed: int, packets_per_edge: int = 15) -> List[Packet]:
    """Phase 76's clean timeline (same per-epoch generator, seeds and volume jitter), no injected anomaly."""
    rng = random.Random(seed * 7919 + 76)
    packets: List[Packet] = []
    for epoch in range(BASELINE_EPOCHS + TEST_EPOCHS):
        ppe = max(1, packets_per_edge + rng.randint(-VOLUME_JITTER, VOLUME_JITTER))
        normal = generate_packets_for_scenario(roles, edges, ip_by_name, capture_id, seed=seed * 1009 + epoch,
                                               packets_per_edge=ppe)
        packets.extend(_shift(normal, epoch, capture_id, "n", EPOCH_SECONDS))
    return packets


def _extra_volume(roles, out_edges, ip_by_name, capture_id, seed, epoch, factor: float, packets_per_edge: int, tag: str):
    per_edge = int(round(factor * packets_per_edge))
    if per_edge <= 0:
        return []
    extra = generate_packets_for_scenario(roles, out_edges, ip_by_name, capture_id, seed=seed * 2003 + epoch,
                                          packets_per_edge=per_edge)
    return _shift(extra, epoch, capture_id, tag, EPOCH_SECONDS)


def pick_actor(edges: Sequence[ScenarioEdge]) -> Optional[str]:
    sources = sorted({e.source for e in edges})
    return sources[0] if sources else None


def volume_dataset(roles, edges, ip_by_name, capture_id: str, seed: int, attack: str, spike_factor: float = 4.0,
                   packets_per_edge: int = 15) -> Optional[AttackDataset]:
    """`attack` in {"clean", "low_and_slow", "baseline_poisoning"}: the same actor and labels, different delivery.
      clean:              one full spike (`spike_factor` x its normal volume) in the first test epoch.
      low_and_slow:       the spike is ramped linearly across all test epochs to `spike_factor` in the last.
      baseline_poisoning: the same single spike, but the actor's volume was already ramped up during the baseline
                          epochs (to `spike_factor` at the last baseline epoch), widening its own baseline.
    """
    actor = pick_actor(edges)
    if actor is None:
        return None
    out_edges = [e for e in edges if e.source == actor]
    touched = [actor] + sorted({e.target for e in out_edges})
    packets = normal_epochs(roles, edges, ip_by_name, capture_id, seed, packets_per_edge)
    first_test = BASELINE_EPOCHS

    def add(epoch: int, factor: float, tag: str) -> None:
        packets.extend(_extra_volume(roles, out_edges, ip_by_name, capture_id, seed, epoch, factor, packets_per_edge,
                                     tag))

    if attack in ("clean", "baseline_poisoning"):
        add(first_test + 1, spike_factor, "x")
        label_epoch = first_test + 1
    elif attack == "low_and_slow":
        for k in range(TEST_EPOCHS):
            add(first_test + k, spike_factor * (k + 1) / TEST_EPOCHS, "s")
        label_epoch = first_test  # the deviation starts with the ramp
    else:
        raise ValueError(f"unknown volume attack {attack!r}")
    if attack == "baseline_poisoning":
        for e in range(BASELINE_EPOCHS):
            add(e, spike_factor * e / max(1, BASELINE_EPOCHS - 1), "p")
    packets.sort(key=lambda p: p.timestamp)
    return AttackDataset(packets, actor, [(n, "traffic_volume") for n in touched], label_epoch)


def burst_dataset(roles, edges, ip_by_name, capture_id: str, seed: int, attack: str,
                  packets_per_edge: int = 15) -> Optional[AttackDataset]:
    """`attack` in {"clean", "minimal_burst"}: the actor contacts nodes it has no edge with, in the second test
    epoch. clean = 3 new peers x `packets_per_edge` pairs (Phase 76's pattern); minimal_burst = ONE new peer, 2
    request/response pairs -- the smallest departure that is still a new destination."""
    names = sorted(roles)
    neighbours: Dict[str, set] = {}
    for e in edges:
        neighbours.setdefault(e.source, set()).add(e.target)
        neighbours.setdefault(e.target, set()).add(e.source)
    options = {n: sorted(set(names) - neighbours.get(n, set()) - {n}) for n in names}
    candidates = [n for n in names if options[n]]
    if not candidates:
        return None
    actor = candidates[0]
    n_peers, per_edge = (3, packets_per_edge) if attack == "clean" else (1, 2)
    if attack not in ("clean", "minimal_burst"):
        raise ValueError(f"unknown burst attack {attack!r}")
    peers = options[actor][:n_peers]
    packets = normal_epochs(roles, edges, ip_by_name, capture_id, seed, packets_per_edge)
    epoch = BASELINE_EPOCHS + 2
    extra_edges = [ScenarioEdge(source=actor, target=p, protocols=["tcp"]) for p in peers]
    extra = generate_packets_for_scenario(roles, extra_edges, ip_by_name, capture_id, seed=seed * 2003 + epoch,
                                          packets_per_edge=per_edge)
    packets.extend(_shift(extra, epoch, capture_id, "x", EPOCH_SECONDS))
    packets.sort(key=lambda p: p.timestamp)
    return AttackDataset(packets, actor, [(actor, "destinations")], epoch)
