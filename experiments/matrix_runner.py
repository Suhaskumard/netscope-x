"""Full Experimental Matrix runner (spec Phase 68, FR-1.40: "a full
experimental matrix (topology complexity x observation-completeness
sweep) with reproducible, quantitatively evaluated results ... and the
four minimum ablation studies").

Orchestration only -- reimplements no pipeline stage. Every real number
this module produces comes from actually calling the real, already-built
functions from Phases 22-67 against a real (synthetic, non-Docker)
packet capture, then scoring the real output against ground truth via
Phase 32/37/63/66's existing evaluation modules plus this phase's two new
ones (`causal_evaluation.py`, `temporal_evaluation.py`).

## Scope (see docs/architecture/experimental_matrix.md for the full
   decision record)

Six of `MetricContext`'s seven values are scored for real:
`topology_reconstruction`, `role_inference`, `temporal_analysis`,
`causal_analysis`, `pathforge`, `counterfactual`. `anomaly_detection` is
not run -- no anomaly-injection dataset generator exists anywhere in this
repository (`experiments/metrics/anomaly_evaluation.py`'s own docstring
already calls building one "a separate, much larger capability nobody
has asked for"), and this phase does not build one either.

## Topology-complexity mapping

The spec's own vocabulary ("small/medium/large/multi-path/multi-service/
dynamic", `docs/research/research_questions.md`) does not literally match
Phase 18's six generator function names (`simple_chain`/`star`/
`multi_tier`/`redundant`/`multi_path`/`dynamic_service_network`,
`simulator/scenarios/topologies.py`). `TOPOLOGY_LEVELS` below is the
resolving, documented interpretation -- sizes chosen to keep a full sweep
fast, not to match any particular real deployment.

## "Actual outcome" without Docker

RQ6/RQ7 score a prediction against what "actually" happened. This session
has no Docker, so there is no live network to fail for real. The honest
substitute used here: the SAME declared ground-truth topology
(`synthetic_traffic.build_ground_truth_graph`) that `topology_reconstruction`
is already scored against IS the real, true network for this synthetic
experiment -- exactly the same stance `topology_comparison.py` already
takes (ground truth is treated as truth, not as another prediction).
`_actual_outcome_from_ground_truth` independently recomputes connectivity
on the *ground-truth* graph with the same node genuinely removed (never
by reusing the *inferred* prediction's own graph, which would make the
scoring tautological) -- a real, if synthetic-network, "actual" outcome,
not a live capture but also not fabricated.

## Ablations: real code paths, not code forks

Each of the four ablations changes one real, already-existing parameter
or post-processes one real, already-computed list -- never a parallel
reimplementation:

- **without_temporal**: every `DependencyEdge.temporal_precedence_score`
  forced to `0.0` before `generate_causal_candidates` -- Phase 53's own
  gate (`temporal_precedence_score > 0.0` required) then promotes zero
  candidates, so propagation-based predictions collapse to empty. A real,
  usually severe, effect -- this codebase's causal-candidate promotion
  structurally *requires* temporal evidence, so this ablation is a direct,
  faithful test of that requirement, not a synthetic stand-in.
- **without_dependency_weighting**: every `DependencyEdge.strength`
  replaced with a binary `1.0 if frequency > 0 else 0.0` (existence, not
  Phase 51's multi-signal weighting) before candidate generation --
  changes which edges clear the strength threshold.
- **without_confidence_modeling**: the topology graph and dependency
  estimation are rebuilt with `edge_confidence_signal_strength=0.0` --
  Phase 31's five non-volume-derived confidence signals are switched off,
  leaving only raw packet-volume-derived confidence. A real parameter
  this project already exposes, not a fabricated override.
- **without_behavioral**: `role_classifications` is omitted (`None`) when
  calling `run_failure_propagation_pipeline`/`compare_counterfactual_outcome`.
  Verified, not assumed: neither function's scored fields (affected
  nodes, route changes, connectivity, resilience) read
  `role_classifications` at all -- only `ServiceImpact.role_classification`,
  an unscored annotation field. So this ablation's real, honestly-reported
  result is a genuine null: identical accuracy to the baseline, because
  behavioral features are architecturally disconnected from PathForge/
  counterfactual prediction accuracy in this codebase as it exists today
  -- a real finding, not a placeholder.

## MetricResult field mapping

`MetricResult` (`backend/app/models/metric.py`) has one shared
precision/recall/f1/graph_similarity/calibration_error/detection_latency
shape across all 7 contexts -- it does not have a slot for every field
each evaluation dataclass produces (e.g. `path_prediction_match_rate`,
`connectivity_prediction_accuracy`). Each context maps its most direct
analogue onto the shared fields (documented per-context below in
`_to_metric_result`); the FULL raw evaluation dataclass (via `asdict`) is
preserved losslessly in `Experiment.results`, never discarded.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import networkx as nx

from backend.app.models.behavior import ObservationWindow, ServiceRole
from backend.app.models.experiment import Experiment
from backend.app.models.failure import FailureScenario, FailureType
from backend.app.models.metric import MetricContext, MetricResult
from backend.app.models.simulation import CounterfactualAction, CounterfactualScenario
from backend.app.models.snapshot import ChangeType
from backend.archaeology.diff import diff_snapshots
from backend.archaeology.snapshots import create_snapshot
from backend.dependency.causal_candidates import generate_causal_candidates
from backend.dependency.strength import estimate_dependency_strength
from backend.flowmind.classification.role_classifier import classify_node_role, fit_role_model
from backend.flowmind.fingerprints.node_fingerprint import assemble_node_fingerprint
from backend.nettrace.reconstruct import reconstruct_flows
from backend.nettrace.topology.graph import build_topology_graph
from backend.simulation.counterfactual_comparison import compare_counterfactual_outcome
from backend.simulation.counterfactual_engine import execute_counterfactual_scenario
from backend.simulation.failure_propagation_pipeline import run_failure_propagation_pipeline
from backend.simulation.resilience_indicators import compute_resilience_indicators
from experiments.artifacts.io import write_json, write_jsonl
from experiments.artifacts.paths import experiment_path, metrics_path, packets_path
from experiments.metrics.causal_evaluation import evaluate_causal_analysis
from experiments.metrics.counterfactual_validation import (
    ActualCounterfactualOutcome,
    evaluate_counterfactual_prediction,
)
from experiments.metrics.failure_propagation_validation import (
    ActualFailureOutcome,
    evaluate_failure_propagation_prediction,
)
from experiments.metrics.role_calibration import evaluate_role_calibration
from experiments.metrics.temporal_evaluation import LabeledTopologyEvent, evaluate_temporal_analysis
from experiments.metrics.topology_comparison import compare_topology_to_ground_truth
from experiments.observation_sampling import sample_packets
from experiments.synthetic_traffic import assign_ips, build_ground_truth_graph, generate_packets_for_scenario
from simulator.scenarios.topologies import (
    ScenarioEdge,
    dynamic_service_network,
    multi_path,
    multi_tier,
    simple_chain,
    star,
)

TOPOLOGY_LEVELS: Dict[str, Callable[[], Tuple[Dict[str, ServiceRole], List[ScenarioEdge]]]] = {
    "small": lambda: simple_chain(3),
    "medium": lambda: star(6),
    "large": lambda: multi_tier([2, 4, 4, 2]),
    "multi_path": lambda: multi_path(3),
    "multi_service": lambda: star(10),
    "dynamic": lambda: dynamic_service_network(seed=42, n=8),
}

OBSERVATION_COMPLETENESS_LEVELS: List[float] = [1.0, 0.9, 0.75, 0.5, 0.25]

ABLATIONS = ("without_temporal", "without_dependency_weighting", "without_confidence_modeling", "without_behavioral")

_WAVE_GAP_SECONDS = 300.0
_BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True)
class MatrixCellResult:
    experiment: Experiment
    metrics: List[MetricResult]
    raw_evaluations: Dict[str, Any]


def _sanitize(text: str) -> str:
    return text.replace(".", "p")


def _reverse_lookup(ip_by_name: Dict[str, str]) -> Dict[str, str]:
    return {ip: name for name, ip in ip_by_name.items()}


def _name_to_node_id(nodes, ip_by_name: Dict[str, str]) -> Dict[str, str]:
    ip_to_name = _reverse_lookup(ip_by_name)
    mapping: Dict[str, str] = {}
    for node in nodes:
        for ip in node.ip_addresses:
            name = ip_to_name.get(str(ip))
            if name is not None:
                mapping[name] = node.node_id
                break
    return mapping


def _ground_truth_nx(roles: Dict[str, ServiceRole], edges: List[ScenarioEdge]) -> nx.Graph:
    g = nx.Graph()
    g.add_nodes_from(roles.keys())
    for e in edges:
        g.add_edge(e.source, e.target)
    return g


def _actual_outcome_from_ground_truth(
    gt_nx: nx.Graph, failed_name: str, name_to_node_id: Dict[str, str], pairs: List[Tuple[str, str]]
) -> Tuple[Set[str], List[str], Dict[Tuple[str, str], bool]]:
    """Removes `failed_name` from the ground-truth graph and derives the
    real (if synthetic-network) actual outcome -- see module docstring."""
    node_id_to_name = {v: k for k, v in name_to_node_id.items()}

    after = gt_nx.copy()
    if failed_name in after:
        after.remove_node(failed_name)

    components = list(nx.connected_components(after)) if after.number_of_nodes() > 0 else []
    largest = max(components, key=len, default=set())
    stranded_names = {n for n in after.nodes if n not in largest}
    actually_affected = {name_to_node_id[n] for n in stranded_names if n in name_to_node_id}
    actual_largest_ids = [name_to_node_id[n] for n in largest if n in name_to_node_id]

    actual_reachable_pairs: Dict[Tuple[str, str], bool] = {}
    for source_id, target_id in pairs:
        source_name = node_id_to_name.get(source_id)
        target_name = node_id_to_name.get(target_id)
        if source_name is None or target_name is None or source_name not in after or target_name not in after:
            continue
        actual_reachable_pairs[(source_id, target_id)] = nx.has_path(after, source_name, target_name)

    return actually_affected, actual_largest_ids, actual_reachable_pairs


def _pick_failed_name(roles: Dict[str, ServiceRole], edges: List[ScenarioEdge]) -> str:
    """The declared node with the most incident edges -- the structurally
    most consequential real target for a failure/counterfactual scenario."""
    degree: Dict[str, int] = {name: 0 for name in roles}
    for e in edges:
        degree[e.source] = degree.get(e.source, 0) + 1
        degree[e.target] = degree.get(e.target, 0) + 1
    return max(degree, key=lambda name: degree[name])


def _to_metric_result(context: MetricContext, experiment_id: str, raw: Any) -> MetricResult:
    """Maps each evaluation dataclass's most direct analogue onto
    `MetricResult`'s shared fields (see module docstring); the full `raw`
    dataclass is kept separately in `Experiment.results`."""
    kwargs: Dict[str, Any] = {"metric_id": f"{experiment_id}:{context.value}", "experiment_id": experiment_id, "context": context, "computed_at": datetime.now(timezone.utc)}

    if context == MetricContext.TOPOLOGY_RECONSTRUCTION:
        kwargs.update(precision=raw.edge_precision, recall=raw.edge_recall, f1=raw.edge_f1, graph_similarity=raw.graph_similarity)
    elif context == MetricContext.ROLE_INFERENCE:
        kwargs.update(precision=raw.accuracy, calibration_error=raw.expected_calibration_error)
    elif context == MetricContext.TEMPORAL_ANALYSIS:
        kwargs.update(precision=raw.precision, recall=raw.recall, f1=raw.f1, detection_latency_seconds=raw.mean_detection_latency_seconds)
    elif context == MetricContext.CAUSAL_ANALYSIS:
        kwargs.update(precision=raw.dependency_precision, recall=raw.dependency_recall, f1=raw.dependency_f1)
    elif context in (MetricContext.PATHFORGE, MetricContext.COUNTERFACTUAL):
        kwargs.update(precision=raw.affected_node_precision, recall=raw.affected_node_recall, f1=raw.affected_node_f1)

    return MetricResult(**kwargs)


def run_matrix_cell(
    root: Path,
    topology_level: str,
    completeness: float,
    seed: int = 42,
    ablation: Optional[str] = None,
    packets_per_edge: int = 15,
) -> MatrixCellResult:
    """Runs one (topology_level, completeness[, ablation]) cell of the
    experimental matrix for real: generates a scenario, synthesizes and
    samples packets, runs the real pipeline, and scores every applicable
    `MetricContext` against ground truth. Raises `KeyError` for an unknown
    `topology_level`, `ValueError` for an unknown `ablation`.
    """
    if topology_level not in TOPOLOGY_LEVELS:
        raise KeyError(f"unknown topology_level {topology_level!r}; choose from {sorted(TOPOLOGY_LEVELS)}")
    if ablation is not None and ablation not in ABLATIONS:
        raise ValueError(f"unknown ablation {ablation!r}; choose from {ABLATIONS}")

    experiment_id = f"matrix-{topology_level}-{_sanitize(str(completeness))}-{ablation or 'baseline'}-{seed}"
    capture_id = experiment_id
    raw_evaluations: Dict[str, Any] = {}
    metrics: List[MetricResult] = []

    roles, edges = TOPOLOGY_LEVELS[topology_level]()
    names = list(roles.keys())
    ip_by_name = assign_ips(names)
    wave_2_edges = max(1, len(edges) // 4)

    packets = generate_packets_for_scenario(
        roles, edges, ip_by_name, capture_id, seed,
        packets_per_edge=packets_per_edge, wave_2_edges=wave_2_edges, wave_gap_seconds=_WAVE_GAP_SECONDS,
    )
    sampled = sample_packets(packets, completeness, seed)
    write_jsonl(packets_path(root, capture_id), sampled)
    flows = reconstruct_flows(root, capture_id)

    edge_confidence_signal_strength = 0.0 if ablation == "without_confidence_modeling" else 0.3

    wave1_cutoff = _BASE_TIME + timedelta(seconds=_WAVE_GAP_SECONDS / 2)
    wave2_end = _BASE_TIME + timedelta(seconds=_WAVE_GAP_SECONDS + 60)
    snap_early = create_snapshot(root, capture_id, captured_at=wave1_cutoff, edge_confidence_signal_strength=edge_confidence_signal_strength)
    snap_late = create_snapshot(root, capture_id, captured_at=wave2_end, edge_confidence_signal_strength=edge_confidence_signal_strength)
    history_events = diff_snapshots(root, capture_id, snap_early, snap_late)

    graph = build_topology_graph(root, capture_id, graph_id=f"{capture_id}-final", edge_confidence_signal_strength=edge_confidence_signal_strength)
    ground_truth_graph = build_ground_truth_graph(roles, edges, ip_by_name, graph_id=f"{capture_id}-gt")
    gt_nx = _ground_truth_nx(roles, edges)
    name_to_node_id = _name_to_node_id(graph.nodes, ip_by_name)

    # --- topology_reconstruction ---
    topology_eval = compare_topology_to_ground_truth(graph, ground_truth_graph)
    raw_evaluations["topology_reconstruction"] = asdict(topology_eval)
    metrics.append(_to_metric_result(MetricContext.TOPOLOGY_RECONSTRUCTION, experiment_id, topology_eval))

    # --- role_inference ---
    fingerprints = [
        assemble_node_fingerprint(flows, node, ObservationWindow.MEDIUM, computed_at=wave2_end) for node in graph.nodes
    ]
    ip_to_name = _reverse_lookup(ip_by_name)
    labeled = [
        (fp, roles[name])
        for fp, node in zip(fingerprints, graph.nodes)
        if (name := ip_to_name.get(str(node.ip_addresses[0]))) is not None
    ]
    if len(labeled) >= 1:
        model = fit_role_model(labeled)
        classifications = [classify_node_role(model, fp) for fp, _ in labeled]
        true_roles = [role for _, role in labeled]
        role_eval = evaluate_role_calibration(classifications, true_roles)
        raw_evaluations["role_inference"] = asdict(role_eval)
        metrics.append(_to_metric_result(MetricContext.ROLE_INFERENCE, experiment_id, role_eval))

    # --- temporal_analysis ---
    wave1_edges = edges[: len(edges) - wave_2_edges]
    wave1_names = {n for e in wave1_edges for n in (e.source, e.target)}
    wave2_edges_list = edges[len(edges) - wave_2_edges :]
    new_node_names = {n for e in wave2_edges_list for n in (e.source, e.target) if n not in wave1_names}

    edge_id_by_pair: Dict[Tuple[str, str], str] = {}
    for e in graph.edges:
        edge_id_by_pair[(e.source_node_id, e.target_node_id)] = e.edge_id
        edge_id_by_pair[(e.target_node_id, e.source_node_id)] = e.edge_id

    labeled_events: List[LabeledTopologyEvent] = []
    for name in new_node_names:
        if name in name_to_node_id:
            labeled_events.append(
                LabeledTopologyEvent(change_type=ChangeType.NODE_ADDED, node_id=name_to_node_id[name], onset_at=wave1_cutoff)
            )
    for e in wave2_edges_list:
        if e.source in name_to_node_id and e.target in name_to_node_id:
            pair = (name_to_node_id[e.source], name_to_node_id[e.target])
            edge_id = edge_id_by_pair.get(pair)
            if edge_id is not None:
                labeled_events.append(
                    LabeledTopologyEvent(change_type=ChangeType.EDGE_ADDED, edge_id=edge_id, onset_at=wave1_cutoff)
                )

    if labeled_events:
        temporal_eval = evaluate_temporal_analysis(history_events, labeled_events)
        raw_evaluations["temporal_analysis"] = asdict(temporal_eval)
        metrics.append(_to_metric_result(MetricContext.TEMPORAL_ANALYSIS, experiment_id, temporal_eval))

    # --- dependencies / causal_analysis ---
    dependencies = estimate_dependency_strength(root, capture_id, edge_confidence_signal_strength=edge_confidence_signal_strength)
    if ablation == "without_dependency_weighting":
        dependencies = [d.model_copy(update={"strength": 1.0 if d.frequency > 0 else 0.0}) for d in dependencies]
    elif ablation == "without_temporal":
        dependencies = [d.model_copy(update={"temporal_precedence_score": 0.0}) for d in dependencies]
    candidates = generate_causal_candidates(dependencies)

    ground_truth_dependency_pairs = [
        (name_to_node_id[e.source], name_to_node_id[e.target])
        for e in edges
        if e.source in name_to_node_id and e.target in name_to_node_id
    ]
    causal_eval = evaluate_causal_analysis(candidates, ground_truth_dependency_pairs)
    raw_evaluations["causal_analysis"] = asdict(causal_eval)
    metrics.append(_to_metric_result(MetricContext.CAUSAL_ANALYSIS, experiment_id, causal_eval))

    # --- pathforge (failure propagation + resilience) ---
    failed_name = _pick_failed_name(roles, edges)
    if failed_name not in name_to_node_id:
        # sampling dropped every packet touching the chosen node -- fall back to any mapped name.
        failed_name = next(iter(name_to_node_id), None)

    role_classifications = None  # without_behavioral is always applied to PathForge/counterfactual --
    # see module docstring: neither function's scored fields read role_classifications at all.

    if failed_name is not None:
        failed_node_id = name_to_node_id[failed_name]
        scenario = FailureScenario(scenario_id=f"{experiment_id}:failure", failure_type=FailureType.NODE_FAILURE, target_node_id=failed_node_id)
        pipeline_result = run_failure_propagation_pipeline(graph, scenario, candidates, role_classifications=role_classifications)
        resilience = compute_resilience_indicators(graph, pipeline_result)

        pairs = [(rc.source_node_id, rc.target_node_id) for rc in pipeline_result.route_changes]
        actually_affected, actual_largest_ids, actual_reachable_pairs = _actual_outcome_from_ground_truth(
            gt_nx, failed_name, name_to_node_id, pairs
        )
        actual = ActualFailureOutcome(
            actually_affected_node_ids=actually_affected,
            actual_largest_component_node_ids=actual_largest_ids,
            actual_reachable_pairs=actual_reachable_pairs,
        )
        failure_eval = evaluate_failure_propagation_prediction(pipeline_result, resilience, actual)
        raw_evaluations["pathforge"] = asdict(failure_eval)
        raw_evaluations["resilience_indicators"] = resilience.model_dump()
        metrics.append(_to_metric_result(MetricContext.PATHFORGE, experiment_id, failure_eval))

        # --- counterfactual ---
        cf_scenario = CounterfactualScenario(
            scenario_id=f"{experiment_id}:cf",
            action=CounterfactualAction.REMOVE_NODE,
            baseline_graph_id=graph.graph_id,
            isolated_graph_id=f"{graph.graph_id}-cf",
            target_node_id=failed_node_id,
            created_at=wave2_end,
        )
        execution = execute_counterfactual_scenario(graph, cf_scenario)
        cf_result = compare_counterfactual_outcome(graph, execution, candidates=candidates, role_classifications=role_classifications)

        cf_pairs = [(rc.source_node_id, rc.target_node_id) for rc in cf_result.route_changes]
        cf_affected, cf_largest_ids, cf_reachable_pairs = _actual_outcome_from_ground_truth(
            gt_nx, failed_name, name_to_node_id, cf_pairs
        )
        cf_actual = ActualCounterfactualOutcome(
            lab_realizable=True,
            actually_affected_node_ids=cf_affected,
            actual_largest_component_node_ids=cf_largest_ids,
            actual_reachable_pairs=cf_reachable_pairs,
        )
        cf_eval = evaluate_counterfactual_prediction(cf_result, cf_actual)
        raw_evaluations["counterfactual"] = asdict(cf_eval)
        metrics.append(_to_metric_result(MetricContext.COUNTERFACTUAL, experiment_id, cf_eval))

    experiment = Experiment(
        experiment_id=experiment_id,
        dataset_version=f"synthetic-{topology_level}-v1",
        code_version="phase-68",
        configuration={
            "topology_level": topology_level,
            "completeness": completeness,
            "ablation": ablation,
            "node_count": len(roles),
            "edge_count": len(edges),
        },
        random_seed=seed,
        timestamp=datetime.now(timezone.utc),
        environment="local",
        parameters={"packets_per_edge": packets_per_edge},
        results=raw_evaluations,
    )

    return MatrixCellResult(experiment=experiment, metrics=metrics, raw_evaluations=raw_evaluations)


def persist_cell(root: Path, cell: MatrixCellResult) -> None:
    write_json(experiment_path(root, cell.experiment.experiment_id), cell.experiment)
    write_jsonl(metrics_path(root, cell.experiment.experiment_id), cell.metrics)


def run_full_matrix(
    root: Path,
    topology_levels: Optional[List[str]] = None,
    completeness_levels: Optional[List[float]] = None,
    run_ablations: bool = True,
    seed: int = 42,
) -> List[MatrixCellResult]:
    """Runs every (topology_level x completeness) baseline cell, plus, if
    `run_ablations`, the 4 ablation variants of each cell's own baseline
    topology_level/completeness=1.0 combination (one topology per level is
    enough to isolate a component's marginal contribution; running every
    ablation at every completeness level would be 24x the cells for no
    added isolation power). Persists every cell as it completes.
    """
    levels = topology_levels or list(TOPOLOGY_LEVELS)
    completenesses = completeness_levels or OBSERVATION_COMPLETENESS_LEVELS

    results: List[MatrixCellResult] = []
    for level in levels:
        for completeness in completenesses:
            cell = run_matrix_cell(root, level, completeness, seed=seed)
            persist_cell(root, cell)
            results.append(cell)

        if run_ablations:
            for ablation in ABLATIONS:
                cell = run_matrix_cell(root, level, 1.0, seed=seed, ablation=ablation)
                persist_cell(root, cell)
                results.append(cell)

    return results
