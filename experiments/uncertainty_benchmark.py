"""Benchmark for the end-to-end uncertainty model (spec Phase 83).

Two questions, both measured against real Phase 68 cells:
  1. Monotonicity (the spec's verification): does the propagated band widen as observation completeness falls?
     Per stage (topology / dependency / PathForge) and combined, per completeness level, plus a paired
     lowest-vs-highest comparison per (topology, seed) and a Spearman correlation across all cells.
     Pass criterion, fixed before the run: the band at the lowest completeness is wider than at 1.0 on a
     majority of (topology, seed) pairs for the combined width.
  2. Calibration (beyond the spec): are the propagated probabilities honest? Brier score against ground truth
     of the bootstrap edge-presence probability vs the existing per-edge `Edge.confidence`, and of the bootstrap
     affected-node probability vs the point prediction's 0/1 membership. The bootstrap's blind spot is scored
     directly: `edge_blind_rate` is the share of truly declared edges the bootstrap gives probability 0.
Ground truth is used only here, for scoring; `experiments/uncertainty.py` never sees it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from statistics import fmean
from typing import Dict, List, Optional, Sequence, Tuple

from scipy.stats import spearmanr

from experiments.matrix_runner import (
    FAILURE_TARGET_COUNT,
    OBSERVATION_COMPLETENESS_LEVELS,
    TOPOLOGY_LEVELS,
    _PULSE_CYCLES,
    _PULSE_INTENSITY_RANGE,
    _PULSE_PACKETS_PER_NODE,
    _WAVE_GAP_SECONDS,
    _actual_outcome_from_ground_truth,
    _ground_truth_nx,
    _pick_failure_targets,
)
from experiments.observation_sampling import sample_packets
from experiments.synthetic_traffic import assign_ips, build_ground_truth_graph, generate_packets_for_scenario
from experiments.uncertainty import PropagatedUncertainty, propagate

SEEDS: List[int] = [42, 43, 44]
DRAWS = 20
STAGES = ("topology", "dependency", "pathforge")


@dataclass(frozen=True)
class UncertaintyRow:
    level: str
    completeness: float
    seed: int
    widths: Dict[str, float]  # per stage, plus "combined"
    edge_brier_bootstrap: float
    edge_brier_point: float
    edge_blind_rate: float
    affected_brier_bootstrap: Optional[float]
    affected_brier_point: Optional[float]


def _brier(pairs: Sequence[Tuple[float, float]]) -> float:
    return fmean((p - y) ** 2 for p, y in pairs) if pairs else float("nan")


def run_cell(level: str, completeness: float, seed: int, scratch: Path, draws: int = DRAWS) -> UncertaintyRow:
    roles, edges = TOPOLOGY_LEVELS[level]()
    ip_by_name = assign_ips(list(roles))
    packets = generate_packets_for_scenario(
        roles, edges, ip_by_name, f"unc-{level}", seed, packets_per_edge=15, wave_2_edges=max(1, len(edges) // 4),
        wave_gap_seconds=_WAVE_GAP_SECONDS, pulse_cycles=_PULSE_CYCLES,
        pulse_packets_per_node=_PULSE_PACKETS_PER_NODE, pulse_intensity_range=_PULSE_INTENSITY_RANGE,
    )
    observed = sample_packets(packets, completeness, seed)

    gt_graph = build_ground_truth_graph(roles, edges, ip_by_name, graph_id="unc-gt")
    target_names = [t.node_id for t in _pick_failure_targets(gt_graph, FAILURE_TARGET_COUNT)]
    unc: PropagatedUncertainty = propagate(
        observed, scratch, [ip_by_name[n] for n in target_names], draws=draws, seed=seed
    )

    truth_edges = {frozenset((ip_by_name[e.source], ip_by_name[e.target])) for e in edges}
    universe = truth_edges | set(unc.edge_presence) | set(unc.point.edge_confidence)
    boot = [(unc.edge_presence.get(k, 0.0), 1.0 if k in truth_edges else 0.0) for k in universe]
    point = [(unc.point.edge_confidence.get(k, 0.0), 1.0 if k in truth_edges else 0.0) for k in universe]
    blind = fmean(1.0 if unc.edge_presence.get(k, 0.0) == 0.0 else 0.0 for k in truth_edges)

    gt_nx = _ground_truth_nx(roles, edges)
    boot_aff: List[Tuple[float, float]] = []
    point_aff: List[Tuple[float, float]] = []
    for name in target_names:
        ip = ip_by_name[name]
        if ip not in unc.affected_probability:
            continue
        truth, _, _ = _actual_outcome_from_ground_truth(gt_nx, name, dict(ip_by_name), [])
        point_set = unc.point.affected.get(ip) or set()
        for node_ip in ip_by_name.values():
            y = 1.0 if node_ip in truth else 0.0
            boot_aff.append((unc.affected_probability[ip].get(node_ip, 0.0), y))
            point_aff.append((1.0 if node_ip in point_set else 0.0, y))

    widths = dict(unc.stage_width)
    widths["combined"] = fmean(widths[s] for s in STAGES)
    return UncertaintyRow(
        level, completeness, seed, widths, _brier(boot), _brier(point), blind,
        _brier(boot_aff) if boot_aff else None, _brier(point_aff) if point_aff else None,
    )


def run_benchmark(
    root: Path,
    levels: Optional[Sequence[str]] = None,
    completeness: Sequence[float] = tuple(OBSERVATION_COMPLETENESS_LEVELS),
    seeds: Sequence[int] = tuple(SEEDS),
    draws: int = DRAWS,
) -> List[UncertaintyRow]:
    scratch = root / "uncertainty_scratch"
    return [
        run_cell(level, c, seed, scratch, draws)
        for level in (levels or list(TOPOLOGY_LEVELS)) for c in completeness for seed in seeds
    ]


@dataclass(frozen=True)
class MonotonicityResult:
    mean_width: Dict[float, Dict[str, float]]  # completeness -> stage -> mean width
    paired_wider: Dict[str, Tuple[int, int, int]]  # stage -> (lowest wider, tie, lowest narrower) over (level, seed)
    spearman: Dict[str, Tuple[float, float]]  # stage -> (rho, p) of width vs (1 - completeness)
    criterion_met: bool  # combined: lowest > highest on a strict majority of (level, seed) pairs


def monotonicity(rows: Sequence[UncertaintyRow]) -> MonotonicityResult:
    cs = sorted({r.completeness for r in rows})
    lo, hi = cs[0], cs[-1]
    all_stages = (*STAGES, "combined")
    mean_width = {
        c: {s: fmean(r.widths[s] for r in rows if r.completeness == c) for s in all_stages} for c in cs
    }
    by_lo = {(r.level, r.seed): r for r in rows if r.completeness == lo}
    by_hi = {(r.level, r.seed): r for r in rows if r.completeness == hi}
    paired: Dict[str, Tuple[int, int, int]] = {}
    spearman: Dict[str, Tuple[float, float]] = {}
    for s in all_stages:
        diffs = [by_lo[k].widths[s] - by_hi[k].widths[s] for k in by_lo if k in by_hi]
        paired[s] = (sum(d > 1e-12 for d in diffs), sum(abs(d) <= 1e-12 for d in diffs), sum(d < -1e-12 for d in diffs))
        ys = [r.widths[s] for r in rows]
        if len(set(ys)) < 2:  # constant width (e.g. PathForge on chains): correlation undefined, said so
            spearman[s] = (float("nan"), float("nan"))
            continue
        rho, p = spearmanr([1 - r.completeness for r in rows], ys)
        spearman[s] = (float(rho), float(p))
    wider, tie, narrower = paired["combined"]
    return MonotonicityResult(mean_width, paired, spearman, wider > (wider + tie + narrower) / 2)


def format_report(rows: Sequence[UncertaintyRow]) -> str:
    m = monotonicity(rows)
    lines = ["| completeness | topology width | dependency width | pathforge width | combined |", "|---|---|---|---|---|"]
    for c in sorted(m.mean_width, reverse=True):
        w = m.mean_width[c]
        lines.append(f"| {c:g} | {w['topology']:.4f} | {w['dependency']:.4f} | {w['pathforge']:.4f} | {w['combined']:.4f} |")
    lines += ["", "| stage | lowest wider / tie / narrower (per level x seed) | Spearman rho (p) vs 1-completeness |", "|---|---|---|"]
    for s in (*STAGES, "combined"):
        a, b, c = m.paired_wider[s]
        rho, p = m.spearman[s]
        lines.append(f"| {s} | {a} / {b} / {c} | {rho:+.3f} ({p:.3g}) |")
    lines += ["", "pre-registered criterion (combined, lowest wider than highest on a majority): "
                  f"{'MET' if m.criterion_met else 'NOT MET'}", ""]
    lines += ["| completeness | edge Brier bootstrap | edge Brier point conf | blind-edge rate | "
              "affected Brier bootstrap | affected Brier point |", "|---|---|---|---|---|---|"]
    for c in sorted({r.completeness for r in rows}, reverse=True):
        rs = [r for r in rows if r.completeness == c]
        ab = [r.affected_brier_bootstrap for r in rs if r.affected_brier_bootstrap is not None]
        ap = [r.affected_brier_point for r in rs if r.affected_brier_point is not None]
        lines.append(
            f"| {c:g} | {fmean(r.edge_brier_bootstrap for r in rs):.4f} | {fmean(r.edge_brier_point for r in rs):.4f} | "
            f"{fmean(r.edge_blind_rate for r in rs):.3f} | {fmean(ab) if ab else float('nan'):.4f} | "
            f"{fmean(ap) if ap else float('nan'):.4f} |")
    return "\n".join(lines)
