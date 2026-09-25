"""Canonical on-disk layout for research artifacts (spec Phase 10).

All paths are built from an explicit `root` directory passed by the
caller -- never a hardcoded global path (ties to NFR-4, configuration-
driven behavior; a future phase may source `root` from Settings once a
concrete deployment need justifies it).

Layout:

    <root>/
      captures/<capture_id>/
        raw.pcap
        manifest.json                 (ingestion metadata, spec Phase 21)
        packets.jsonl                 (normalized packets, spec Phase 22)
        flows.jsonl
        topology/<graph_id>.json
        fingerprints.jsonl            (assembled BehavioralFingerprints, spec Phase 35)
        snapshots/<snapshot_id>.json
        topology_events.jsonl         (chronological GraphChangeEvent stream, spec Phase 47)
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
        manifest.json                 (every run of this cell, spec addendum Phase 75)
        manifest.json.sha256
        v<N>/
          experiment.json
          metrics.jsonl
        experiment.json               (legacy pre-Phase-75 flat layout; read-only fallback)
        metrics.jsonl
"""

from __future__ import annotations

from pathlib import Path


def capture_dir(root: Path, capture_id: str) -> Path:
    return root / "captures" / capture_id


def pcap_path(root: Path, capture_id: str) -> Path:
    return capture_dir(root, capture_id) / "raw.pcap"


def capture_manifest_path(root: Path, capture_id: str) -> Path:
    return capture_dir(root, capture_id) / "manifest.json"


def packets_path(root: Path, capture_id: str) -> Path:
    return capture_dir(root, capture_id) / "packets.jsonl"


def flows_path(root: Path, capture_id: str) -> Path:
    return capture_dir(root, capture_id) / "flows.jsonl"


def topology_path(root: Path, capture_id: str, graph_id: str) -> Path:
    return capture_dir(root, capture_id) / "topology" / f"{graph_id}.json"


def fingerprints_path(root: Path, capture_id: str) -> Path:
    """One capture's assembled BehavioralFingerprints (spec Phase 35), one per
    node per observation window, as JSON Lines -- a collection, unlike
    topology_path's single-object TopologyGraph."""
    return capture_dir(root, capture_id) / "fingerprints.jsonl"


def snapshots_dir(root: Path, capture_id: str) -> Path:
    return capture_dir(root, capture_id) / "snapshots"


def snapshot_path(root: Path, capture_id: str, snapshot_id: str) -> Path:
    return snapshots_dir(root, capture_id) / f"{snapshot_id}.json"


def events_path(root: Path, capture_id: str) -> Path:
    """One capture's chronological `GraphChangeEvent` stream (spec Phase 47), as JSON Lines --
    built by chaining Phase 45's `diff_snapshots` across every consecutive pair of Phase 44's
    `NetworkSnapshot`s for this capture."""
    return capture_dir(root, capture_id) / "topology_events.jsonl"


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
    """Legacy (pre-Phase-75) flat location, overwritten on every re-run. New runs are written
    under `experiment_run_dir`; this path is only read as a fallback for older artifact roots."""
    return experiment_dir(root, experiment_id) / "experiment.json"


def metrics_path(root: Path, experiment_id: str) -> Path:
    """Legacy (pre-Phase-75) flat location -- see `experiment_path`."""
    return experiment_dir(root, experiment_id) / "metrics.jsonl"


def experiment_manifest_path(root: Path, experiment_id: str) -> Path:
    return experiment_dir(root, experiment_id) / "manifest.json"


def experiment_run_dir(root: Path, experiment_id: str, version: int) -> Path:
    return experiment_dir(root, experiment_id) / f"v{version}"
