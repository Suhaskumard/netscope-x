"""Incremental topology reconstruction (spec Phase 85).

Replaces "re-read and re-parse the whole capture, regroup every packet, rebuild every edge" with state that is
updated as packets arrive. `IncrementalTopology.ingest(packets)` keeps the packets in memory, per-IP first/last
observation times, and per five-tuple flow units; only the flow keys a batch touches are re-derived (with the very
same `derive_units` the batch `reconstruct_flows` uses). `flows()` / `graph()` then apply the global numbering and
cross-flow aggregates via `assemble_flows`, and build nodes and edges through the same functions
(`nodes_from_observations`, `discover_edges_from_flows`) the batch path uses, so equivalence is by construction
where the code is shared and is CHECKED, not assumed, by `experiments/incremental_topology_benchmark.py`.

What stays O(everything) on purpose: flow numbering (`flow_id` appears in edge evidence text) and the per-source
aggregates are recomputed from cached units when a graph is materialized. What is saved is packet re-parsing, file
I/O, regrouping, and per-flow feature derivation for untouched flows.

Limits, stated: pcap-derived TLS versions are not supported (packets only -- pass `pcap_present=True` to be told so
rather than get silently different results); `as_of` time-travel remains a batch feature. Never imports ground truth.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Sequence, Set, Tuple

from backend.app.models.flow import Flow
from backend.app.models.packet import Packet, TransportProtocol
from backend.app.models.topology import Node, TopologyGraph
from backend.nettrace.reconstruct import _FLOW_PROTOCOLS, _flow_key, _FlowKey, _Unit, assemble_flows, derive_units
from backend.nettrace.topology.discovery import nodes_from_observations
from backend.nettrace.topology.edges import (
    _DEFAULT_PACKET_SCALE,
    _DEFAULT_SIGNAL_STRENGTH,
    discover_edges_from_flows,
)


@dataclass(frozen=True)
class IngestStats:
    packets: int
    flow_keys_touched: int
    flow_keys_total: int
    new_ips: int
    # (flow key, units before, units after) for every touched key; Phase 87's streaming dependency estimator
    # retracts the old contribution and adds the new one. Excluded from equality so older comparisons are unaffected.
    changes: Tuple[Tuple[_FlowKey, Tuple[_Unit, ...], Tuple[_Unit, ...]], ...] = field(default=(), compare=False, repr=False)


class IncrementalTopology:
    def __init__(
        self,
        capture_id: str,
        udp_session_idle_timeout_seconds: float = 30.0,
        edge_confidence_packet_scale: float = _DEFAULT_PACKET_SCALE,
        edge_confidence_signal_strength: float = _DEFAULT_SIGNAL_STRENGTH,
        pcap_present: bool = False,
    ) -> None:
        if pcap_present:
            raise ValueError("IncrementalTopology works from packets only; pcap-derived TLS versions need the batch path")
        self.capture_id = capture_id
        self._udp_idle = udp_session_idle_timeout_seconds
        self._scale = edge_confidence_packet_scale
        self._strength = edge_confidence_signal_strength
        self._groups: Dict[_FlowKey, List[Packet]] = defaultdict(list)
        self._units: Dict[_FlowKey, List[_Unit]] = {}
        self._first: Dict[str, datetime] = {}
        self._last: Dict[str, datetime] = {}
        self.packet_count = 0

    def ingest(self, packets: Sequence[Packet]) -> IngestStats:
        """Adds `packets` (in arrival order). Only the flow keys they touch are re-derived."""
        touched: Set[_FlowKey] = set()
        new_ips = 0
        for pkt in packets:
            for ip in (str(pkt.src_ip), str(pkt.dst_ip)):
                if ip not in self._first:
                    new_ips += 1
                    self._first[ip] = self._last[ip] = pkt.timestamp
                else:
                    if pkt.timestamp < self._first[ip]:
                        self._first[ip] = pkt.timestamp
                    if pkt.timestamp > self._last[ip]:
                        self._last[ip] = pkt.timestamp
            if pkt.protocol in _FLOW_PROTOCOLS:
                key = _flow_key(pkt)
                self._groups[key].append(pkt)
                touched.add(key)
        changes = []
        for key in touched:
            before = tuple(self._units.get(key, ()))
            self._units[key] = derive_units(self._groups[key], self._udp_idle)
            changes.append((key, before, tuple(self._units[key])))
        self.packet_count += len(packets)
        return IngestStats(len(packets), len(touched), len(self._groups), new_ips, tuple(changes))

    def nodes(self) -> List[Node]:
        return nodes_from_observations(self.capture_id, self._first, self._last)

    def flows(self) -> List[Flow]:
        # Insertion order of `_groups` is first-packet arrival order, the same order batch iterates its groups in.
        units = [u for key in self._groups for u in self._units[key]]
        return assemble_flows(self.capture_id, units)

    def graph(self, graph_id: str) -> TopologyGraph:
        nodes = self.nodes()
        edges = discover_edges_from_flows(self.capture_id, self.flows(), nodes, self._scale, self._strength)
        return TopologyGraph(graph_id=graph_id, generated_at=datetime.now(timezone.utc), nodes=nodes, edges=edges)
