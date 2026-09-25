"""Red-team benchmark: measured degradation under crafted traffic, hardening, re-measurement (spec Phase 84).

For each attack (`attacks.ATTACKS`) and each (topology level, seed) unit, the same stage is scored on:
  clean            the honest traffic, default pipeline
  attacked         the crafted traffic, default pipeline
  clean_hardened   the honest traffic, hardened pipeline           (guard: hardening must not cost clean accuracy)
  attacked_hardened the crafted traffic, hardened pipeline
Every metric is oriented "higher is better" (`PRIMARY`): topology node/edge F1, role "not confidently wrong" rate on
the attacked node, anomaly recall. An attack SUCCEEDS if mean(clean) - mean(attacked) exceeds the clean metric's own
across-unit standard deviation (rule fixed before the run). A fix WORKS if the hardened attacked score recovers more
than that spread over the unhardened attacked score, and it is ACCEPTED only if clean_hardened stays within that
spread of clean. Ground truth (declared roles / edges) is used only to score.
"""

from __future__ import annotations

import shutil
from datetime import timedelta
import statistics
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from backend.app.models.anomaly import AnomalyDimension
from backend.app.models.behavior import ObservationWindow, ServiceRole
from backend.flowmind.anomaly.node_anomaly import detect_node_anomalies, detect_sustained_drift
from backend.flowmind.baseline.node_baseline import build_anchored_baseline, build_node_baseline
from backend.flowmind.classification.role_classifier import (
    classify_node_role,
    classify_node_role_robust,
    fit_role_model,
)
from backend.flowmind.fingerprints.node_fingerprint import assemble_node_fingerprint
from backend.nettrace.reconstruct import reconstruct_flows
from backend.nettrace.topology.discovery import discover_nodes
from backend.nettrace.topology.graph import build_topology_graph
from experiments.adversarial import attacks as A
from experiments.anomaly_fingerprints import fingerprints_from_flows
from experiments.artifacts.io import write_jsonl
from experiments.artifacts.paths import packets_path
from experiments.matrix_runner import (
    TOPOLOGY_LEVELS,
    _PULSE_CYCLES,
    _PULSE_INTENSITY_RANGE,
    _PULSE_PACKETS_PER_NODE,
    _WAVE_GAP_SECONDS,
)
from experiments.metrics.anomaly_evaluation import LabeledAnomalyEvent, evaluate_anomaly_detection
from experiments.metrics.topology_comparison import compare_topology_to_ground_truth
from experiments.synthetic_traffic import BASE_TIME, assign_ips, build_ground_truth_graph, generate_packets_for_scenario

LEVELS: Tuple[str, ...] = ("small", "medium", "large", "multi_path", "dynamic")
SEEDS: Tuple[int, ...] = (42, 43, 44)
MIN_EDGE_BIDIRECTIONALITY = 0.15  # hardening parameters; provisional, reported
OOD_MAX_Z = 4.0
DETECTOR_DIMENSION_COUNT = 6

PRIMARY: Dict[str, str] = {
    "spoofed_sources": "node_f1",
    "decoy_chatter": "edge_f1",
    "ip_aliasing": "node_f1",
    "role_mimicry": "not_confidently_wrong",
    "fingerprint_noise": "not_confidently_wrong",
    "low_and_slow": "recall",
    "baseline_poisoning": "recall",
    "minimal_burst": "recall",
}
HARDENING: Dict[str, str] = {
    "topology": f"edges need >= {MIN_EDGE_BIDIRECTIONALITY} bidirectionality; isolated nodes dropped",
    "role": f"abstain (uniform posterior) when a feature is > {OOD_MAX_Z} scale units from every role",
    "anomaly": "baseline from the oldest 5 epochs only + detect_sustained_drift (3 rising epochs, each >= 1.5 MADs)",
}


@dataclass(frozen=True)
class Cell:
    attack: str
    level: str
    seed: int
    variant: str  # clean | attacked | clean_hardened | attacked_hardened
    metrics: Dict[str, float]


def _scenario_packets(level: str, seed: int):
    roles, edges = TOPOLOGY_LEVELS[level]()
    ips = assign_ips(list(roles))
    packets = generate_packets_for_scenario(
        roles, edges, ips, "adv", seed, packets_per_edge=15, wave_2_edges=max(1, len(edges) // 4),
        wave_gap_seconds=_WAVE_GAP_SECONDS, pulse_cycles=_PULSE_CYCLES,
        pulse_packets_per_node=_PULSE_PACKETS_PER_NODE, pulse_intensity_range=_PULSE_INTENSITY_RANGE,
    )
    return roles, edges, ips, packets


def _in_scratch(scratch: Path, fn: Callable[[Path], Dict[str, float]]) -> Dict[str, float]:
    scratch.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(dir=scratch))
    try:
        return fn(work)
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ------------------------------------------------------------------ topology
def _topology_packets(attack: Optional[str], level: str, seed: int):
    roles, edges, ips, packets = _scenario_packets(level, seed)
    victim = A.pick_actor(edges) or sorted(roles)[0]
    if attack == "spoofed_sources":
        packets = A.spoofed_sources(packets, list(ips.values()), seed)
    elif attack == "decoy_chatter":
        packets = A.decoy_chatter(packets, ips, edges, seed)
    elif attack == "ip_aliasing":
        packets = A.ip_aliasing(packets, ips[victim], seed)
    elif attack is not None:
        raise ValueError(attack)
    return roles, edges, ips, packets


def topology_cell(attack: Optional[str], level: str, seed: int, hardened: bool, scratch: Path) -> Dict[str, float]:
    roles, edges, ips, packets = _topology_packets(attack, level, seed)

    def run(work: Path) -> Dict[str, float]:
        write_jsonl(packets_path(work, "adv"), packets)
        reconstruct_flows(work, "adv")
        graph = build_topology_graph(
            work, "adv", graph_id="adv-g",
            min_edge_bidirectionality=MIN_EDGE_BIDIRECTIONALITY if hardened else 0.0,
        )
        truth = build_ground_truth_graph(roles, edges, ips, graph_id="adv-gt")
        r = compare_topology_to_ground_truth(graph, truth)
        return {"node_f1": r.node_f1, "edge_f1": r.edge_f1, "inferred_nodes": float(r.inferred_node_count),
                "inferred_edges": float(r.inferred_edge_count)}

    return _in_scratch(scratch, run)


# ------------------------------------------------------------------ role
def _role_outcome(work: Path, packets, roles, ips, attacker: str, mimic_role: ServiceRole, hardened: bool) -> Dict[str, float]:
    write_jsonl(packets_path(work, "adv"), packets)
    flows = reconstruct_flows(work, "adv")
    nodes = discover_nodes(work, "adv")
    name_of = {ip: n for n, ip in ips.items()}
    at = BASE_TIME + timedelta(seconds=_WAVE_GAP_SECONDS + 60)  # the matrix's own fingerprint time
    labeled = {}
    for node in nodes:
        name = name_of.get(str(node.ip_addresses[0]))
        if name is not None:
            labeled[name] = (assemble_node_fingerprint(flows, node, ObservationWindow.MEDIUM, computed_at=at),
                             roles[name])
    train = [v for n, v in labeled.items() if n != attacker]
    fp, true_role = labeled[attacker]
    model = fit_role_model(train)
    cls = classify_node_role_robust(model, fp, max_feature_z=OOD_MAX_Z) if hardened else classify_node_role(model, fp)
    probs = cls.role_probabilities
    top = max(probs, key=probs.get)
    abstained = len(probs) > 1 and max(probs.values()) - min(probs.values()) < 1e-9
    correct = top == true_role and not abstained
    confident_wrong = (top != true_role) and not abstained and probs[top] > 0.5
    return {"correct": float(correct), "abstained": float(abstained),
            "not_confidently_wrong": float(not confident_wrong),
            "fooled_into_mimic": float(top == mimic_role and not abstained)}


def _pick_role_attacker(roles, ips, packets, scratch: Path) -> Optional[Tuple[str, ServiceRole]]:
    """The attack can only degrade a classification that was right: the first node (by name) that shares its role
    with another node, has a different role to imitate, and that the DEFAULT classifier gets right on clean
    traffic. Chosen on clean traffic only, so clean and attacked cells share the attacker."""
    for name in sorted(roles):
        siblings = [n for n in roles if n != name and roles[n] == roles[name]]
        others = sorted({r for r in roles.values() if r != roles[name]}, key=lambda r: r.value)
        if not siblings or not others:
            continue
        outcome = _in_scratch(scratch, lambda w: _role_outcome(w, packets, roles, ips, name, others[0], False))
        if outcome["correct"] == 1.0:
            return name, others[0]
    return None


def role_cell(attack: Optional[str], level: str, seed: int, hardened: bool, scratch: Path) -> Optional[Dict[str, float]]:
    roles, edges, ips, packets = _scenario_packets(level, seed)
    picked = _pick_role_attacker(roles, ips, packets, scratch)
    if picked is None:
        return None
    attacker, mimic_role = picked
    real_ips = list(ips.values())
    if attack == "role_mimicry":
        packets = A.role_mimicry(packets, ips[attacker], real_ips, mimic_role, seed)
    elif attack == "fingerprint_noise":
        packets = A.fingerprint_noise(packets, ips[attacker], real_ips, seed)
    elif attack is not None:
        raise ValueError(attack)
    return _in_scratch(scratch, lambda w: _role_outcome(w, packets, roles, ips, attacker, mimic_role, hardened))


# ------------------------------------------------------------------ anomaly
def anomaly_cell(attack: str, level: str, seed: int, hardened: bool, scratch: Path) -> Optional[Dict[str, float]]:
    """`attack` is a Phase 84 attack name or "clean:<pattern>" with pattern volume|burst."""
    roles, edges = TOPOLOGY_LEVELS[level]()
    ips = assign_ips(list(roles))
    if attack in ("low_and_slow", "baseline_poisoning"):
        dataset = A.volume_dataset(roles, edges, ips, "adv", seed, attack)
    elif attack == "clean:volume":
        dataset = A.volume_dataset(roles, edges, ips, "adv", seed, "clean")
    elif attack == "minimal_burst":
        dataset = A.burst_dataset(roles, edges, ips, "adv", seed, "minimal_burst")
    elif attack == "clean:burst":
        dataset = A.burst_dataset(roles, edges, ips, "adv", seed, "clean")
    else:
        raise ValueError(attack)
    if dataset is None:
        return None

    def run(work: Path) -> Dict[str, float]:
        write_jsonl(packets_path(work, "adv-anomaly"), dataset.packets)
        flows = reconstruct_flows(work, "adv-anomaly")
        nodes = discover_nodes(work, "adv-anomaly")
        fingerprints = fingerprints_from_flows(flows, dataset, nodes)
        node_id_of = {str(n.ip_addresses[0]): n.node_id for n in nodes}

        detected = []
        for node in nodes:
            history = fingerprints[node.node_id]
            past = history[: dataset.baseline_epochs]
            baseline = build_anchored_baseline(past) if hardened else build_node_baseline(past)
            test = history[dataset.baseline_epochs:]
            for fp in test:
                detected.extend(detect_node_anomalies(baseline, fp))
            if hardened:
                detected.extend(detect_sustained_drift(baseline, test))

        labels = [
            LabeledAnomalyEvent(node_id=node_id_of[ips[name]], dimension=AnomalyDimension(dim),
                                onset_at=dataset.epoch_start(dataset.label_epoch))
            for name, dim in dataset.label_pairs if ips[name] in node_id_of
        ]
        if not labels:
            return {}
        total = len(nodes) * DETECTOR_DIMENSION_COUNT * dataset.test_epochs
        ev = evaluate_anomaly_detection(detected, labels, total_checks=total)
        return {"recall": ev.recall, "precision": ev.precision, "false_positives": float(ev.false_positive_count),
                "latency_seconds": (ev.mean_detection_latency_seconds
                                    if ev.mean_detection_latency_seconds is not None else float("nan"))}

    out = _in_scratch(scratch, run)
    return out or None


_CLEAN_ANOMALY = {"low_and_slow": "clean:volume", "baseline_poisoning": "clean:volume", "minimal_burst": "clean:burst"}


def run_attack(attack: A.Attack, root: Path, levels: Sequence[str] = LEVELS, seeds: Sequence[int] = SEEDS) -> List[Cell]:
    scratch = root / "adversarial_scratch"
    cells: List[Cell] = []
    for level in levels:
        for seed in seeds:
            for hardened in (False, True):
                if attack.stage == "topology":
                    clean = topology_cell(None, level, seed, hardened, scratch)
                    hit = topology_cell(attack.name, level, seed, hardened, scratch)
                elif attack.stage == "role":
                    clean = role_cell(None, level, seed, hardened, scratch)
                    hit = role_cell(attack.name, level, seed, hardened, scratch)
                else:
                    clean = anomaly_cell(_CLEAN_ANOMALY[attack.name], level, seed, hardened, scratch)
                    hit = anomaly_cell(attack.name, level, seed, hardened, scratch)
                if clean is None or hit is None:
                    continue
                suffix = "_hardened" if hardened else ""
                cells.append(Cell(attack.name, level, seed, "clean" + suffix, clean))
                cells.append(Cell(attack.name, level, seed, "attacked" + suffix, hit))
    return cells


@dataclass(frozen=True)
class AttackSummary:
    attack: str
    stage: str
    metric: str
    units: int
    clean: float
    attacked: float
    clean_spread: float
    degradation: float
    succeeded: bool
    clean_hardened: float
    attacked_hardened: float
    recovery: float  # attacked_hardened - attacked
    hardening_works: bool
    hardening_accepted: bool  # clean_hardened within clean spread of clean
    notes: str = ""


def _mean(cells: Sequence[Cell], variant: str, metric: str) -> float:
    vals = [c.metrics[metric] for c in cells if c.variant == variant]
    return statistics.fmean(vals) if vals else float("nan")


def summarize(attack: A.Attack, cells: Sequence[Cell]) -> AttackSummary:
    metric = PRIMARY[attack.name]
    mine = [c for c in cells if c.attack == attack.name]
    clean_vals = [c.metrics[metric] for c in mine if c.variant == "clean"]
    spread = statistics.stdev(clean_vals) if len(clean_vals) >= 2 else 0.0
    clean, hit = _mean(mine, "clean", metric), _mean(mine, "attacked", metric)
    ch, ah = _mean(mine, "clean_hardened", metric), _mean(mine, "attacked_hardened", metric)
    degradation = clean - hit
    tol = max(spread, 1e-9)
    return AttackSummary(
        attack.name, attack.stage, metric, len(clean_vals), clean, hit, spread, degradation, degradation > tol,
        ch, ah, ah - hit, (ah - hit) > tol, abs(ch - clean) <= tol,
    )


def run_benchmark(root: Path, levels: Sequence[str] = LEVELS, seeds: Sequence[int] = SEEDS,
                  attacks: Sequence[A.Attack] = A.ATTACKS) -> Tuple[List[Cell], List[AttackSummary]]:
    cells: List[Cell] = []
    for attack in attacks:
        cells += run_attack(attack, root, levels, seeds)
    return cells, [summarize(a, cells) for a in attacks]


def verdict(s: AttackSummary) -> str:
    if not s.succeeded:
        return "not successful"
    if s.hardening_works and s.hardening_accepted:
        return "successful -> FIXED"
    if s.hardening_works:
        return "successful -> fix costs clean accuracy (rejected)"
    return "successful -> OPEN (not fixed)"


def format_report(summaries: Sequence[AttackSummary]) -> str:
    lines = ["| attack | stage | metric | units | clean | attacked | clean spread | degradation | "
             "hardened clean | hardened attacked | verdict |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for s in summaries:
        lines.append(
            f"| {s.attack} | {s.stage} | {s.metric} | {s.units} | {s.clean:.3f} | {s.attacked:.3f} | "
            f"{s.clean_spread:.3f} | {s.degradation:+.3f} | {s.clean_hardened:.3f} | {s.attacked_hardened:.3f} | "
            f"{verdict(s)} |")
    lines += ["", "hardening: " + "; ".join(f"{k}: {v}" for k, v in HARDENING.items())]
    return "\n".join(lines)


def secondary_report(cells: Sequence[Cell]) -> str:
    """Numbers the primary metric hides: anomaly detection latency and false alarms, and how often role attacks
    flip the default classifier to a wrong / the imitated role (or make the hardened one abstain)."""
    lines = ["| attack | variant | mean latency (s) | mean false positives |", "|---|---|---|---|"]
    for name in ("low_and_slow", "baseline_poisoning", "minimal_burst"):
        for variant in ("clean", "attacked", "clean_hardened", "attacked_hardened"):
            cs = [c for c in cells if c.attack == name and c.variant == variant]
            lat = [c.metrics["latency_seconds"] for c in cs if c.metrics["latency_seconds"] == c.metrics["latency_seconds"]]
            if cs:
                lines.append(f"| {name} | {variant} | {statistics.fmean(lat) if lat else float('nan'):.1f} | "
                             f"{statistics.fmean(c.metrics['false_positives'] for c in cs):.1f} |")
    lines += ["", "| attack | variant | correct | abstained | fooled into imitated role |", "|---|---|---|---|---|"]
    for name in ("role_mimicry", "fingerprint_noise"):
        for variant in ("clean", "attacked", "clean_hardened", "attacked_hardened"):
            cs = [c for c in cells if c.attack == name and c.variant == variant]
            if cs:
                m = lambda k: statistics.fmean(c.metrics[k] for c in cs)
                lines.append(f"| {name} | {variant} | {m('correct'):.2f} | {m('abstained'):.2f} | {m('fooled_into_mimic'):.2f} |")
    return "\n".join(lines)
