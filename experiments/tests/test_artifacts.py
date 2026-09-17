"""Phase 10 research artifact architecture tests.

Round-trips real Phase 04 model instances through the artifact I/O layer
against a real temporary directory (pytest's tmp_path, actual filesystem,
not mocked), covering all required artifact types: flows, graphs,
snapshots, ground truth, experiments, and metrics (results).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.app.models import (
    Edge,
    Experiment,
    Flow,
    FlowFeatures,
    MetricContext,
    MetricResult,
    NetworkSnapshot,
    Node,
    TopologyGraph,
    TransportProtocol,
)
from experiments.artifacts import io, paths

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _sample_flow(flow_id: str) -> Flow:
    return Flow(
        flow_id=flow_id,
        capture_id="cap1",
        src_ip="10.0.0.1",
        dst_ip="10.0.0.2",
        src_port=51000,
        dst_port=443,
        protocol=TransportProtocol.TCP,
        first_seen=NOW,
        last_seen=NOW,
        features=FlowFeatures(
            packet_count=10,
            byte_count=5000,
            duration_seconds=2.5,
            burstiness=0.4,
            mean_inter_arrival_seconds=0.25,
            forward_byte_ratio=0.8,
            destination_diversity=3,
            port_diversity=2,
            is_persistent=True,
        ),
    )


def _sample_topology_graph() -> TopologyGraph:
    n1 = Node(node_id="n1", ip_addresses=["10.0.0.1"], first_observed=NOW, last_observed=NOW)
    n2 = Node(node_id="n2", ip_addresses=["10.0.0.2"], first_observed=NOW, last_observed=NOW)
    e1 = Edge(
        edge_id="e1",
        source_node_id="n1",
        target_node_id="n2",
        confidence=0.9,
        evidence=["repeated flows"],
        observation_count=5,
        first_observed=NOW,
        last_observed=NOW,
        protocols=["TCP"],
    )
    return TopologyGraph(graph_id="g1", generated_at=NOW, nodes=[n1, n2], edges=[e1])


def test_flows_round_trip_via_jsonl(tmp_path: Path) -> None:
    root = tmp_path
    flows = [_sample_flow("f1"), _sample_flow("f2")]
    path = paths.flows_path(root, "cap1")

    io.write_jsonl(path, flows)
    loaded = io.read_jsonl(path, Flow)

    assert loaded == flows
    assert path.exists()
    assert path.parent == paths.capture_dir(root, "cap1")


def test_topology_graph_round_trip_via_json(tmp_path: Path) -> None:
    root = tmp_path
    graph = _sample_topology_graph()
    path = paths.topology_path(root, "cap1", graph.graph_id)

    io.write_json(path, graph)
    loaded = io.read_json(path, TopologyGraph)

    assert loaded == graph


def test_snapshot_round_trip_via_json(tmp_path: Path) -> None:
    root = tmp_path
    snapshot = NetworkSnapshot(snapshot_id="s1", graph_id="g1", captured_at=NOW, version=1)
    path = paths.snapshot_path(root, "cap1", snapshot.snapshot_id)

    io.write_json(path, snapshot)
    loaded = io.read_json(path, NetworkSnapshot)

    assert loaded == snapshot


def test_experiment_and_metrics_round_trip(tmp_path: Path) -> None:
    root = tmp_path
    experiment = Experiment(
        experiment_id="exp1",
        dataset_version="dataset_small@v1",
        code_version="abc1234",
        configuration={"detector": "flowmind-v1"},
        random_seed=42,
        timestamp=NOW,
        environment="docker-lab",
    )
    metrics = [
        MetricResult(
            metric_id="m1",
            experiment_id="exp1",
            context=MetricContext.TOPOLOGY_RECONSTRUCTION,
            computed_at=NOW,
            precision=0.9,
            recall=0.85,
        ),
        MetricResult(
            metric_id="m2",
            experiment_id="exp1",
            context=MetricContext.ANOMALY_DETECTION,
            computed_at=NOW,
            f1=0.7,
        ),
    ]

    io.write_json(paths.experiment_path(root, "exp1"), experiment)
    io.write_jsonl(paths.metrics_path(root, "exp1"), metrics)

    loaded_experiment = io.read_json(paths.experiment_path(root, "exp1"), Experiment)
    loaded_metrics = io.read_jsonl(paths.metrics_path(root, "exp1"), MetricResult)

    assert loaded_experiment == experiment
    assert loaded_metrics == metrics


def test_ground_truth_round_trip_with_valid_hash(tmp_path: Path) -> None:
    root = tmp_path
    graph = _sample_topology_graph()
    path = paths.ground_truth_topology_path(root, "cap1")

    digest = io.write_ground_truth(path, graph)
    loaded = io.read_ground_truth(path, TopologyGraph)

    assert loaded == graph
    sidecar = path.parent / f"{path.name}.sha256"
    assert sidecar.exists()
    assert sidecar.read_text(encoding="utf-8").strip() == digest


def test_ground_truth_tamper_detection(tmp_path: Path) -> None:
    root = tmp_path
    graph = _sample_topology_graph()
    path = paths.ground_truth_topology_path(root, "cap1")
    io.write_ground_truth(path, graph)

    # Simulate accidental or malicious contamination of the ground-truth file
    # after it was written -- this must NEVER silently succeed.
    tampered = path.read_text(encoding="utf-8").replace('"g1"', '"g1-tampered"')
    path.write_text(tampered, encoding="utf-8")

    with pytest.raises(io.GroundTruthIntegrityError):
        io.read_ground_truth(path, TopologyGraph)


def test_ground_truth_missing_sidecar_is_rejected(tmp_path: Path) -> None:
    root = tmp_path
    graph = _sample_topology_graph()
    path = paths.ground_truth_topology_path(root, "cap1")
    io.write_ground_truth(path, graph)

    sidecar = path.parent / f"{path.name}.sha256"
    sidecar.unlink()

    with pytest.raises(io.GroundTruthIntegrityError):
        io.read_ground_truth(path, TopologyGraph)


def test_pcap_path_convention_matches_capture_dir(tmp_path: Path) -> None:
    root = tmp_path
    p = paths.pcap_path(root, "cap1")
    assert p == paths.capture_dir(root, "cap1") / "raw.pcap"
