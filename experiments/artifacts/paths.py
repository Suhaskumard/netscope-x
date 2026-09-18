"""Canonical on-disk layout for research artifacts (spec Phase 10).

All paths are built from an explicit `root` directory passed by the
caller -- never a hardcoded global path (ties to NFR-4, configuration-
driven behavior; a future phase may source `root` from Settings once a
concrete deployment need justifies it).

Layout:

    <root>/
      captures/<capture_id>/
        raw.pcap
        flows.jsonl
        topology/<graph_id>.json
        snapshots/<snapshot_id>.json
      ground_truth/<capture_id>/
        topology.json
        topology.json.sha256          (content-hash sidecar, spec Phase 10)
        manifest.json                 (generation history, spec Phase 17)
        manifest.json.sha256
        v<N>/
          <artifact>.json
          <artifact>.json.sha256
      scenarios/<scenario_id>/
        declaration.json              (roles + edges, spec Phase 18)
        docker-compose.yml            (generated, deployable)
        topology.json                 (only if actually deployed)
      experiments/<experiment_id>/
        experiment.json
        metrics.jsonl
"""

from __future__ import annotations

from pathlib import Path


def capture_dir(root: Path, capture_id: str) -> Path:
    return root / "captures" / capture_id


def pcap_path(root: Path, capture_id: str) -> Path:
    return capture_dir(root, capture_id) / "raw.pcap"


def flows_path(root: Path, capture_id: str) -> Path:
    return capture_dir(root, capture_id) / "flows.jsonl"


def topology_path(root: Path, capture_id: str, graph_id: str) -> Path:
    return capture_dir(root, capture_id) / "topology" / f"{graph_id}.json"


def snapshot_path(root: Path, capture_id: str, snapshot_id: str) -> Path:
    return capture_dir(root, capture_id) / "snapshots" / f"{snapshot_id}.json"


def ground_truth_dir(root: Path, capture_id: str) -> Path:
    return root / "ground_truth" / capture_id


def ground_truth_topology_path(root: Path, capture_id: str) -> Path:
    return ground_truth_dir(root, capture_id) / "topology.json"


def ground_truth_manifest_path(root: Path, capture_id: str) -> Path:
    return ground_truth_dir(root, capture_id) / "manifest.json"


def ground_truth_generation_dir(root: Path, capture_id: str, version: int) -> Path:
    return ground_truth_dir(root, capture_id) / f"v{version}"


def scenario_dir(root: Path, scenario_id: str) -> Path:
    return root / "scenarios" / scenario_id


def scenario_declaration_path(root: Path, scenario_id: str) -> Path:
    return scenario_dir(root, scenario_id) / "declaration.json"


def scenario_compose_path(root: Path, scenario_id: str) -> Path:
    return scenario_dir(root, scenario_id) / "docker-compose.yml"


def scenario_topology_path(root: Path, scenario_id: str) -> Path:
    """Only written once a scenario is actually deployed -- see simulator/scenarios/generate.py's
    build_topology_graph, which requires a real docker IP lookup."""
    return scenario_dir(root, scenario_id) / "topology.json"


def experiment_dir(root: Path, experiment_id: str) -> Path:
    return root / "experiments" / experiment_id


def experiment_path(root: Path, experiment_id: str) -> Path:
    return experiment_dir(root, experiment_id) / "experiment.json"


def metrics_path(root: Path, experiment_id: str) -> Path:
    return experiment_dir(root, experiment_id) / "metrics.jsonl"
