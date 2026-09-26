"""Distributed Multi-Collector Capture (spec addendum Phase 90).

Several vantage points ("collectors") feed ONE reconstruction pipeline. Each collector sees only part of the traffic,
often the same packets as another collector, and sometimes wrong (skewed clocks, a faulty or hostile collector).

RESOLUTION RULE (evidence pooling, not averaging)
1. Cross-collector de-duplication. The same wire packet seen by two collectors must count once, because the Phase 31
   edge confidence is a noisy-OR over pooled packet evidence and only means something over non-duplicated evidence.
   Identity = (src/dst ip+port, protocol, size, tcp_flags, direction); two observations from DIFFERENT collectors whose
   timestamps differ by at most `dedupe_tolerance_s` are one packet (nearest match; each accepted packet can be claimed
   once per collector, so a collector's own genuine repeats are never merged with each other). The first-seen
   timestamp is kept.
2. The deduplicated union goes into one `IncrementalTopology` (Phase 85); nodes, flows, edges and confidences are
   recomputed from the pooled evidence. Where two collectors disagree about an edge, the fused confidence is whatever
   the pooled evidence supports - never a max, mean or vote of the collectors' numbers.
3. Optional quorum guard (`quorum=True`): an edge backed by exactly one collector while at least `quorum_min_absent`
   other collectors observed BOTH endpoints and never saw the edge is "contested" and dropped. This is a defence
   against a collector fabricating an edge; it also drops real edges that only one vantage point can see (see limits).
Every fused edge gets a `Resolution` record (who supported it, who saw both ends but not the edge, who was blind to an
endpoint, per-collector confidences, decision) so a resolution is inspectable, not just applied.

FAILURE CASES (measured in experiments/multi_collector_benchmark.py; documented in docs/architecture/multi_collector.md)
clock skew beyond the tolerance (duplicates survive and inflate confidence); a tolerance wide enough to merge genuine
repeats; a fabricated edge from a single collector when quorum is off (kept) or when only two collectors exist (quorum
cannot arbitrate a 1-vs-1 tie); colluding collectors; real edges visible from one vantage point only (quorum drops
them); greedy nearest-match de-duplication can differ by arrival order only when timestamps are closer than the
tolerance to more than one candidate.

No schema change: collector provenance lives outside the frozen `Packet`. Never imports `simulator.ground_truth`.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, FrozenSet, List, Optional, Sequence, Set, Tuple

from backend.app.models.packet import Packet
from backend.app.models.topology import TopologyGraph
from backend.nettrace.topology.edges import _DEFAULT_PACKET_SCALE, _DEFAULT_SIGNAL_STRENGTH
from backend.nettrace.topology.incremental import IncrementalTopology

Pair = FrozenSet[str]


def _identity(p: Packet) -> Tuple:
    return (str(p.src_ip), str(p.dst_ip), p.src_port, p.dst_port, p.protocol, p.size_bytes, p.tcp_flags, p.direction)


@dataclass(frozen=True)
class Resolution:
    pair: Pair  # the two endpoint IPs
    kind: str  # agree | existence | confidence | single_source
    supporting: Tuple[str, ...]  # collectors whose own graph has the edge
    absent: Tuple[str, ...]  # collectors that saw both endpoints but not the edge
    blind: Tuple[str, ...]  # collectors that never saw at least one endpoint
    per_collector_confidence: Tuple[Tuple[str, float], ...]
    fused_confidence: float
    decision: str  # kept | dropped_contested
    rule: str


@dataclass(frozen=True)
class IngestReport:
    collector_id: str
    packets: int
    accepted: int
    duplicates: int


@dataclass
class _Seen:
    timestamp: datetime
    collectors: Set[str] = field(default_factory=set)


class MultiCollectorPipeline:
    def __init__(
        self,
        capture_id: str,
        *,
        dedupe: bool = True,
        dedupe_tolerance_s: float = 0.001,
        quorum: bool = False,
        quorum_min_absent: int = 2,
        confidence_delta: float = 0.15,
        edge_confidence_packet_scale: float = _DEFAULT_PACKET_SCALE,
        edge_confidence_signal_strength: float = _DEFAULT_SIGNAL_STRENGTH,
    ) -> None:
        if dedupe_tolerance_s < 0 or quorum_min_absent < 1 or confidence_delta < 0:
            raise ValueError("invalid multi-collector settings")
        self.capture_id = capture_id
        self._dedupe = dedupe
        self._tol = timedelta(seconds=dedupe_tolerance_s)
        self._quorum = quorum
        self._min_absent = quorum_min_absent
        self._delta = confidence_delta
        self._scale, self._strength = edge_confidence_packet_scale, edge_confidence_signal_strength
        self._fused = IncrementalTopology(capture_id, 30.0, self._scale, self._strength)
        self._local: Dict[str, IncrementalTopology] = {}
        self._seen: Dict[Tuple, List[_Seen]] = defaultdict(list)
        self.duplicates_dropped = 0
        self.accepted_total = 0
        self.per_collector_packets: Dict[str, int] = defaultdict(int)

    @property
    def collectors(self) -> List[str]:
        return sorted(self._local)

    def ingest(self, collector_id: str, packets: Sequence[Packet]) -> IngestReport:
        local = self._local.setdefault(
            collector_id, IncrementalTopology(self.capture_id, 30.0, self._scale, self._strength)
        )
        local.ingest(packets)  # a collector's own view keeps everything it saw
        accepted: List[Packet] = []
        dup = 0
        for p in packets:
            if self._dedupe and self._is_duplicate(collector_id, p):
                dup += 1
            else:
                accepted.append(p)
        self._fused.ingest(accepted)
        self.duplicates_dropped += dup
        self.accepted_total += len(accepted)
        self.per_collector_packets[collector_id] += len(packets)
        return IngestReport(collector_id, len(packets), len(accepted), dup)

    def _is_duplicate(self, collector_id: str, p: Packet) -> bool:
        entries = self._seen[_identity(p)]
        best: Optional[_Seen] = None
        best_gap = None
        for e in entries:
            if collector_id in e.collectors:
                continue  # already claimed by this collector: a genuine repeat, not a duplicate
            gap = abs(e.timestamp - p.timestamp)
            if gap <= self._tol and (best_gap is None or gap < best_gap):
                best, best_gap = e, gap
        if best is not None:
            best.collectors.add(collector_id)
            return True
        entries.append(_Seen(p.timestamp, {collector_id}))
        return False

    # -- results -------------------------------------------------------------------------------------------
    def collector_graph(self, collector_id: str) -> TopologyGraph:
        return self._local[collector_id].graph(f"{self.capture_id}:{collector_id}")

    def resolutions(self) -> List[Resolution]:
        fused = self._fused.graph(self.capture_id)
        ip = {n.node_id: str(n.ip_addresses[0]) for n in fused.nodes}
        views = {}
        for cid in self._local:
            g = self.collector_graph(cid)
            nid = {n.node_id: str(n.ip_addresses[0]) for n in g.nodes}
            edges = {frozenset({nid[e.source_node_id], nid[e.target_node_id]}): e.confidence for e in g.edges}
            views[cid] = (set(nid.values()), edges)
        out: List[Resolution] = []
        for e in fused.edges:
            pair = frozenset({ip[e.source_node_id], ip[e.target_node_id]})
            sup, absent, blind, confs = [], [], [], []
            for cid in sorted(views):
                seen_ips, edges = views[cid]
                if pair in edges:
                    sup.append(cid)
                    confs.append((cid, edges[pair]))
                elif pair <= seen_ips:
                    absent.append(cid)
                else:
                    blind.append(cid)
            if sup and absent:
                kind = "existence"
            elif len(sup) >= 2 and max(c for _, c in confs) - min(c for _, c in confs) > self._delta:
                kind = "confidence"
            elif len(sup) == 1 and not absent and len(views) > 1:
                kind = "single_source"
            else:
                kind = "agree"
            contested = (
                self._quorum and kind == "existence" and len(sup) == 1 and len(absent) >= self._min_absent
            )
            out.append(Resolution(
                pair, kind, tuple(sup), tuple(absent), tuple(blind), tuple(confs), e.confidence,
                "dropped_contested" if contested else "kept",
                "pooled-evidence+quorum" if self._quorum else "pooled-evidence",
            ))
        return out

    def graph(self, graph_id: Optional[str] = None) -> TopologyGraph:
        """The fused graph: pooled-evidence edges, minus contested ones when `quorum` is on."""
        fused = self._fused.graph(graph_id or self.capture_id)
        if not self._quorum:
            return fused
        ip = {n.node_id: str(n.ip_addresses[0]) for n in fused.nodes}
        dropped = {r.pair for r in self.resolutions() if r.decision == "dropped_contested"}
        keep = [e for e in fused.edges if frozenset({ip[e.source_node_id], ip[e.target_node_id]}) not in dropped]
        return fused.model_copy(update={"edges": keep})
