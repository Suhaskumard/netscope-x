"""Multi-collector fusion, conflict resolution and its failure cases, measured (spec addendum Phase 90).

Collectors are simulated from real matrix-runner scenario traffic (`scenario_packets`), so what each one "sees" is a
known subset of one true capture and every fused result can be checked against the single full capture and against
the declared topology (evaluation code only; the backend never sees ground truth).

Parts
  equivalence  union of collectors == the full capture (overlap 0.5, N = 2..4, in-order and interleaved arrival, zero skew
               and skew inside the tolerance (pairwise <= 0.0006 s vs 0.001 s)): fused edges/confidences vs the full-capture graph, checked directly.
  quality      lossy union (each packet lost with p in {0, 0.3, 0.8}, then seen by one collector plus others with p=0.3): edge F1 vs
               ground truth for best single collector / pooled / naive concatenation (no dedupe) / quorum, and
               confidence error vs the full-capture graph for pooled / naive / union-max / mean of collector confidences.
  conflicts    counts of real disagreements per kind in those lossy runs; every fused edge must have a Resolution.
  failures     skew beyond tolerance; tolerance wide enough to merge genuine repeats; a fabricated-edge collector with
               N=3 (quorum can arbitrate) and N=2 (tie); direction-split collectors (asymmetric views).
  cost         ingest seconds, fused N collectors vs a single collector fed the same union.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from datetime import timedelta
from statistics import fmean
from typing import Dict, FrozenSet, List, Optional, Sequence, Tuple

from backend.app.models.packet import Packet, PacketDirection, TransportProtocol
from backend.app.models.topology import TopologyGraph
from backend.nettrace.collectors.multi import MultiCollectorPipeline
from backend.nettrace.topology.incremental import IncrementalTopology
from experiments.incremental_topology_benchmark import CAPTURE, scenario_packets, shuffled_within_window
from experiments.matrix_runner import TOPOLOGY_LEVELS
from experiments.metrics.topology_comparison import compare_topology_to_ground_truth
from experiments.synthetic_traffic import assign_ips, build_ground_truth_graph

LEVELS: Tuple[str, ...] = ("small", "multi_service", "large", "multi_path")
SEEDS: Tuple[int, ...] = (42, 43)
TOL = 0.001
Pair = FrozenSet[str]


# ------------------------------------------------------------------ simulation
def make_views(
    packets: Sequence[Packet], n: int, overlap: float, seed: int, drop: float = 0.0, skew_s: Sequence[float] = ()
) -> List[List[Packet]]:
    """Each surviving packet is seen by one primary collector plus each other collector with probability `overlap`;
    collector i's clock is offset by skew_s[i]. Order within a collector stays timestamp order."""
    rng = random.Random(seed)
    views: List[List[Packet]] = [[] for _ in range(n)]
    for p in packets:
        if drop and rng.random() < drop:
            continue
        primary = rng.randrange(n)
        for i in range(n):
            if i == primary or rng.random() < overlap:
                off = skew_s[i] if i < len(skew_s) else 0.0
                views[i].append(p if not off else p.model_copy(update={"timestamp": p.timestamp + timedelta(seconds=off)}))
    return views


def direction_split_views(packets: Sequence[Packet]) -> List[List[Packet]]:
    """Two collectors on an asymmetric path: one sees only packets with src ip < dst ip, the other the rest."""
    a = [p for p in packets if str(p.src_ip) < str(p.dst_ip)]
    b = [p for p in packets if str(p.src_ip) >= str(p.dst_ip)]
    return [a, b]


def fabricate(packets: Sequence[Packet], ips: Dict[str, str], true_pairs: set, seed: int, per_edge: int = 12) -> List[Packet]:
    """A faulty collector's invented traffic: bidirectional TCP between IP pairs that have no true edge."""
    rng = random.Random(seed)
    values = sorted(ips.values())
    fake = [(a, b) for i, a in enumerate(values) for b in values[i + 1:] if frozenset({a, b}) not in true_pairs]
    if not fake:
        return []
    picked = rng.sample(fake, min(3, len(fake)))
    t0, t1 = packets[0].timestamp, packets[-1].timestamp
    span = max(1.0, (t1 - t0).total_seconds())
    out: List[Packet] = []
    for k, (a, b) in enumerate(picked):
        for j in range(per_edge):
            t = t0 + timedelta(seconds=span * (j + 1) / (per_edge + 1))
            for src, dst, sp, dp in ((a, b, 40000 + k, 443), (b, a, 443, 40000 + k)):
                out.append(Packet(
                    packet_id=f"fab-{k}-{j}-{src}", capture_id=CAPTURE, timestamp=t, src_ip=src, dst_ip=dst,
                    src_port=sp, dst_port=dp, protocol=TransportProtocol.TCP, size_bytes=120,
                    direction=PacketDirection.UNKNOWN,
                ))
    return sorted(out, key=lambda p: p.timestamp)



def segment_views(packets: Sequence[Packet], n: int) -> List[List[Packet]]:
    """Collectors on different network segments: each sees only the links (unordered IP pair) hashed to it, so every
    edge is visible from exactly one vantage point while endpoints are seen by others through their other links."""
    views: List[List[Packet]] = [[] for _ in range(n)]
    for p in packets:
        a, b = sorted((str(p.src_ip), str(p.dst_ip)))
        views[sum(map(ord, a + b)) % n].append(p)
    return views


def keepalive_packets(seconds: int = 60, gap: float = 0.5) -> List[Packet]:
    """A genuine repeating stream: identical packets every `gap` s, alternately seen by two collectors."""
    base = scenario_packets("small", 42)[0].timestamp
    out = []
    for i in range(int(seconds / gap)):
        out.append(Packet(
            packet_id=f"ka-{i}", capture_id=CAPTURE, timestamp=base + timedelta(seconds=i * gap),
            src_ip="10.9.0.1", dst_ip="10.9.0.2", src_port=5000, dst_port=5001, protocol=TransportProtocol.UDP,
            size_bytes=64, direction=PacketDirection.UNKNOWN,
        ))
    return out

# ------------------------------------------------------------------ helpers
def _ips(graph: TopologyGraph) -> Dict[str, str]:
    return {n.node_id: str(n.ip_addresses[0]) for n in graph.nodes}


def edge_conf(graph: TopologyGraph) -> Dict[Pair, float]:
    ip = _ips(graph)
    return {frozenset({ip[e.source_node_id], ip[e.target_node_id]}): e.confidence for e in graph.edges}


def full_graph(packets: Sequence[Packet]) -> TopologyGraph:
    inc = IncrementalTopology(CAPTURE)
    inc.ingest(list(packets))
    return inc.graph(CAPTURE)


def truth_graph(level: str) -> Tuple[TopologyGraph, Dict[str, str], set]:
    roles, edges = TOPOLOGY_LEVELS[level]()
    ips = assign_ips(list(roles))
    truth = build_ground_truth_graph(roles, edges, ips, graph_id="gt")
    return truth, ips, set(edge_conf(truth))


def conf_mae(candidate: Dict[Pair, float], reference: Dict[Pair, float]) -> float:
    common = set(candidate) & set(reference)
    return fmean(abs(candidate[k] - reference[k]) for k in common) if common else float("nan")


def fuse(views: Sequence[Sequence[Packet]], **kw) -> MultiCollectorPipeline:
    pipe = MultiCollectorPipeline(CAPTURE, **kw)
    for i, v in enumerate(views):
        pipe.ingest(f"c{i}", list(v))
    return pipe


def edge_f1(graph: TopologyGraph, truth: TopologyGraph):
    return compare_topology_to_ground_truth(graph, truth)


# ------------------------------------------------------------------ equivalence
@dataclass(frozen=True)
class EquivRow:
    level: str
    seed: int
    n: int
    arrival: str
    skew: str
    pairs_equal: bool
    max_conf_diff: float
    dup_dropped: int
    packets_full: int
    accepted: int


def run_equivalence(levels: Sequence[str] = LEVELS, seeds: Sequence[int] = SEEDS, ns: Sequence[int] = (2, 3, 4)) -> List[EquivRow]:
    rows = []
    for level in levels:
        for seed in seeds:
            packets = sorted(scenario_packets(level, seed), key=lambda p: p.timestamp)
            ref = edge_conf(full_graph(packets))
            for n in ns:
                for skew_name, skews in (("0", ()), ("<=0.0006s", [0.0002 * i for i in range(n)])):
                    views = make_views(packets, n, 0.5, seed, skew_s=skews)
                    for arrival in ("in_order", "interleaved"):
                        if arrival == "in_order":
                            pipe = fuse(views, dedupe_tolerance_s=TOL)
                        else:
                            pipe = MultiCollectorPipeline(CAPTURE, dedupe_tolerance_s=TOL)
                            shuf = [shuffled_within_window(v, seed + i, 8) for i, v in enumerate(views)]
                            step = 25
                            for at in range(0, max(len(v) for v in shuf), step):
                                for i, v in enumerate(shuf):
                                    pipe.ingest(f"c{i}", v[at:at + step])
                        got = edge_conf(pipe.graph())
                        diff = max((abs(got[k] - ref[k]) for k in set(got) & set(ref)), default=0.0)
                        rows.append(EquivRow(level, seed, n, arrival, skew_name, set(got) == set(ref), diff,
                                             pipe.duplicates_dropped, len(packets), pipe.accepted_total))
    return rows


def format_equivalence(rows: Sequence[EquivRow]) -> str:
    ok = [r for r in rows if r.pairs_equal and r.max_conf_diff < 1e-9]
    lines = [f"{'skew':<11}{'arrival':<13}{'runs':>5}{'pairs==':>9}{'conf exact':>11}{'max |dconf|':>13}{'accepted==full':>16}"]
    for skew in ("0", "<=0.0006s"):
        for arr in ("in_order", "interleaved"):
            g = [r for r in rows if r.skew == skew and r.arrival == arr]
            lines.append(f"{skew:<11}{arr:<13}{len(g):>5}{sum(r.pairs_equal for r in g):>9}"
                         f"{sum(r.max_conf_diff < 1e-9 for r in g):>11}{max(r.max_conf_diff for r in g):>13.2e}"
                         f"{sum(r.accepted == r.packets_full for r in g):>16}")
    lines.append(f"\nfused == full capture (edge set and confidence to 1e-9): {len(ok)}/{len(rows)}")
    return "\n".join(lines)


# ------------------------------------------------------------------ quality + conflicts
@dataclass(frozen=True)
class QualityRow:
    level: str
    seed: int
    single_best_f1: float
    single_mean_f1: float
    pooled_f1: float
    naive_f1: float
    quorum_f1: float
    mae_pooled: float
    mae_naive: float
    mae_union_max: float
    mae_mean: float
    conflicts: Dict[str, int]
    resolutions_complete: bool


def run_quality(levels: Sequence[str] = LEVELS, seeds: Sequence[int] = SEEDS, n: int = 3, drop: float = 0.3) -> List[QualityRow]:
    rows = []
    for level in levels:
        truth, ips, _ = truth_graph(level)
        for seed in seeds:
            packets = sorted(scenario_packets(level, seed), key=lambda p: p.timestamp)
            ref = edge_conf(full_graph(packets))
            views = make_views(packets, n, 0.3, seed, drop=drop)
            pooled = fuse(views, dedupe_tolerance_s=TOL)
            naive = fuse(views, dedupe=False)
            quorum = fuse(views, dedupe_tolerance_s=TOL, quorum=True)
            singles = [pooled.collector_graph(c) for c in pooled.collectors]
            sf1 = [edge_f1(g, truth).edge_f1 for g in singles]
            per = [edge_conf(g) for g in singles]
            keys = set().union(*per)
            umax = {k: max(p[k] for p in per if k in p) for k in keys}
            umean = {k: fmean(p[k] for p in per if k in p) for k in keys}
            res = pooled.resolutions()
            kinds: Dict[str, int] = {}
            for r in res:
                kinds[r.kind] = kinds.get(r.kind, 0) + 1
            rows.append(QualityRow(
                level, seed, max(sf1), fmean(sf1), edge_f1(pooled.graph(), truth).edge_f1,
                edge_f1(naive.graph(), truth).edge_f1, edge_f1(quorum.graph(), truth).edge_f1,
                conf_mae(edge_conf(pooled.graph()), ref), conf_mae(edge_conf(naive.graph()), ref),
                conf_mae(umax, ref), conf_mae(umean, ref), kinds, len(res) == len(pooled.graph().edges),
            ))
    return rows


def format_quality(rows: Sequence[QualityRow]) -> str:
    lines = [f"{'level':<14}{'seed':>5}{'F1 best1':>9}{'mean1':>7}{'pooled':>8}{'naive':>7}{'quorum':>8}"
             f"  {'conf MAE vs full: pooled':>25}{'naive':>7}{'u-max':>7}{'mean':>7}  conflicts"]
    for r in rows:
        lines.append(f"{r.level:<14}{r.seed:>5}{r.single_best_f1:>9.3f}{r.single_mean_f1:>7.3f}{r.pooled_f1:>8.3f}"
                     f"{r.naive_f1:>7.3f}{r.quorum_f1:>8.3f}  {r.mae_pooled:>25.4f}{r.mae_naive:>7.4f}"
                     f"{r.mae_union_max:>7.4f}{r.mae_mean:>7.4f}  {dict(sorted(r.conflicts.items()))}")
    m = lambda f: fmean(getattr(r, f) for r in rows)  # noqa: E731
    lines.append(f"\nmeans: F1 best single {m('single_best_f1'):.3f}, mean single {m('single_mean_f1'):.3f}, pooled "
                 f"{m('pooled_f1'):.3f}, naive {m('naive_f1'):.3f}, quorum {m('quorum_f1'):.3f}; confidence MAE vs full "
                 f"capture: pooled {m('mae_pooled'):.4f}, naive {m('mae_naive'):.4f}, union-max {m('mae_union_max'):.4f}, "
                 f"mean {m('mae_mean'):.4f}; every fused edge has a Resolution: "
                 f"{sum(r.resolutions_complete for r in rows)}/{len(rows)}")
    return "\n".join(lines)


# ------------------------------------------------------------------ failure cases
@dataclass(frozen=True)
class FailureRow:
    case: str
    detail: str


def run_failures(levels: Sequence[str] = ("multi_service", "large"), seeds: Sequence[int] = SEEDS) -> List[FailureRow]:
    out: List[FailureRow] = []
    agg: Dict[str, List[float]] = {}

    def add(k: str, v: float) -> None:
        agg.setdefault(k, []).append(v)

    for level in levels:
        truth, ips, true_pairs = truth_graph(level)
        for seed in seeds:
            packets = sorted(scenario_packets(level, seed), key=lambda p: p.timestamp)
            ref = edge_conf(full_graph(packets))
            # 1. clock skew: inside vs beyond tolerance (duplicates survive beyond it)
            for name, skew in (("skew_within_tol", 0.0004), ("skew_beyond_tol", 0.05)):
                views = make_views(packets, 3, 0.5, seed, skew_s=[0, skew, 2 * skew])
                pipe = fuse(views, dedupe_tolerance_s=TOL)
                add(f"{name}:mae", conf_mae(edge_conf(pipe.graph()), ref))
                add(f"{name}:accepted_over_full", pipe.accepted_total / len(packets))
            # 3. fabricated edges from one collector: N=3 and N=2 with the default quorum (min_absent=2, cannot fire at
            #    N=2), N=2 with min_absent=1 (a 1-vs-1 tie broken by dropping anything unconfirmed)
            fake = fabricate(packets, ips, true_pairs, seed)
            for tag, n, min_abs in (("N3", 3, 2), ("N2default", 2, 2), ("N2min1", 2, 1)):
                views = make_views(packets, n, 0.6, seed)
                views[0] = sorted(views[0] + fake, key=lambda p: p.timestamp)
                for mode, q in (("pooled", False), ("quorum", True)):
                    g = fuse(views, dedupe_tolerance_s=TOL, quorum=q, quorum_min_absent=min_abs).graph()
                    r = edge_f1(g, truth)
                    add(f"fabricated_{tag}_{mode}:false_edges_kept", float(len(set(edge_conf(g)) - true_pairs)))
                    add(f"fabricated_{tag}_{mode}:edge_recall", r.edge_recall)
            # 4b. collectors on different segments: each real edge visible from one vantage point only
            views = segment_views(packets, 3)
            add("segments_N3_pooled:edge_recall", edge_f1(fuse(views, dedupe_tolerance_s=TOL).graph(), truth).edge_recall)
            add("segments_N3_quorum:edge_recall",
                edge_f1(fuse(views, dedupe_tolerance_s=TOL, quorum=True).graph(), truth).edge_recall)
            # 4. direction-split (asymmetric) collectors
            views = direction_split_views(packets)
            pipe = fuse(views, dedupe_tolerance_s=TOL)
            add("direction_split:fused_mae", conf_mae(edge_conf(pipe.graph()), ref))
            for c in pipe.collectors:
                add("direction_split:single_mae", conf_mae(edge_conf(pipe.collector_graph(c)), ref))
    ka = keepalive_packets()
    ka_views = [ka[0::2], ka[1::2]]  # disjoint: every dedupe here is a false merge
    ref_ka = edge_conf(full_graph(ka))
    for tol in (TOL, 1.0):
        pipe = fuse(ka_views, dedupe_tolerance_s=tol)
        add(f"keepalive_tol_{tol}:false_merges_of_{len(ka)}", float(pipe.duplicates_dropped))
        add(f"keepalive_tol_{tol}:conf_error", abs(edge_conf(pipe.graph())[frozenset({'10.9.0.1', '10.9.0.2'})]
                                                    - ref_ka[frozenset({'10.9.0.1', '10.9.0.2'})]))
    for k in sorted(agg):
        v = [x for x in agg[k] if x == x]
        out.append(FailureRow(k, f"mean {fmean(v):.4f}  (min {min(v):.4f}, max {max(v):.4f}, n={len(v)})"))
    return out


def format_failures(rows: Sequence[FailureRow]) -> str:
    return "\n".join(f"{r.case:<46}{r.detail}" for r in rows)


# ------------------------------------------------------------------ cost
def run_cost(level: str = "large", seed: int = 42, ns: Sequence[int] = (1, 2, 4)) -> str:
    packets = sorted(scenario_packets(level, seed), key=lambda p: p.timestamp)
    t0 = time.perf_counter()
    single = IncrementalTopology(CAPTURE)
    single.ingest(packets)
    single.graph(CAPTURE)
    base = time.perf_counter() - t0
    lines = [f"single collector, full capture ({len(packets)} pkts): {base * 1000:.0f} ms"]
    for n in ns:
        views = make_views(packets, n, 0.5, seed)
        t0 = time.perf_counter()
        pipe = fuse(views, dedupe_tolerance_s=TOL)
        pipe.graph()
        dt = time.perf_counter() - t0
        lines.append(f"fused, {n} collectors ({sum(len(v) for v in views)} observations): {dt * 1000:.0f} ms "
                     f"({dt / base:.1f}x single); conflicts resolved: {len(pipe.resolutions())} edges")
    return "\n".join(lines)
