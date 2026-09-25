"""Equivalence and speed of incremental topology reconstruction (spec Phase 85).

Equivalence is CHECKED directly: after every chunk of a streamed capture, `IncrementalTopology`'s flows, nodes and
edges are compared, by exact model equality (ids, evidence text, confidence, features -- everything but the graph's
`generated_at` wall-clock stamp), with a from-scratch batch rebuild (`reconstruct_flows` + `build_topology_graph`) of
the same prefix, written to disk the way the batch pipeline reads it.

Three arrival modes, reported separately and never merged:
  in_order   chunks are consecutive slices of the batch input, so arrival order == batch input order
  shuffled   packets are permuted within a sliding window (late arrival); the batch reference is run on the packets
             in ARRIVAL order (the same evidence, same order) -> exact equality expected
  canonical  the same shuffled arrival compared with the batch run on the TIMESTAMP-SORTED packets; only order-free
             content is compared (IP sets, edge pairs, confidence, observation counts, first/last observed)
             because ids and evidence numbering may legitimately differ on timestamp ties.
Speed is per-chunk (update + graph) vs a batch rebuild of the same prefix, measured, including where it loses.
Ground truth is not used.
"""

from __future__ import annotations

import random
import shutil
import tempfile
import time
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from statistics import fmean
from typing import Dict, List, Optional, Sequence, Tuple

from backend.app.models.flow import Flow
from backend.app.models.packet import Packet, PacketDirection, TransportProtocol
from backend.app.models.topology import TopologyGraph
from backend.nettrace.reconstruct import reconstruct_flows
from backend.nettrace.topology.graph import build_topology_graph
from backend.nettrace.topology.incremental import IncrementalTopology
from experiments.artifacts.io import write_jsonl
from experiments.artifacts.paths import packets_path
from experiments.matrix_runner import (
    TOPOLOGY_LEVELS,
    _PULSE_CYCLES,
    _PULSE_INTENSITY_RANGE,
    _PULSE_PACKETS_PER_NODE,
    _WAVE_GAP_SECONDS,
)
from experiments.observation_sampling import sample_packets
from experiments.synthetic_traffic import BASE_TIME, assign_ips, generate_packets_for_scenario

LEVELS: Tuple[str, ...] = ("small", "medium", "large", "multi_path", "multi_service", "dynamic")
COMPLETENESS: Tuple[float, ...] = (1.0, 0.5, 0.25)
SEEDS: Tuple[int, ...] = (42, 43, 44)
CAPTURE = "inc"


def scenario_packets(level: str, seed: int, packets_per_edge: int = 15) -> List[Packet]:
    roles, edges = TOPOLOGY_LEVELS[level]()
    ips = assign_ips(list(roles))
    return generate_packets_for_scenario(
        roles, edges, ips, CAPTURE, seed, packets_per_edge=packets_per_edge, wave_2_edges=max(1, len(edges) // 4),
        wave_gap_seconds=_WAVE_GAP_SECONDS, pulse_cycles=_PULSE_CYCLES,
        pulse_packets_per_node=_PULSE_PACKETS_PER_NODE, pulse_intensity_range=_PULSE_INTENSITY_RANGE,
    )


def udp_session_packets(seed: int, hosts: int = 4, repeats: int = 5, gap_seconds: float = 45.0) -> List[Packet]:
    """UDP-heavy capture: each client repeats the SAME five-tuple with idle gaps longer than the 30 s session timeout,
    so every key holds several sessions (exercises UDP splitting and `is_persistent`), plus one ICMP packet that
    creates a node but no flow."""
    rng = random.Random(seed)
    out: List[Packet] = []
    n = 0
    for h in range(hosts):
        client, server = f"10.1.0.{h + 1}", "10.1.9.1"
        for r in range(repeats):
            t = BASE_TIME + timedelta(seconds=r * gap_seconds + rng.random())
            for i in range(3):
                for src, dst, sp, dp in ((client, server, 40000 + h, 53), (server, client, 53, 40000 + h)):
                    out.append(Packet(
                        packet_id=f"{CAPTURE}:u{n}", capture_id=CAPTURE, timestamp=t + timedelta(milliseconds=i * 20 + (src == server)),
                        src_ip=src, dst_ip=dst, src_port=sp, dst_port=dp, protocol=TransportProtocol.UDP,
                        size_bytes=80 + rng.randint(0, 60), direction=PacketDirection.UNKNOWN))
                    n += 1
    out.append(Packet(packet_id=f"{CAPTURE}:icmp", capture_id=CAPTURE, timestamp=BASE_TIME + timedelta(seconds=3),
                      src_ip="10.1.5.5", dst_ip="10.1.9.1", protocol=TransportProtocol.ICMP, size_bytes=64,
                      direction=PacketDirection.UNKNOWN))
    return sorted(out, key=lambda p: p.timestamp)


def chunk_bounds(n: int, mode: str, seed: int) -> List[int]:
    """Cumulative end offsets. modes: single (every packet), ten (10 equal chunks), random (random sizes)."""
    if n == 0:
        return []
    if mode == "single":
        return list(range(1, n + 1))
    if mode == "ten":
        return sorted({max(1, round(n * (i + 1) / 10)) for i in range(10)})
    rng = random.Random(seed)
    ends, at = [], 0
    while at < n:
        at = min(n, at + rng.randint(1, max(1, n // 6)))
        ends.append(at)
    return ends


def shuffled_within_window(packets: Sequence[Packet], seed: int, window: int = 12) -> List[Packet]:
    """Late-arrival model: each packet may be delivered up to `window` positions away from its timestamp order."""
    rng = random.Random(seed)
    keyed = sorted(((i + rng.uniform(0, window), p) for i, p in enumerate(packets)), key=lambda kp: kp[0])
    return [p for _, p in keyed]


def batch_reference(packets: Sequence[Packet], scratch: Path) -> Tuple[List[Flow], TopologyGraph]:
    scratch.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(dir=scratch))
    try:
        write_jsonl(packets_path(work, CAPTURE), list(packets))
        flows = reconstruct_flows(work, CAPTURE)
        graph = build_topology_graph(work, CAPTURE, graph_id="g")
        return flows, graph
    finally:
        shutil.rmtree(work, ignore_errors=True)


def graphs_equal(a: TopologyGraph, b: TopologyGraph) -> bool:
    return a.nodes == b.nodes and a.edges == b.edges


def canonical_form(graph: TopologyGraph) -> Tuple:
    ip = {n.node_id: str(n.ip_addresses[0]) for n in graph.nodes}
    nodes = sorted((ip[n.node_id], n.first_observed, n.last_observed) for n in graph.nodes)
    edges = sorted(
        (tuple(sorted((ip[e.source_node_id], ip[e.target_node_id]))), round(e.confidence, 12), e.observation_count,
         e.first_observed, e.last_observed, tuple(e.protocols))
        for e in graph.edges
    )
    return nodes, edges


@dataclass(frozen=True)
class EquivalenceRow:
    scenario: str
    mode: str  # in_order | shuffled | canonical
    chunking: str
    checks: int  # prefixes compared
    exact_matches: int
    canonical_matches: int
    first_mismatch: Optional[int]


def check_stream(scenario: str, packets: Sequence[Packet], mode: str, chunking: str, seed: int, scratch: Path) -> EquivalenceRow:
    arrival = list(packets) if mode == "in_order" else shuffled_within_window(packets, seed)
    inc = IncrementalTopology(CAPTURE)
    exact = canon = checks = 0
    first_bad: Optional[int] = None
    at = 0
    for end in chunk_bounds(len(arrival), chunking, seed):
        inc.ingest(arrival[at:end])
        at = end
        prefix = arrival[:end]
        checks += 1
        g = inc.graph("g")
        if mode == "canonical":
            ref_flows, ref_graph = batch_reference(sorted(prefix, key=lambda p: p.timestamp), scratch)
            ok_exact = False
            ok_canon = canonical_form(g) == canonical_form(ref_graph)
        else:
            ref_flows, ref_graph = batch_reference(prefix, scratch)
            ok_exact = inc.flows() == ref_flows and graphs_equal(g, ref_graph)
            ok_canon = ok_exact or canonical_form(g) == canonical_form(ref_graph)
        exact += ok_exact
        canon += ok_canon
        if not (ok_exact or (mode == "canonical" and ok_canon)) and first_bad is None:
            first_bad = end
    return EquivalenceRow(scenario, mode, chunking, checks, exact, canon, first_bad)


def run_equivalence(root: Path, levels: Sequence[str] = LEVELS, completeness: Sequence[float] = COMPLETENESS,
                    seeds: Sequence[int] = SEEDS, chunkings: Sequence[str] = ("ten", "random"),
                    include_single: bool = True) -> List[EquivalenceRow]:
    scratch = root / "incremental_scratch"
    rows: List[EquivalenceRow] = []
    for level in levels:
        for c in completeness:
            for seed in seeds:
                pk = sample_packets(scenario_packets(level, seed), c, seed)
                name = f"{level}@{c:g}/s{seed}"
                for chunking in chunkings:
                    for mode in ("in_order", "shuffled", "canonical"):
                        rows.append(check_stream(name, pk, mode, chunking, seed, scratch))
    for seed in seeds:
        pk = udp_session_packets(seed)
        for chunking in (*chunkings, *(("single",) if include_single else ())):
            for mode in ("in_order", "shuffled", "canonical"):
                rows.append(check_stream(f"udp_sessions/s{seed}", pk, mode, chunking, seed, scratch))
    if include_single:  # every-packet granularity on the smallest real cells
        for seed in seeds:
            pk = sample_packets(scenario_packets("small", seed), 1.0, seed)
            rows.append(check_stream(f"small@1/s{seed}", pk, "in_order", "single", seed, scratch))
    return rows


@dataclass(frozen=True)
class SpeedRow:
    scenario: str
    packets: int
    chunks: int
    incremental_ms: float  # mean per-chunk ingest + graph
    batch_ms: float  # mean per-chunk batch rebuild of the same prefix
    speedup: float
    final_incremental_ms: float
    final_batch_ms: float


def run_speed(root: Path, levels: Sequence[str] = ("small", "multi_service"),
              packets_per_edge: Sequence[int] = (15, 200), chunks: int = 20, seed: int = 42) -> List[SpeedRow]:
    scratch = root / "incremental_scratch"
    rows: List[SpeedRow] = []
    for level in levels:
        for ppe in packets_per_edge:
            pk = scenario_packets(level, seed, ppe)
            ends = chunk_bounds(len(pk), "ten", seed)
            ends = sorted({max(1, round(len(pk) * (i + 1) / chunks)) for i in range(chunks)})
            inc = IncrementalTopology(CAPTURE)
            inc_t: List[float] = []
            batch_t: List[float] = []
            at = 0
            for end in ends:
                t = time.perf_counter()
                inc.ingest(pk[at:end])
                inc.graph("g")
                inc_t.append((time.perf_counter() - t) * 1000)
                t = time.perf_counter()
                batch_reference(pk[:end], scratch)
                batch_t.append((time.perf_counter() - t) * 1000)
                at = end
            rows.append(SpeedRow(f"{level}, {ppe} pkts/edge", len(pk), len(ends), fmean(inc_t), fmean(batch_t),
                                 fmean(batch_t) / fmean(inc_t), inc_t[-1], batch_t[-1]))
    return rows


def format_equivalence(rows: Sequence[EquivalenceRow]) -> str:
    lines = ["| mode | streams | prefixes compared | exact matches | canonical matches | streams with a mismatch |",
             "|---|---|---|---|---|---|"]
    for mode in ("in_order", "shuffled", "canonical"):
        rs = [r for r in rows if r.mode == mode]
        if not rs:
            continue
        bad = sum(1 for r in rs if r.first_mismatch is not None)
        lines.append(f"| {mode} | {len(rs)} | {sum(r.checks for r in rs)} | {sum(r.exact_matches for r in rs)} | "
                     f"{sum(r.canonical_matches for r in rs)} | {bad} |")
    mism = [r for r in rows if r.first_mismatch is not None]
    if mism:
        lines += ["", "mismatching streams (first mismatching prefix length):"]
        lines += [f"- {r.scenario} {r.mode} {r.chunking}: prefix {r.first_mismatch}" for r in mism[:20]]
    return "\n".join(lines)


def format_speed(rows: Sequence[SpeedRow]) -> str:
    lines = ["| capture | packets | chunks | incremental ms/chunk | batch ms/chunk | speedup | final chunk inc / batch ms |",
             "|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r.scenario} | {r.packets} | {r.chunks} | {r.incremental_ms:.1f} | {r.batch_ms:.1f} | "
                     f"{r.speedup:.2f}x | {r.final_incremental_ms:.1f} / {r.final_batch_ms:.1f} |")
    return "\n".join(lines)
