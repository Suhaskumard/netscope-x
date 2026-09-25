"""Supplementary causal dataset for Phase 79: traffic with a well-defined causal structure.

Phase 70's lag-encoded pulses (`synthetic_traffic._pulse_packets`) make every node a delayed copy of one
hidden shared driver, which violates the causal-sufficiency assumption of PC-style discovery. So a poor
result there is ambiguous: the method, or the data? This generator is the control: every node's activity
is *driven by its declared parents' earlier activity plus independent noise*, so the declared directed edges
ARE the true causal graph and no hidden common cause exists.

Generative model (per one-bucket step, `bucket_seconds` wide):
  - Nodes are processed in topological order of the declared directed edges. If the declared edges contain
    a cycle (e.g. `redundant`), back-edges are dropped until the graph is acyclic and reported in
    `dropped_edges`; ground truth is the kept edges only.
  - A root's count in bucket t is Poisson(`root_rate`), independent across time and nodes.
  - A child's count is Poisson(`base` + `coupling` x sum of its parents' counts in bucket t-1): lag-1
    influence, independent noise, so the parent -> child arrow is real and directed by time.
  - A node's count is rendered as that many distinct flows (fresh source port each, as Phase 70 does,
    because the detector counts flows) from the node to its designated partner (its first parent, or its
    first child for a root), timestamped inside the bucket away from its boundaries.

Honest caveat: the pipeline counts every flow *touching* a node, so a partner also sees the flows it
receives. Each observed series is therefore the node's own activity plus its dependants' -- a partial
mixing the generator does not remove, and part of what makes this a test of the method rather than a
guaranteed pass. This is a construction of this project's, so it shows what the method can do when its
assumptions hold, not that it works on real networks.

Deterministic per `seed`. Never imports `simulator.ground_truth`.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Dict, List, Sequence, Tuple

import networkx as nx
import numpy as np

from backend.app.models.behavior import ServiceRole
from backend.app.models.packet import Packet, PacketDirection
from experiments.synthetic_traffic import BASE_TIME, _port_for, _protocol_for
from simulator.scenarios.topologies import ScenarioEdge


@dataclass
class ParentDrivenDataset:
    packets: List[Packet]
    true_edges: List[Tuple[str, str]]  # directed (parent, child): the generative DAG
    dropped_edges: List[Tuple[str, str]] = field(default_factory=list)
    activity: Dict[str, np.ndarray] = field(default_factory=dict)  # each node's own per-bucket count


def _acyclic_edges(names: Sequence[str], edges: Sequence[ScenarioEdge]) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]]]:
    graph = nx.DiGraph()
    graph.add_nodes_from(names)
    graph.add_edges_from((e.source, e.target) for e in edges)
    dropped: List[Tuple[str, str]] = []
    while True:
        try:
            cycle = nx.find_cycle(graph)
        except nx.NetworkXNoCycle:
            break
        edge = cycle[-1][:2]
        graph.remove_edge(*edge)
        dropped.append(edge)
    return sorted(graph.edges), dropped


def parent_driven_traffic(
    roles: Dict[str, ServiceRole],
    edges: Sequence[ScenarioEdge],
    ip_by_name: Dict[str, str],
    capture_id: str,
    seed: int,
    buckets: int = 100,
    bucket_seconds: float = 10.0,
    root_rate: float = 6.0,
    base: float = 1.0,
    coupling: float = 0.5,
) -> ParentDrivenDataset:
    names = list(roles)
    rng = np.random.default_rng(seed)
    py_rng = random.Random(seed)
    kept, dropped = _acyclic_edges(names, edges)
    dag = nx.DiGraph()
    dag.add_nodes_from(names)
    dag.add_edges_from(kept)

    activity: Dict[str, np.ndarray] = {}
    for name in nx.lexicographical_topological_sort(dag):
        parents = sorted(dag.predecessors(name))
        counts = np.zeros(buckets, dtype=int)
        for t in range(buckets):
            if not parents:
                mean = root_rate
            else:
                previous = sum(int(activity[p][t - 1]) for p in parents) if t > 0 else 0
                mean = base + coupling * previous
            counts[t] = rng.poisson(max(mean, 0.1))
        activity[name] = counts

    packets: List[Packet] = []
    counter = 0
    for name in names:
        parents = sorted(dag.predecessors(name))
        children = sorted(dag.successors(name))
        partner = parents[0] if parents else (children[0] if children else None)
        if partner is None:
            continue
        src_ip, dst_ip = ip_by_name[name], ip_by_name[partner]
        dst_port, protocol = _port_for(roles[partner]), _protocol_for(roles[partner])
        for t in range(buckets):
            for unit in range(int(activity[name][t])):
                at = BASE_TIME + timedelta(seconds=t * bucket_seconds + 2.0, milliseconds=unit * 2)
                src_port = 20000 + py_rng.randint(0, 40000)
                for direction, (a, b, sp, dp) in enumerate(((src_ip, dst_ip, src_port, dst_port), (dst_ip, src_ip, dst_port, src_port))):
                    packets.append(
                        Packet(
                            packet_id=f"{capture_id}:pd{counter}", capture_id=capture_id,
                            timestamp=at + timedelta(milliseconds=direction), src_ip=a, dst_ip=b,
                            src_port=sp, dst_port=dp, protocol=protocol,
                            size_bytes=100 + py_rng.randint(0, 400), direction=PacketDirection.UNKNOWN,
                        )
                    )
                    counter += 1
    packets.sort(key=lambda p: p.timestamp)
    return ParentDrivenDataset(packets=packets, true_edges=kept, dropped_edges=dropped, activity=activity)
