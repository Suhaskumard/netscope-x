"""Phase 76: minimal anomaly-injection dataset and its matrix wiring."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from backend.app.models.anomaly import AnomalyDimension
from backend.app.models.metric import MetricContext
from experiments.anomaly_injection import (
    BASELINE_EPOCHS,
    BURST_PEERS,
    EPOCH_SECONDS,
    NEW_DESTINATION_BURST,
    SPIKE_FACTOR,
    TEST_EPOCHS,
    VOLUME_SPIKE,
    generate_anomaly_dataset,
)
from experiments.matrix_runner import TOPOLOGY_LEVELS, run_matrix_cell
from experiments.synthetic_traffic import BASE_TIME, assign_ips
from simulator.scenarios.topologies import ScenarioEdge


def _dataset(level: str = "medium", seed: int = 1, packets_per_edge: int = 5):
    roles, edges = TOPOLOGY_LEVELS[level]()
    ips = assign_ips(list(roles))
    return roles, edges, ips, generate_anomaly_dataset(roles, edges, ips, "cap", seed, packets_per_edge)


def _epoch_of(dataset, packet) -> int:
    return int((packet.timestamp - BASE_TIME).total_seconds() // dataset.epoch_seconds)


def test_at_least_five_baseline_epochs_and_clean_test_epochs() -> None:
    assert BASELINE_EPOCHS >= 5  # Phase 38's build_node_baseline cold-start minimum
    _, _, _, dataset = _dataset()
    assert {i.epoch for i in dataset.injected} == {BASELINE_EPOCHS + 1, BASELINE_EPOCHS + 2}
    assert dataset.total_epochs == BASELINE_EPOCHS + TEST_EPOCHS
    assert {_epoch_of(dataset, p) for p in dataset.packets} == set(range(dataset.total_epochs))
    assert len({p.packet_id for p in dataset.packets}) == len(dataset.packets)


def test_deterministic_per_seed_and_seed_changes_the_dataset() -> None:
    _, _, _, a = _dataset(seed=3)
    _, _, _, b = _dataset(seed=3)
    _, _, _, c = _dataset(seed=4)
    assert [p.model_dump() for p in a.packets] == [p.model_dump() for p in b.packets]
    assert a.injected == b.injected
    assert [p.model_dump() for p in a.packets] != [p.model_dump() for p in c.packets]


def test_baseline_epochs_have_real_volume_spread() -> None:
    _, _, _, dataset = _dataset(packets_per_edge=15)
    per_epoch = Counter(_epoch_of(dataset, p) for p in dataset.packets if _epoch_of(dataset, p) < BASELINE_EPOCHS)
    assert len(set(per_epoch.values())) > 1  # identical epochs would make every MAD zero


def test_onset_is_the_first_injected_packet_and_labels_follow_the_pattern() -> None:
    roles, edges, ips, dataset = _dataset()
    by_pattern = {i.pattern: i for i in dataset.injected}
    assert set(by_pattern) == {VOLUME_SPIKE, NEW_DESTINATION_BURST}

    spike = by_pattern[VOLUME_SPIKE]
    assert all(dim == AnomalyDimension.TRAFFIC_VOLUME for _, dim in spike.labels)
    assert (spike.actor, AnomalyDimension.TRAFFIC_VOLUME) in spike.labels
    out_targets = {e.target for e in edges if e.source == spike.actor}
    assert {n for n, _ in spike.labels} == {spike.actor} | out_targets

    burst = by_pattern[NEW_DESTINATION_BURST]
    assert burst.labels == ((burst.actor, AnomalyDimension.DESTINATIONS),)

    for injected in dataset.injected:
        start, end = dataset.epoch_start(injected.epoch), dataset.epoch_end(injected.epoch)
        assert start <= injected.onset_at < end
        # the onset is a real packet in the capture, sent by the actor
        actor_ip = ips[injected.actor]
        assert any(p.timestamp == injected.onset_at and str(p.src_ip) == actor_ip for p in dataset.packets)


def test_burst_targets_only_nodes_without_an_existing_edge() -> None:
    roles, edges, ips, dataset = _dataset()
    burst = next(i for i in dataset.injected if i.pattern == NEW_DESTINATION_BURST)
    connected = {e.target for e in edges if e.source == burst.actor} | {e.source for e in edges if e.target == burst.actor}
    ip_to_name = {ip: n for n, ip in ips.items()}
    injected_epoch_dsts = {
        ip_to_name[str(p.dst_ip)]
        for p in dataset.packets
        if _epoch_of(dataset, p) == burst.epoch and str(p.src_ip) == ips[burst.actor]
    }
    new_dsts = injected_epoch_dsts - connected
    assert 1 <= len(new_dsts) <= BURST_PEERS


def test_spike_multiplies_the_actors_outgoing_volume() -> None:
    roles, edges, ips, dataset = _dataset(packets_per_edge=10)
    spike = next(i for i in dataset.injected if i.pattern == VOLUME_SPIKE)
    out_ips = {ips[e.target] for e in edges if e.source == spike.actor}

    def actor_out(epoch: int) -> int:
        return sum(1 for p in dataset.packets if _epoch_of(dataset, p) == epoch and str(p.src_ip) == ips[spike.actor] and str(p.dst_ip) in out_ips)

    normal = actor_out(BASELINE_EPOCHS)  # first test epoch is clean
    assert actor_out(spike.epoch) >= (SPIKE_FACTOR - 1) * normal * 0.6  # jitter-tolerant lower bound


def test_pattern_is_skipped_not_faked_when_it_cannot_be_built() -> None:
    roles = {"a": next(iter(TOPOLOGY_LEVELS["small"]()[0].values())), "b": next(iter(TOPOLOGY_LEVELS["small"]()[0].values()))}
    edges = [ScenarioEdge(source="a", target="b", protocols=["tcp"])]  # every pair already has an edge
    dataset = generate_anomaly_dataset(roles, edges, assign_ips(list(roles)), "cap", 1, 3)
    assert [i.pattern for i in dataset.injected] == [VOLUME_SPIKE]
    assert any(NEW_DESTINATION_BURST in s for s in dataset.skipped)


def test_matrix_cell_scores_anomaly_detection_for_real(tmp_path: Path) -> None:
    cell = run_matrix_cell(tmp_path, "small", 1.0, seed=42)
    metric = next(m for m in cell.metrics if m.context == MetricContext.ANOMALY_DETECTION)
    raw = cell.raw_evaluations["anomaly_detection"]

    assert raw["baseline_epochs"] >= 5
    assert {i["pattern"] for i in raw["injected"]} == {VOLUME_SPIKE, NEW_DESTINATION_BURST}
    assert raw["true_positive_count"] + raw["false_negative_count"] == raw["label_count"]
    assert metric.precision == raw["precision"] and metric.recall == raw["recall"] and metric.f1 == raw["f1"]
    assert metric.false_positive_rate == raw["false_positive_rate"] is not None
    # a real detection can only happen after the epoch finishes: latency is bounded by the epoch length
    assert 0 < metric.detection_latency_seconds <= EPOCH_SECONDS
    assert raw["recall"] > 0  # the injected 5x spike / new-destination burst is detectable at full observation
    assert (tmp_path / "captures" / f"{cell.experiment.experiment_id}-anomaly" / "flows.jsonl").is_file()


def test_ablation_cells_do_not_rescore_anomaly_detection(tmp_path: Path) -> None:
    cell = run_matrix_cell(tmp_path, "small", 1.0, seed=42, ablation="without_temporal")
    assert MetricContext.ANOMALY_DETECTION not in {m.context for m in cell.metrics}
