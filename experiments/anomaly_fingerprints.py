"""Per-node, per-epoch behavioral fingerprints for a Phase 76 anomaly dataset.

Shared by the Phase 68 matrix's `anomaly_detection` scoring (Phase 76) and the Phase 78 sequence-model
benchmark, so every detector under comparison sees exactly the same fingerprint history.

The (observation-sampled) anomaly capture is written under `<capture_id>-anomaly` and reconstructed into
flows once; each epoch's flows give every node one real `BehavioralFingerprint` whose `computed_at` is the
epoch's end -- a detection can only happen after the epoch it judges has finished, so detection latency
honestly includes that wait.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Sequence

from backend.app.models.behavior import BehavioralFingerprint, ObservationWindow
from backend.app.models.flow import Flow
from backend.app.models.topology import Node
from backend.flowmind.fingerprints.node_fingerprint import assemble_node_fingerprint
from backend.nettrace.reconstruct import reconstruct_flows
from experiments.anomaly_injection import AnomalyDataset
from experiments.artifacts.io import write_jsonl
from experiments.artifacts.paths import packets_path
from experiments.observation_sampling import sample_packets


def anomaly_capture_id(capture_id: str) -> str:
    return f"{capture_id}-anomaly"


def write_anomaly_capture(
    root: Path, capture_id: str, dataset: AnomalyDataset, completeness: float, seed: int
) -> List[Flow]:
    """Writes the observation-sampled anomaly capture under `<capture_id>-anomaly` and returns its
    reconstructed flows."""
    write_jsonl(packets_path(root, anomaly_capture_id(capture_id)), sample_packets(dataset.packets, completeness, seed))
    return reconstruct_flows(root, anomaly_capture_id(capture_id))


def fingerprints_from_flows(
    flows: Sequence[Flow], dataset: AnomalyDataset, nodes: Sequence[Node]
) -> Dict[str, List[BehavioralFingerprint]]:
    """`{node_id: [fingerprint for epoch 0, 1, ..., total_epochs - 1]}` for every node in `nodes`."""
    window_seconds = {ObservationWindow.SHORT: dataset.epoch_seconds}
    epoch_flows = []
    for epoch in range(dataset.total_epochs):
        start, end = dataset.epoch_start(epoch), dataset.epoch_end(epoch)
        epoch_flows.append([f for f in flows if start <= f.last_seen < end])

    return {
        node.node_id: [
            assemble_node_fingerprint(
                epoch_flows[epoch], node, ObservationWindow.SHORT, window_seconds, computed_at=dataset.epoch_end(epoch)
            )
            for epoch in range(dataset.total_epochs)
        ]
        for node in nodes
    }


def build_epoch_fingerprints(
    root: Path,
    capture_id: str,
    dataset: AnomalyDataset,
    completeness: float,
    seed: int,
    nodes: Sequence[Node],
) -> Dict[str, List[BehavioralFingerprint]]:
    flows = write_anomaly_capture(root, capture_id, dataset, completeness, seed)
    return fingerprints_from_flows(flows, dataset, nodes)
