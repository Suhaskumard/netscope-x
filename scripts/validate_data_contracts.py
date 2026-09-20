"""Phase 04 validation script.

Constructs one VALID and one INVALID instance of every data contract in
backend/app/models, and asserts that the invalid case actually raises
pydantic.ValidationError. This is the executed proof required by the
master spec's Rule 2 ("never fabricate execution") and §32 ("a phase is
not complete merely because code exists / imports succeed") -- schemas are
only considered verified once this script is run and its output inspected.

Run with:
    .venv/Scripts/python.exe -m scripts.validate_data_contracts
(from the repository root, so the `backend` package resolves on sys.path).
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import ValidationError

from backend.app.models import (
    Anomaly,
    AnomalyClass,
    AnomalyDimension,
    BehavioralFingerprint,
    CausalEvidenceReport,
    ChangeType,
    CommunicationRelationship,
    CounterfactualAction,
    CounterfactualScenario,
    DependencyEdge,
    Edge,
    Experiment,
    FailureScenario,
    FailureType,
    Flow,
    FlowFeatures,
    GraphChangeEvent,
    ImpactOrder,
    MetricContext,
    MetricResult,
    NetworkSnapshot,
    Node,
    ObservationWindow,
    Packet,
    PacketDirection,
    PropagationImpact,
    ResilienceIndicators,
    RoleClassification,
    ServiceRole,
    SimulationRun,
    TCPState,
    TopologyGraph,
    TransportProtocol,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)

results: list[tuple[str, bool, str]] = []


def check_valid(label: str, factory) -> None:
    try:
        factory()
        results.append((label, True, "constructed OK"))
    except ValidationError as exc:
        results.append((label, False, f"UNEXPECTED ValidationError: {exc}"))


def check_invalid(label: str, factory) -> None:
    try:
        factory()
        results.append((label, False, "expected ValidationError but none was raised"))
    except ValidationError:
        results.append((label, True, "correctly rejected"))


# ---------------------------------------------------------------- packet --
check_valid(
    "Packet (valid)",
    lambda: Packet(
        packet_id="p1",
        capture_id="cap1",
        timestamp=NOW,
        src_ip="10.0.0.1",
        dst_ip="10.0.0.2",
        src_port=443,
        dst_port=51000,
        protocol=TransportProtocol.TCP,
        size_bytes=1500,
        direction=PacketDirection.FORWARD,
    ),
)
check_invalid(
    "Packet (invalid: port out of range)",
    lambda: Packet(
        packet_id="p2",
        capture_id="cap1",
        timestamp=NOW,
        src_ip="10.0.0.1",
        dst_ip="10.0.0.2",
        src_port=999999,
        protocol=TransportProtocol.TCP,
        size_bytes=1500,
    ),
)

# ------------------------------------------------------------------ flow --
_flow_features = dict(
    packet_count=10,
    byte_count=5000,
    duration_seconds=2.5,
    burstiness=0.4,
    mean_inter_arrival_seconds=0.25,
    forward_byte_ratio=0.8,
    destination_diversity=3,
    port_diversity=2,
    is_persistent=True,
)
check_valid(
    "Flow (valid)",
    lambda: Flow(
        flow_id="f1",
        capture_id="cap1",
        src_ip="10.0.0.1",
        dst_ip="10.0.0.2",
        src_port=51000,
        dst_port=443,
        protocol=TransportProtocol.TCP,
        first_seen=NOW,
        last_seen=NOW,
        tcp_state=TCPState.ESTABLISHED,
        features=FlowFeatures(**_flow_features),
    ),
)
check_invalid(
    "Flow (invalid: last_seen before first_seen)",
    lambda: Flow(
        flow_id="f2",
        capture_id="cap1",
        src_ip="10.0.0.1",
        dst_ip="10.0.0.2",
        protocol=TransportProtocol.UDP,
        first_seen=NOW,
        last_seen=datetime(2020, 1, 1, tzinfo=timezone.utc),
        features=FlowFeatures(**_flow_features),
    ),
)

# ------------------------------------------------------------------ node --
check_valid(
    "Node (valid)",
    lambda: Node(node_id="n1", ip_addresses=["10.0.0.1"], first_observed=NOW, last_observed=NOW),
)
check_invalid(
    "Node (invalid: last_observed before first_observed)",
    lambda: Node(
        node_id="n2",
        ip_addresses=["10.0.0.2"],
        first_observed=NOW,
        last_observed=datetime(2020, 1, 1, tzinfo=timezone.utc),
    ),
)

# ------------------------------------------------------------------ edge --
check_valid(
    "Edge (valid)",
    lambda: Edge(
        edge_id="e1",
        source_node_id="n1",
        target_node_id="n2",
        confidence=0.9,
        evidence=["repeated TCP flows over 10 min"],
        observation_count=42,
        first_observed=NOW,
        last_observed=NOW,
        protocols=["TCP"],
    ),
)
check_invalid(
    "Edge (invalid: self-loop)",
    lambda: Edge(
        edge_id="e2",
        source_node_id="n1",
        target_node_id="n1",
        confidence=0.5,
        evidence=["x"],
        observation_count=1,
        first_observed=NOW,
        last_observed=NOW,
        protocols=["TCP"],
    ),
)

# -------------------------------------------------------------- topology --
_n1 = Node(node_id="n1", ip_addresses=["10.0.0.1"], first_observed=NOW, last_observed=NOW)
_n2 = Node(node_id="n2", ip_addresses=["10.0.0.2"], first_observed=NOW, last_observed=NOW)
_e_valid = Edge(
    edge_id="e1",
    source_node_id="n1",
    target_node_id="n2",
    confidence=0.9,
    evidence=["x"],
    observation_count=5,
    first_observed=NOW,
    last_observed=NOW,
    protocols=["TCP"],
)
check_valid(
    "TopologyGraph (valid)",
    lambda: TopologyGraph(graph_id="g1", generated_at=NOW, nodes=[_n1, _n2], edges=[_e_valid]),
)
_e_dangling = Edge(
    edge_id="e3",
    source_node_id="n1",
    target_node_id="n999",
    confidence=0.5,
    evidence=["x"],
    observation_count=1,
    first_observed=NOW,
    last_observed=NOW,
    protocols=["TCP"],
)
check_invalid(
    "TopologyGraph (invalid: edge references unknown node)",
    lambda: TopologyGraph(graph_id="g2", generated_at=NOW, nodes=[_n1, _n2], edges=[_e_dangling]),
)

# ----------------------------------------------------- behavioral fingerprint --
check_valid(
    "BehavioralFingerprint (valid)",
    lambda: BehavioralFingerprint(
        node_id="n1",
        window=ObservationWindow.MEDIUM,
        computed_at=NOW,
        distinct_ports=[443, 8080],
        distinct_protocols=["TCP"],
        distinct_destinations=5,
        mean_flow_duration_seconds=1.2,
        outbound_byte_ratio=0.6,
        is_persistent_talker=True,
    ),
)
check_invalid(
    "BehavioralFingerprint (invalid: outbound_byte_ratio out of range)",
    lambda: BehavioralFingerprint(
        node_id="n1",
        window=ObservationWindow.MEDIUM,
        computed_at=NOW,
        distinct_destinations=5,
        mean_flow_duration_seconds=1.2,
        outbound_byte_ratio=1.7,
        is_persistent_talker=True,
    ),
)

# --------------------------------------------------------- role classification --
check_valid(
    "RoleClassification (valid)",
    lambda: RoleClassification(
        node_id="n1",
        computed_at=NOW,
        role_probabilities={ServiceRole.DATABASE: 0.72, ServiceRole.CACHE: 0.21, ServiceRole.UNKNOWN: 0.07},
    ),
)
check_invalid(
    "RoleClassification (invalid: probabilities don't sum to 1)",
    lambda: RoleClassification(
        node_id="n1",
        computed_at=NOW,
        role_probabilities={ServiceRole.DATABASE: 0.5, ServiceRole.CACHE: 0.1},
    ),
)

# --------------------------------------------------------------- anomaly --
check_valid(
    "Anomaly (valid)",
    lambda: Anomaly(
        node_id="n1",
        anomaly_id="a1",
        detected_at=NOW,
        dimension=AnomalyDimension.DESTINATIONS,
        anomaly_class=AnomalyClass.TRANSIENT_ANOMALY,
        evidence=["new destination X observed", "historical_destinations=4, current=9"],
        evidence_values={"historical_destinations": "4", "current_destinations": "9"},
        score=0.83,
    ),
)
check_invalid(
    "Anomaly (invalid: empty evidence)",
    lambda: Anomaly(
        node_id="n1",
        anomaly_id="a2",
        detected_at=NOW,
        dimension=AnomalyDimension.PORTS,
        anomaly_class=AnomalyClass.TRANSIENT_ANOMALY,
        evidence=[],
        score=0.5,
    ),
)

# -------------------------------------------------------------- snapshot --
check_valid(
    "NetworkSnapshot (valid)",
    lambda: NetworkSnapshot(snapshot_id="s1", graph_id="g1", captured_at=NOW, version=1),
)
check_valid(
    "GraphChangeEvent (valid)",
    lambda: GraphChangeEvent(
        event_id="ev1",
        from_snapshot_id="s1",
        to_snapshot_id="s2",
        occurred_at=NOW,
        change_type=ChangeType.NODE_ADDED,
        affected_node_id="n3",
        evidence=["new node n3 first observed at t=..."],
    ),
)
check_invalid(
    "GraphChangeEvent (invalid: node_added without affected_node_id)",
    lambda: GraphChangeEvent(
        event_id="ev2",
        from_snapshot_id="s1",
        to_snapshot_id="s2",
        occurred_at=NOW,
        change_type=ChangeType.NODE_ADDED,
        evidence=["x"],
    ),
)

# ------------------------------------------------------------ dependency --
check_valid(
    "CommunicationRelationship (valid)",
    lambda: CommunicationRelationship(
        source_node_id="n1", target_node_id="n2", frequency=12.5, persistence_seconds=600.0
    ),
)
check_valid(
    "DependencyEdge (valid)",
    lambda: DependencyEdge(
        dependency_id="d1",
        source_node_id="n1",
        target_node_id="n2",
        strength=0.85,
        frequency=12.5,
        persistence_seconds=600.0,
        directionality_score=0.9,
        temporal_precedence_score=0.6,
    ),
)
check_invalid(
    "DependencyEdge (invalid: self-dependency)",
    lambda: DependencyEdge(
        dependency_id="d2",
        source_node_id="n1",
        target_node_id="n1",
        strength=0.5,
        frequency=1.0,
        persistence_seconds=1.0,
        directionality_score=0.5,
    ),
)
check_valid(
    "CausalEvidenceReport (valid)",
    lambda: CausalEvidenceReport(
        report_id="c1",
        relationship="API-1 depends on Redis",
        evidence=["consistent request->query temporal precedence over 500 samples"],
        confidence=0.78,
        counter_evidence=[],
        limitations=["single vantage point capture; no host-level confirmation"],
        generated_at=NOW,
    ),
)
check_invalid(
    "CausalEvidenceReport (invalid: empty limitations)",
    lambda: CausalEvidenceReport(
        report_id="c2",
        relationship="X depends on Y",
        evidence=["some evidence"],
        confidence=0.5,
        limitations=[],
        generated_at=NOW,
    ),
)

# ---------------------------------------------------------------- failure --
check_valid(
    "FailureScenario (valid)",
    lambda: FailureScenario(
        scenario_id="fs1", failure_type=FailureType.NODE_FAILURE, target_node_id="n2"
    ),
)
check_invalid(
    "FailureScenario (invalid: node_failure missing target_node_id)",
    lambda: FailureScenario(scenario_id="fs2", failure_type=FailureType.NODE_FAILURE),
)
check_valid(
    "PropagationImpact (valid)",
    lambda: PropagationImpact(
        scenario_id="fs1",
        affected_node_id="n3",
        order=ImpactOrder.SECONDARY,
        caused_by_node_id="n2",
        evidence=["n3 lost connectivity to n2 after n2 failure"],
    ),
)
check_invalid(
    "PropagationImpact (invalid: primary impact with caused_by_node_id)",
    lambda: PropagationImpact(
        scenario_id="fs1",
        affected_node_id="n2",
        order=ImpactOrder.PRIMARY,
        caused_by_node_id="n1",
        evidence=["x"],
    ),
)
check_valid(
    "ResilienceIndicators (valid)",
    lambda: ResilienceIndicators(
        scenario_id="fs1",
        connectivity_ratio=0.7,
        reachable_node_ratio=0.8,
        affected_service_count=2,
        path_degradation_score=1.4,
        bottleneck_node_ids=["n2"],
        alternative_path_available=True,
    ),
)
check_invalid(
    "ResilienceIndicators (invalid: connectivity_ratio out of range)",
    lambda: ResilienceIndicators(
        scenario_id="fs1",
        connectivity_ratio=1.5,
        reachable_node_ratio=0.8,
        affected_service_count=2,
        path_degradation_score=1.4,
        alternative_path_available=True,
    ),
)

# ------------------------------------------------------------- simulation --
check_valid(
    "SimulationRun (valid)",
    lambda: SimulationRun(
        run_id="sr1",
        twin_snapshot_id="s1",
        scenario=FailureScenario(
            scenario_id="fs1", failure_type=FailureType.NODE_FAILURE, target_node_id="n2"
        ),
        started_at=NOW,
    ),
)
check_invalid(
    "SimulationRun (invalid: missing required scenario)",
    lambda: SimulationRun(run_id="sr2", twin_snapshot_id="s1", started_at=NOW),
)
check_valid(
    "CounterfactualScenario (valid)",
    lambda: CounterfactualScenario(
        scenario_id="cf1",
        action=CounterfactualAction.REMOVE_NODE,
        baseline_graph_id="g1",
        isolated_graph_id="g1-cf1",
        target_node_id="n2",
        created_at=NOW,
    ),
)
check_invalid(
    "CounterfactualScenario (invalid: isolated_graph_id == baseline_graph_id)",
    lambda: CounterfactualScenario(
        scenario_id="cf2",
        action=CounterfactualAction.REMOVE_NODE,
        baseline_graph_id="g1",
        isolated_graph_id="g1",
        target_node_id="n2",
        created_at=NOW,
    ),
)
check_invalid(
    "CounterfactualScenario (invalid: REMOVE_NODE missing target_node_id)",
    lambda: CounterfactualScenario(
        scenario_id="cf3",
        action=CounterfactualAction.REMOVE_NODE,
        baseline_graph_id="g1",
        isolated_graph_id="g1-cf3",
        created_at=NOW,
    ),
)
check_valid(
    "CounterfactualScenario (valid: REMOVE_EDGE)",
    lambda: CounterfactualScenario(
        scenario_id="cf4",
        action=CounterfactualAction.REMOVE_EDGE,
        baseline_graph_id="g1",
        isolated_graph_id="g1-cf4",
        target_edge_id="e1",
        created_at=NOW,
    ),
)
check_invalid(
    "CounterfactualScenario (invalid: REMOVE_EDGE missing target_edge_id)",
    lambda: CounterfactualScenario(
        scenario_id="cf5",
        action=CounterfactualAction.REMOVE_EDGE,
        baseline_graph_id="g1",
        isolated_graph_id="g1-cf5",
        created_at=NOW,
    ),
)
check_valid(
    "CounterfactualScenario (valid: INCREASE_LATENCY)",
    lambda: CounterfactualScenario(
        scenario_id="cf6",
        action=CounterfactualAction.INCREASE_LATENCY,
        baseline_graph_id="g1",
        isolated_graph_id="g1-cf6",
        target_node_id="n2",
        magnitude=50.0,
        created_at=NOW,
    ),
)
check_invalid(
    "CounterfactualScenario (invalid: INCREASE_LATENCY missing magnitude)",
    lambda: CounterfactualScenario(
        scenario_id="cf7",
        action=CounterfactualAction.INCREASE_LATENCY,
        baseline_graph_id="g1",
        isolated_graph_id="g1-cf7",
        target_node_id="n2",
        created_at=NOW,
    ),
)
check_invalid(
    "CounterfactualScenario (invalid: INCREASE_LATENCY missing target_node_id)",
    lambda: CounterfactualScenario(
        scenario_id="cf8",
        action=CounterfactualAction.INCREASE_LATENCY,
        baseline_graph_id="g1",
        isolated_graph_id="g1-cf8",
        magnitude=50.0,
        created_at=NOW,
    ),
)
check_valid(
    "CounterfactualScenario (valid: REDUCE_BANDWIDTH via target_node_id)",
    lambda: CounterfactualScenario(
        scenario_id="cf9",
        action=CounterfactualAction.REDUCE_BANDWIDTH,
        baseline_graph_id="g1",
        isolated_graph_id="g1-cf9",
        target_node_id="n2",
        magnitude=0.5,
        created_at=NOW,
    ),
)
check_valid(
    "CounterfactualScenario (valid: REDUCE_BANDWIDTH via target_edge_id)",
    lambda: CounterfactualScenario(
        scenario_id="cf10",
        action=CounterfactualAction.REDUCE_BANDWIDTH,
        baseline_graph_id="g1",
        isolated_graph_id="g1-cf10",
        target_edge_id="e1",
        magnitude=0.5,
        created_at=NOW,
    ),
)
check_invalid(
    "CounterfactualScenario (invalid: REDUCE_BANDWIDTH neither target set)",
    lambda: CounterfactualScenario(
        scenario_id="cf11",
        action=CounterfactualAction.REDUCE_BANDWIDTH,
        baseline_graph_id="g1",
        isolated_graph_id="g1-cf11",
        magnitude=0.5,
        created_at=NOW,
    ),
)
check_invalid(
    "CounterfactualScenario (invalid: REDUCE_BANDWIDTH missing magnitude)",
    lambda: CounterfactualScenario(
        scenario_id="cf12",
        action=CounterfactualAction.REDUCE_BANDWIDTH,
        baseline_graph_id="g1",
        isolated_graph_id="g1-cf12",
        target_node_id="n2",
        created_at=NOW,
    ),
)
check_valid(
    "CounterfactualScenario (valid: INCREASE_TRAFFIC)",
    lambda: CounterfactualScenario(
        scenario_id="cf13",
        action=CounterfactualAction.INCREASE_TRAFFIC,
        baseline_graph_id="g1",
        isolated_graph_id="g1-cf13",
        target_node_id="n2",
        magnitude=2.0,
        created_at=NOW,
    ),
)
check_invalid(
    "CounterfactualScenario (invalid: INCREASE_TRAFFIC missing magnitude)",
    lambda: CounterfactualScenario(
        scenario_id="cf14",
        action=CounterfactualAction.INCREASE_TRAFFIC,
        baseline_graph_id="g1",
        isolated_graph_id="g1-cf14",
        target_node_id="n2",
        created_at=NOW,
    ),
)
check_valid(
    "CounterfactualScenario (valid: ADD_ROUTE)",
    lambda: CounterfactualScenario(
        scenario_id="cf15",
        action=CounterfactualAction.ADD_ROUTE,
        baseline_graph_id="g1",
        isolated_graph_id="g1-cf15",
        source_node_id="n1",
        target_node_id="n2",
        created_at=NOW,
    ),
)
check_invalid(
    "CounterfactualScenario (invalid: ADD_ROUTE missing source_node_id)",
    lambda: CounterfactualScenario(
        scenario_id="cf16",
        action=CounterfactualAction.ADD_ROUTE,
        baseline_graph_id="g1",
        isolated_graph_id="g1-cf16",
        target_node_id="n2",
        created_at=NOW,
    ),
)
check_invalid(
    "CounterfactualScenario (invalid: ADD_ROUTE with target_edge_id set)",
    lambda: CounterfactualScenario(
        scenario_id="cf17",
        action=CounterfactualAction.ADD_ROUTE,
        baseline_graph_id="g1",
        isolated_graph_id="g1-cf17",
        source_node_id="n1",
        target_node_id="n2",
        target_edge_id="e1",
        created_at=NOW,
    ),
)
check_invalid(
    "CounterfactualScenario (invalid: ADD_ROUTE self-loop source == target)",
    lambda: CounterfactualScenario(
        scenario_id="cf18",
        action=CounterfactualAction.ADD_ROUTE,
        baseline_graph_id="g1",
        isolated_graph_id="g1-cf18",
        source_node_id="n1",
        target_node_id="n1",
        created_at=NOW,
    ),
)
check_invalid(
    "CounterfactualScenario (invalid: source_node_id set on non-ADD_ROUTE action)",
    lambda: CounterfactualScenario(
        scenario_id="cf19",
        action=CounterfactualAction.REMOVE_NODE,
        baseline_graph_id="g1",
        isolated_graph_id="g1-cf19",
        source_node_id="n1",
        target_node_id="n2",
        created_at=NOW,
    ),
)

# ------------------------------------------------------------- experiment --
check_valid(
    "Experiment (valid)",
    lambda: Experiment(
        experiment_id="exp1",
        dataset_version="dataset_small@v1",
        code_version="abc1234",
        configuration={"detector": "flowmind-v1"},
        random_seed=42,
        timestamp=NOW,
        environment="docker-lab",
    ),
)
check_invalid(
    "Experiment (invalid: missing required random_seed)",
    lambda: Experiment(
        experiment_id="exp2",
        dataset_version="dataset_small@v1",
        code_version="abc1234",
        configuration={},
        timestamp=NOW,
        environment="docker-lab",
    ),
)

# ---------------------------------------------------------------- metric --
check_valid(
    "MetricResult (valid)",
    lambda: MetricResult(
        metric_id="m1",
        experiment_id="exp1",
        context=MetricContext.TOPOLOGY_RECONSTRUCTION,
        computed_at=NOW,
        precision=0.9,
        recall=0.85,
        f1=0.87,
    ),
)
check_invalid(
    "MetricResult (invalid: precision out of range)",
    lambda: MetricResult(
        metric_id="m2",
        experiment_id="exp1",
        context=MetricContext.ANOMALY_DETECTION,
        computed_at=NOW,
        precision=1.4,
    ),
)


# ----------------------------------------------------------------- report --
if __name__ == "__main__":
    passed = 0
    failed = 0
    for label, ok, detail in results:
        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        else:
            failed += 1
        print(f"[{status}] {label}: {detail}")
    print(f"\n{passed} passed, {failed} failed, {len(results)} total")
    if failed:
        raise SystemExit(1)
