"""Equivalence and speed of streaming dependency / causal-candidate updates (spec Phase 87).

Equivalence is CHECKED after every chunk: `StreamingDependencyEstimator` vs a from-scratch batch
(`write packets -> reconstruct_flows -> estimate_dependency_strength -> generate_causal_candidates`) over the same
prefix. Compared: the dependency list (ids, orientation, count) exactly; strength / frequency / persistence /
directionality / temporal by the reported max absolute difference (running sums add in a different order, so
rounding-level differences are expected and measured, never assumed); and the candidate list (ids, order).

Two traffic families, so temporal precedence is exercised for real and not just sitting at 0:
  matrix    the Phase 68/85 scenario traffic (6 topologies x 3 completeness x 3 seeds)
  lagged    `parent_driven_traffic`: a child's activity follows its parents' one bucket later (Phase 70's generator)
Arrival modes: in_order, and shuffled (each packet up to 12 positions from timestamp order; the batch reference is run
on the same arrival order, exactly as in Phase 85). Speed is per chunk, incremental (ingest + dependencies +
candidates) vs the full batch pipeline and vs batch dependency estimation alone, including where it loses.
Ground truth is not used.
"""

from __future__ import annotations

import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean
from typing import Dict, List, Optional, Sequence, Tuple

from backend.app.models.dependency import DependencyEdge
from backend.app.models.packet import Packet
from backend.dependency.causal_candidates import generate_causal_candidates
from backend.dependency.strength import estimate_dependency_strength
from backend.dependency.streaming import StreamingDependencyEstimator
from backend.nettrace.reconstruct import reconstruct_flows
from experiments.artifacts.io import write_jsonl
from experiments.artifacts.paths import packets_path
from experiments.causal_generators import parent_driven_traffic
from experiments.incremental_topology_benchmark import CAPTURE, chunk_bounds, scenario_packets, shuffled_within_window
from experiments.matrix_runner import TOPOLOGY_LEVELS
from experiments.observation_sampling import sample_packets
from experiments.synthetic_traffic import assign_ips

LEVELS: Tuple[str, ...] = ("small", "medium", "large", "multi_path", "multi_service", "dynamic")
COMPLETENESS: Tuple[float, ...] = (1.0, 0.5, 0.25)
SEEDS: Tuple[int, ...] = (42, 43, 44)
FIELDS = ("strength", "frequency", "persistence_seconds", "directionality_score", "temporal_precedence_score")


def lagged_packets(level: str, seed: int) -> List[Packet]:
    roles, edges = TOPOLOGY_LEVELS[level]()
    return parent_driven_traffic(roles, edges, assign_ips(list(roles)), CAPTURE, seed).packets


def batch_dependencies(prefix: Sequence[Packet], scratch: Path):
    """The full pipeline as it runs today; returns (dependencies, candidates, seconds_total, seconds_estimate_only)."""
    scratch.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(dir=scratch))
    try:
        t0 = time.perf_counter()
        write_jsonl(packets_path(work, CAPTURE), list(prefix))
        reconstruct_flows(work, CAPTURE)
        t1 = time.perf_counter()
        deps = estimate_dependency_strength(work, CAPTURE)
        cands = generate_causal_candidates(deps)
        t2 = time.perf_counter()
        return deps, cands, t2 - t0, t2 - t1
    finally:
        shutil.rmtree(work, ignore_errors=True)


def compare(inc: Sequence[DependencyEdge], ref: Sequence[DependencyEdge]) -> Tuple[bool, float]:
    """(structure identical, max abs difference over numeric fields)."""
    if [(d.dependency_id, d.source_node_id, d.target_node_id) for d in inc] != [
        (d.dependency_id, d.source_node_id, d.target_node_id) for d in ref
    ]:
        return False, float("inf")
    worst = 0.0
    for a, b in zip(inc, ref):
        for f in FIELDS:
            worst = max(worst, abs(getattr(a, f) - getattr(b, f)))
    return True, worst


def _candidate_ids(cands) -> List[Tuple[str, str, str]]:
    return [(c.dependency_id, c.source_node_id, c.target_node_id) for c in cands]


@dataclass(frozen=True)
class EquivalenceRow:
    scenario: str
    mode: str
    chunking: str
    checks: int
    structure_matches: int
    bit_exact: int
    candidate_matches: int
    max_abs_diff: float
    nonzero_temporal_checks: int  # checks where at least one pair had temporal_precedence_score > 0
    first_mismatch: Optional[int]


def check_stream(scenario: str, packets: Sequence[Packet], mode: str, chunking: str, seed: int, scratch: Path) -> EquivalenceRow:
    arrival = list(packets) if mode == "in_order" else shuffled_within_window(packets, seed)
    est = StreamingDependencyEstimator(CAPTURE)
    checks = structure = exact = cand = temporal = 0
    worst = 0.0
    first_bad: Optional[int] = None
    at = 0
    for end in chunk_bounds(len(arrival), chunking, seed):
        est.ingest(arrival[at:end])
        at = end
        got, got_cands = est.dependencies(), est.candidates()
        ref, ref_cands, _, _ = batch_dependencies(arrival[:end], scratch)
        ok, diff = compare(got, ref)
        cands_ok = _candidate_ids(got_cands) == _candidate_ids(ref_cands)
        checks += 1
        structure += ok
        exact += ok and diff == 0.0
        cand += cands_ok
        worst = max(worst, diff)
        temporal += any(d.temporal_precedence_score > 0 for d in ref)
        if not (ok and cands_ok) and first_bad is None:
            first_bad = end
    return EquivalenceRow(scenario, mode, chunking, checks, structure, exact, cand, worst, temporal, first_bad)


def run_equivalence(root: Path, levels: Sequence[str] = LEVELS, completeness: Sequence[float] = COMPLETENESS,
                    seeds: Sequence[int] = SEEDS, chunkings: Sequence[str] = ("ten",)) -> List[EquivalenceRow]:
    scratch = root / "streaming_dependency_scratch"
    rows: List[EquivalenceRow] = []
    for level in levels:
        for seed in seeds:
            for c in completeness:
                pk = sample_packets(scenario_packets(level, seed), c, seed)
                for chunking in chunkings:
                    for mode in ("in_order", "shuffled"):
                        rows.append(check_stream(f"matrix:{level}@{c:g}/s{seed}", pk, mode, chunking, seed, scratch))
            pk = lagged_packets(level, seed)
            for chunking in chunkings:
                for mode in ("in_order", "shuffled"):
                    rows.append(check_stream(f"lagged:{level}/s{seed}", pk, mode, chunking, seed, scratch))
    shutil.rmtree(scratch, ignore_errors=True)
    return rows


def format_equivalence(rows: Sequence[EquivalenceRow]) -> str:
    lines = [
        "equivalence: streaming vs from-scratch batch after every chunk",
        f"{'family/mode':<22}{'streams':>8}{'checks':>8}{'structure':>11}{'bit-exact':>11}{'candidates':>12}"
        f"{'max |diff|':>13}{'temporal>0':>11}",
    ]
    groups: Dict[str, List[EquivalenceRow]] = {}
    for r in rows:
        groups.setdefault(f"{r.scenario.split(':')[0]}/{r.mode}", []).append(r)
    for name, rs in groups.items():
        lines.append(
            f"{name:<22}{len(rs):>8}{sum(r.checks for r in rs):>8}{sum(r.structure_matches for r in rs):>11}"
            f"{sum(r.bit_exact for r in rs):>11}{sum(r.candidate_matches for r in rs):>12}"
            f"{max(r.max_abs_diff for r in rs):>13.2e}{sum(r.nonzero_temporal_checks for r in rs):>11}"
        )
    bad = [r for r in rows if r.first_mismatch is not None]
    lines.append(
        f"ALL {len(rows)} streams, {sum(r.checks for r in rows)} checks; "
        f"streams with a structural or candidate mismatch: {len(bad)}"
    )
    for r in bad[:5]:
        lines.append(f"  mismatch: {r.scenario} {r.mode} at packet {r.first_mismatch}")
    return "\n".join(lines)


@dataclass(frozen=True)
class SpeedRow:
    scenario: str
    packets: int
    pairs: int
    chunks: int
    inc_ms: float  # mean per chunk: ingest + dependencies + candidates
    batch_full_ms: float  # mean per chunk: write + reconstruct + estimate + candidates
    batch_estimate_ms: float  # mean per chunk: estimate + candidates only (flows already on disk)
    mean_pairs_touched: float
    mean_pairs_recomputed: float


def run_speed(root: Path, levels: Sequence[str] = ("small", "multi_service", "large"), chunks: int = 20,
              seed: int = 42) -> List[SpeedRow]:
    scratch = root / "streaming_dependency_scratch"
    rows: List[SpeedRow] = []
    for family, gen in (("matrix", scenario_packets), ("lagged", lagged_packets)):
        for level in levels:
            pk = gen(level, seed)
            est = StreamingDependencyEstimator(CAPTURE)
            inc, full, only, touched, recomputed = [], [], [], [], []
            pairs = at = 0
            for end in [round(len(pk) * (i + 1) / chunks) for i in range(chunks)]:
                t0 = time.perf_counter()
                est.ingest(pk[at:end])
                pairs = len(est.dependencies())
                recomputed.append(est.pairs_recomputed_last)  # before `candidates()` re-reads (and finds nothing stale)
                est.candidates()
                inc.append((time.perf_counter() - t0) * 1000)
                touched.append(est.pairs_touched_last)
                _, _, total, estimate_only = batch_dependencies(pk[:end], scratch)
                full.append(total * 1000)
                only.append(estimate_only * 1000)
                at = end
            rows.append(SpeedRow(f"{family}:{level}", len(pk), pairs, chunks, fmean(inc), fmean(full), fmean(only),
                                 fmean(touched), fmean(recomputed)))
    shutil.rmtree(scratch, ignore_errors=True)
    return rows


def format_speed(rows: Sequence[SpeedRow]) -> str:
    lines = [
        "speed: mean ms per chunk (20 chunks); full = write+reconstruct+estimate, est = estimate only",
        f"{'scenario':<22}{'pkts':>7}{'pairs':>6}{'inc ms':>9}{'full ms':>9}{'est ms':>9}{'x full':>8}{'x est':>7}"
        f"{'touched':>9}{'recomp':>8}",
    ]
    for r in rows:
        lines.append(
            f"{r.scenario:<22}{r.packets:>7}{r.pairs:>6}{r.inc_ms:>9.2f}{r.batch_full_ms:>9.2f}"
            f"{r.batch_estimate_ms:>9.2f}{r.batch_full_ms / r.inc_ms:>8.1f}{r.batch_estimate_ms / r.inc_ms:>7.1f}"
            f"{r.mean_pairs_touched:>9.1f}{r.mean_pairs_recomputed:>8.1f}"
        )
    return "\n".join(lines)
