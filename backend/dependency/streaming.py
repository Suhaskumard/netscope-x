"""Streaming dependency-strength and causal-candidate updates (spec addendum Phase 87).

Replaces "re-read the capture, rebuild every edge and recompute every pair" (`estimate_dependency_strength`) with
sufficient statistics kept per node pair and updated as packets arrive. The strength is the same five-signal
noisy-OR; only its inputs are maintained incrementally, and the formulas are the batch code itself
(`combine_dependency_strength`, `confidence_from_stats`, `precedence_from_times`, `_bidirectionality`), so
equivalence is by shared code where possible and is CHECKED against a from-scratch batch run by
`experiments/streaming_dependency_benchmark.py`, not assumed.

What is maintained
  per node pair   flow count, packet sum, forward-byte-ratio sum, exact counters for the "any flow" signals
                  (established / fingerprinted / persistent), and sorted lists of first_seen / last_seen /
                  bidirectionality so min/max survive retraction.
  per node        sorted first_seen times of every flow touching it (the input of temporal precedence).
A flow's contribution changes when more packets arrive (packet count, byte ratio, TCP state, and `is_persistent`,
which depends on how many sessions share the five-tuple), so each touched flow key is RETRACTED (old units) and
re-ADDED (new units) using the old/new units `IncrementalTopology.ingest` reports.

What is recomputed after an ingest: only pairs whose statistics changed, plus pairs whose temporal inputs changed.
Temporal precedence depends on BOTH nodes' whole flow-time series, so a new flow at node A dirties the temporal score
of every pair incident to A, and each such recompute is O(flows at the two nodes), not O(1). The noisy-OR product itself
is O(1) per pair. Node ids (and so edge orientation and `dependency_id`) are positional in first-observed order and can
shift as new IPs appear, so orientation and ids are assigned when results are read, exactly as batch assigns them.

Limits, stated: packets only (no pcap TLS), no `as_of`, state grows without bound; floating-point running sums add in a
different order than batch, so values agree to rounding (~1e-12), not necessarily bit-for-bit. Never imports ground truth.
"""

from __future__ import annotations

from bisect import bisect_left, insort
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Sequence, Set, Tuple

from backend.app.models.dependency import DependencyEdge
from backend.app.models.flow import TCPState
from backend.app.models.packet import Packet
from backend.dependency.causal_candidates import _DEFAULT_STRENGTH_THRESHOLD, CausalCandidate, generate_causal_candidates
from backend.dependency.strength import (
    _DEFAULT_DEPENDENCY_SIGNAL_STRENGTH,
    _DEFAULT_FREQUENCY_SCALE,
    _DEFAULT_PERSISTENCE_SCALE,
    combine_dependency_strength,
)
from backend.dependency.temporal_precedence import _DEFAULT_BUCKET_SECONDS, _DEFAULT_MAX_LAG_BUCKETS, precedence_from_times
from backend.nettrace.reconstruct import _compute_features, _Unit
from backend.nettrace.topology.edges import (
    _DEFAULT_PACKET_SCALE,
    _DEFAULT_SIGNAL_STRENGTH,
    _bidirectionality,
    confidence_from_stats,
)
from backend.nettrace.topology.incremental import IncrementalTopology

_Pair = Tuple[str, str]  # (ip, ip), sorted


@dataclass(frozen=True)
class _UnitRecord:
    pair: _Pair
    ips: Tuple[str, ...]  # distinct IPs of the flow (for per-node time lists)
    first_seen: datetime
    last_seen: datetime
    packets: int
    ratio: float
    established: bool
    fingerprinted: bool
    persistent: bool
    bidirectionality: float


def _records(units: Sequence[_Unit]) -> List[_UnitRecord]:
    persistent = len(units) > 1  # `is_persistent`: more than one session on the same five-tuple
    out: List[_UnitRecord] = []
    for u in units:
        src, dst = str(u.canonical.src_ip), str(u.canonical.dst_ip)
        ratio = _compute_features(u.group, u.forward_bytes, 0, 0, persistent).forward_byte_ratio
        out.append(
            _UnitRecord(
                pair=(src, dst) if src <= dst else (dst, src),
                ips=(src,) if src == dst else (src, dst),
                first_seen=u.group[0].timestamp,
                last_seen=u.group[-1].timestamp,
                packets=len(u.group),
                ratio=ratio,
                established=u.tcp_state == TCPState.ESTABLISHED,
                fingerprinted=u.fingerprinted_protocol is not None,
                persistent=persistent,
                bidirectionality=_bidirectionality(ratio),
            )
        )
    return out


def _remove_sorted(values: list, item) -> None:
    del values[bisect_left(values, item)]


class _PairStats:
    def __init__(self) -> None:
        self.count = 0
        self.packets = 0
        self.ratio_sum = 0.0
        self.established = 0
        self.fingerprinted = 0
        self.persistent = 0
        self.firsts: List[datetime] = []
        self.lasts: List[datetime] = []
        self.bidirs: List[float] = []
        self.version = 0

    def add(self, r: _UnitRecord) -> None:
        self._apply(r, +1)
        insort(self.firsts, r.first_seen)
        insort(self.lasts, r.last_seen)
        insort(self.bidirs, r.bidirectionality)

    def remove(self, r: _UnitRecord) -> None:
        self._apply(r, -1)
        _remove_sorted(self.firsts, r.first_seen)
        _remove_sorted(self.lasts, r.last_seen)
        _remove_sorted(self.bidirs, r.bidirectionality)

    def _apply(self, r: _UnitRecord, sign: int) -> None:
        self.count += sign
        self.packets += sign * r.packets
        self.ratio_sum += sign * r.ratio
        self.established += sign * r.established
        self.fingerprinted += sign * r.fingerprinted
        self.persistent += sign * r.persistent
        self.version += 1


@dataclass(frozen=True)
class _Computed:
    frequency: float
    persistence_seconds: float
    directionality: float
    temporal: float
    strength: float
    first_observed: datetime


class StreamingDependencyEstimator:
    def __init__(
        self,
        capture_id: str,
        edge_confidence_packet_scale: float = _DEFAULT_PACKET_SCALE,
        edge_confidence_signal_strength: float = _DEFAULT_SIGNAL_STRENGTH,
        dependency_frequency_scale: float = _DEFAULT_FREQUENCY_SCALE,
        dependency_persistence_scale: float = _DEFAULT_PERSISTENCE_SCALE,
        dependency_signal_strength: float = _DEFAULT_DEPENDENCY_SIGNAL_STRENGTH,
        dependency_temporal_bucket_seconds: float = _DEFAULT_BUCKET_SECONDS,
        dependency_temporal_max_lag_buckets: int = _DEFAULT_MAX_LAG_BUCKETS,
    ) -> None:
        self.capture_id = capture_id
        self._topology = IncrementalTopology(capture_id, 30.0, edge_confidence_packet_scale, edge_confidence_signal_strength)
        self._conf = (edge_confidence_packet_scale, edge_confidence_signal_strength)
        self._dep = (dependency_frequency_scale, dependency_persistence_scale, dependency_signal_strength)
        self._temporal = (dependency_temporal_bucket_seconds, dependency_temporal_max_lag_buckets)
        self._by_key: Dict[object, List[_UnitRecord]] = {}
        self._pairs: Dict[_Pair, _PairStats] = {}
        self._node_times: Dict[str, List[datetime]] = {}
        self._node_version: Dict[str, int] = {}
        self._cache: Dict[_Pair, Tuple[Tuple, _Computed]] = {}
        self.pairs_recomputed_last = 0
        self.pairs_touched_last = 0

    # -- ingestion ------------------------------------------------------------------------------------------------
    def ingest(self, packets: Sequence[Packet]) -> int:
        """Adds `packets` (arrival order); returns the number of node pairs whose statistics changed."""
        stats = self._topology.ingest(packets)
        touched: Set[_Pair] = set()
        for key, _before, after in stats.changes:
            for r in self._by_key.pop(key, ()):
                self._pairs[r.pair].remove(r)
                for ip in r.ips:
                    _remove_sorted(self._node_times[ip], r.first_seen)
                    self._node_version[ip] += 1
                touched.add(r.pair)
            new = _records(after)
            self._by_key[key] = new
            for r in new:
                self._pairs.setdefault(r.pair, _PairStats()).add(r)
                for ip in r.ips:
                    insort(self._node_times.setdefault(ip, []), r.first_seen)
                    self._node_version[ip] = self._node_version.get(ip, 0) + 1
                touched.add(r.pair)
        self.pairs_touched_last = len(touched)
        return len(touched)

    # -- reading --------------------------------------------------------------------------------------------------
    def _compute(self, src_ip: str, dst_ip: str, st: _PairStats) -> _Computed:
        fs, ps, s = self._dep
        persistence = (st.lasts[-1] - st.firsts[0]).total_seconds()
        frequency = st.count / persistence if persistence > 0 else float(st.count)
        directionality = 1 - _bidirectionality(st.ratio_sum / st.count)
        confidence = confidence_from_stats(
            st.packets,
            {  # same keys and order as the batch `_signal_indicators` (the product's order matters to rounding)
                "established": 1.0 if st.established > 0 else 0.0,
                "fingerprinted": 1.0 if st.fingerprinted > 0 else 0.0,
                "tls": 0.0,  # packets carry no TLS version; pcap-derived versions are out of scope
                "persistent": 1.0 if st.persistent > 0 else 0.0,
                "bidirectional": st.bidirs[-1] if st.bidirs else 0.0,
            },
            *self._conf,
        )
        temporal = precedence_from_times(self._node_times[src_ip], self._node_times[dst_ip], *self._temporal)
        strength = combine_dependency_strength(frequency, persistence, directionality, confidence, temporal, fs, ps, s)
        return _Computed(frequency, persistence, directionality, temporal, strength, st.firsts[0])

    def dependencies(self) -> List[DependencyEdge]:
        """One `DependencyEdge` per node pair, oriented and numbered the way the batch estimator does. A pair is
        recomputed only if its statistics, its orientation, or either node's flow times changed since last read."""
        node_id = {str(n.ip_addresses[0]): n.node_id for n in self._topology.nodes()}
        recomputed = 0
        fresh: Dict[_Pair, Tuple[Tuple, _Computed]] = {}
        rows = []
        for pair, st in self._pairs.items():
            if st.count <= 0:
                continue
            a, b = pair
            # batch orients each pair by string order of node ids (`sorted((src_id, dst_id))`)
            src_ip, dst_ip = (a, b) if node_id[a] <= node_id[b] else (b, a)
            valid = (src_ip, dst_ip, st.version, self._node_version[src_ip], self._node_version[dst_ip])
            hit = self._cache.get(pair)
            if hit is not None and hit[0] == valid:
                computed = hit[1]
            else:
                computed = self._compute(src_ip, dst_ip, st)
                recomputed += 1
            fresh[pair] = (valid, computed)
            rows.append((computed.first_observed, node_id[src_ip], node_id[dst_ip], computed))
        self._cache = fresh
        self.pairs_recomputed_last = recomputed
        rows.sort(key=lambda r: r[:3])
        return [
            DependencyEdge(
                dependency_id=f"{self.capture_id}:dependency:{index}",
                source_node_id=sid,
                target_node_id=tid,
                strength=c.strength,
                frequency=c.frequency,
                persistence_seconds=c.persistence_seconds,
                directionality_score=c.directionality,
                temporal_precedence_score=c.temporal,
            )
            for index, (_, sid, tid, c) in enumerate(rows)
        ]

    def candidates(self, strength_threshold: float = _DEFAULT_STRENGTH_THRESHOLD) -> List[CausalCandidate]:
        """Causal candidates from the current dependencies, via the batch `generate_causal_candidates` (a cheap
        filter over pairs; the expensive strength computation above is what is incremental)."""
        return generate_causal_candidates(self.dependencies(), strength_threshold)
