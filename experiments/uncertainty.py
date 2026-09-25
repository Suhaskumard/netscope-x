"""End-to-end uncertainty propagation from packet-level observation noise (spec Phase 83).

One model, not per-stage confidences: a single nonparametric bootstrap over the OBSERVED packets feeds every
stage of the real, unmodified pipeline. Each draw resamples the observed packet set with replacement (the
observation model of `sample_packets` is independent per-packet inclusion, so per-packet resampling is the
matching noise model), then runs `reconstruct_flows -> build_topology_graph -> estimate_dependency_strength ->
generate_causal_candidates -> run_failure_propagation_pipeline`. Because the same draw feeds all stages, the
topology, dependency and PathForge outputs are jointly distributed; their bands are not independent.

Reported per draw-set (`PropagatedUncertainty`):
  - edge: presence probability and 90% band on `Edge.confidence` (absent edge counts as confidence 0)
  - dependency: 90% band on `DependencyEdge.strength` (absent counts as 0)
  - PathForge: per-node probability of being in the predicted affected set, per failure target, and the 90%
    band on the affected-set size
Everything is keyed by node IP address (what the pipeline observes); no ground truth enters this module. What
the bootstrap cannot see is stated, not hidden: an edge with no observed packet has presence probability 0 in
every draw, so resampling cannot represent missing evidence -- `benchmark` scores that blind spot against truth.
"""

from __future__ import annotations

import random
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Sequence, Set, Tuple

import numpy as np

from backend.app.models.failure import FailureScenario, FailureType
from backend.app.models.packet import Packet
from backend.dependency.causal_candidates import generate_causal_candidates
from backend.dependency.strength import estimate_dependency_strength
from backend.nettrace.reconstruct import reconstruct_flows
from backend.nettrace.topology.graph import build_topology_graph
from backend.simulation.failure_propagation_pipeline import run_failure_propagation_pipeline
from experiments.artifacts.io import write_jsonl
from experiments.artifacts.paths import packets_path

BAND_LOW, BAND_HIGH = 5.0, 95.0  # 90% band
EdgeKey = FrozenSet[str]  # undirected pair of node IPs
DepKey = Tuple[str, str]  # (source ip, target ip)


@dataclass(frozen=True)
class Band:
    low: float
    mean: float
    high: float

    @property
    def width(self) -> float:
        return self.high - self.low


def band(values: Sequence[float]) -> Band:
    arr = np.asarray(values, dtype=float)
    return Band(float(np.percentile(arr, BAND_LOW)), float(arr.mean()), float(np.percentile(arr, BAND_HIGH)))


@dataclass
class DrawResult:
    """One pass of the real pipeline over one packet set."""

    edge_confidence: Dict[EdgeKey, float]
    dependency_strength: Dict[DepKey, float]
    node_ips: Set[str]
    affected: Dict[str, Optional[Set[str]]]  # failure-target ip -> affected node ips (None: target not observed)


@dataclass
class PropagatedUncertainty:
    draws: int
    node_count: int
    edge_presence: Dict[EdgeKey, float]
    edge_confidence: Dict[EdgeKey, Band]
    dependency_strength: Dict[DepKey, Band]
    affected_probability: Dict[str, Dict[str, float]]  # target ip -> node ip -> P(in predicted affected set)
    affected_size: Dict[str, Band]  # target ip -> band on |predicted affected set| (draws where target observed)
    target_observed_rate: Dict[str, float]
    point: DrawResult  # the pipeline on the observed packets themselves (the un-resampled point estimate)
    stage_width: Dict[str, float] = field(default_factory=dict)  # mean 90% band width per stage


def run_draw(
    packets: List[Packet],
    scratch: Path,
    targets_ip: Sequence[str],
    edge_confidence_signal_strength: float = 0.3,
    as_of: Optional[datetime] = None,
) -> DrawResult:
    """Runs the real pipeline over `packets` in a throwaway directory."""
    scratch.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(dir=scratch))
    capture_id = "unc"
    try:
        write_jsonl(packets_path(work, capture_id), packets)
        reconstruct_flows(work, capture_id)
        graph = build_topology_graph(
            work, capture_id, graph_id="unc-g", edge_confidence_signal_strength=edge_confidence_signal_strength
        )
        deps = estimate_dependency_strength(
            work, capture_id, as_of=as_of, edge_confidence_signal_strength=edge_confidence_signal_strength
        )
        candidates = generate_causal_candidates(deps)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    ip_of = {n.node_id: str(n.ip_addresses[0]) for n in graph.nodes}
    edge_conf: Dict[EdgeKey, float] = {}
    for e in graph.edges:
        key = frozenset((ip_of[e.source_node_id], ip_of[e.target_node_id]))
        edge_conf[key] = max(edge_conf.get(key, 0.0), e.confidence)
    dep_strength: Dict[DepKey, float] = {}
    for d in deps:
        if d.source_node_id in ip_of and d.target_node_id in ip_of:
            dep_strength[(ip_of[d.source_node_id], ip_of[d.target_node_id])] = d.strength

    id_of = {ip: nid for nid, ip in ip_of.items()}
    affected: Dict[str, Optional[Set[str]]] = {}
    for ip in targets_ip:
        if ip not in id_of:
            affected[ip] = None
            continue
        scenario = FailureScenario(
            scenario_id=f"unc:failure:{ip}", failure_type=FailureType.NODE_FAILURE, target_node_id=id_of[ip]
        )
        result = run_failure_propagation_pipeline(graph, scenario, candidates, role_classifications=None)
        ids = {si.node_id for si in result.service_impacts} | set(result.newly_unreachable_node_ids)
        affected[ip] = {ip_of[i] for i in ids if i in ip_of}
    return DrawResult(edge_conf, dep_strength, set(ip_of.values()), affected)


def _zero_filled(draws: Sequence[Dict], keys: Sequence) -> Dict:
    return {k: [d.get(k, 0.0) for d in draws] for k in keys}


def propagate(
    observed: List[Packet],
    scratch: Path,
    targets_ip: Sequence[str],
    draws: int = 30,
    seed: int = 0,
    edge_confidence_signal_strength: float = 0.3,
    as_of: Optional[datetime] = None,
) -> PropagatedUncertainty:
    """Bootstrap `draws` resamples of `observed` (with replacement, same size) through the real pipeline."""
    if draws < 2:
        raise ValueError("draws must be >= 2 to form a band")
    point = run_draw(observed, scratch, targets_ip, edge_confidence_signal_strength, as_of)
    rng = random.Random(seed)
    n = len(observed)
    results: List[DrawResult] = []
    for _ in range(draws):
        sample = [observed[rng.randrange(n)] for _ in range(n)] if n else []
        sample.sort(key=lambda p: p.timestamp)  # the pipeline reads packets in capture order
        results.append(run_draw(sample, scratch, targets_ip, edge_confidence_signal_strength, as_of))

    edge_keys = sorted({k for r in results + [point] for k in r.edge_confidence}, key=lambda k: sorted(k))
    dep_keys = sorted({k for r in results + [point] for k in r.dependency_strength})
    node_ips = sorted({ip for r in results + [point] for ip in r.node_ips})

    edge_series = _zero_filled([r.edge_confidence for r in results], edge_keys)
    dep_series = _zero_filled([r.dependency_strength for r in results], dep_keys)
    edge_bands = {k: band(v) for k, v in edge_series.items()}
    dep_bands = {k: band(v) for k, v in dep_series.items()}
    presence = {k: float(np.mean([1.0 if r.edge_confidence.get(k) else 0.0 for r in results])) for k in edge_keys}

    affected_prob: Dict[str, Dict[str, float]] = {}
    affected_size: Dict[str, Band] = {}
    observed_rate: Dict[str, float] = {}
    for t in targets_ip:
        sets = [r.affected[t] for r in results if r.affected.get(t) is not None]
        observed_rate[t] = len(sets) / len(results)
        if not sets:
            continue
        affected_prob[t] = {ip: sum(ip in s for s in sets) / len(sets) for ip in node_ips}
        affected_size[t] = band([len(s) for s in sets])

    stage_width = {
        "topology": float(np.mean([b.width for b in edge_bands.values()])) if edge_bands else 0.0,
        "dependency": float(np.mean([b.width for b in dep_bands.values()])) if dep_bands else 0.0,
        # PathForge: affected-set size band, as a fraction of nodes in the observed universe
        "pathforge": float(np.mean([b.width for b in affected_size.values()])) / max(1, len(node_ips))
        if affected_size else 0.0,
    }
    return PropagatedUncertainty(
        draws=draws, node_count=len(node_ips), edge_presence=presence, edge_confidence=edge_bands,
        dependency_strength=dep_bands, affected_probability=affected_prob, affected_size=affected_size,
        target_observed_rate=observed_rate, point=point, stage_width=stage_width,
    )
