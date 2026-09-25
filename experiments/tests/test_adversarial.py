"""Phase 84: adversarial robustness evaluation."""

from __future__ import annotations

from datetime import timedelta

import pytest

from backend.app.models.anomaly import AnomalyDimension
from backend.app.models.behavior import ObservationWindow, ServiceRole
from backend.flowmind.anomaly.node_anomaly import detect_sustained_drift
from backend.flowmind.baseline.node_baseline import build_anchored_baseline, build_node_baseline
from backend.flowmind.classification.role_classifier import (
    classify_node_role,
    classify_node_role_robust,
    fit_role_model,
    is_out_of_distribution,
)
from backend.nettrace.reconstruct import reconstruct_flows
from backend.nettrace.topology.graph import build_topology_graph
from experiments.adversarial import attacks as A
from experiments.adversarial import benchmark as B
from experiments.artifacts.io import write_jsonl
from experiments.artifacts.paths import packets_path
from experiments.synthetic_traffic import assign_ips

LEVEL = "medium"


@pytest.fixture(scope="module")
def scenario():
    return B._scenario_packets(LEVEL, 42)


def test_attacks_do_not_mutate_input_and_are_deterministic(scenario):
    roles, edges, ips, packets = scenario
    snapshot = list(packets)
    real = list(ips.values())
    a = A.spoofed_sources(packets, real, 1)
    b = A.spoofed_sources(packets, real, 1)
    assert packets == snapshot and a == b and len(a) > len(packets)


def test_spoofed_sources_add_only_unused_one_way_ips(scenario):
    roles, edges, ips, packets = scenario
    out = A.spoofed_sources(packets, list(ips.values()), 1)
    fresh = {str(p.src_ip) for p in out} - {str(p.src_ip) for p in packets}
    assert fresh and all(ip.startswith(A.FAKE_IP_PREFIX) for ip in fresh)
    assert not any(str(p.dst_ip) in fresh for p in out)  # nobody replies to a forged source


def test_decoy_chatter_links_only_undeclared_pairs(scenario):
    roles, edges, ips, packets = scenario
    declared = {frozenset((ips[e.source], ips[e.target])) for e in edges}
    extra = [p for p in A.decoy_chatter(packets, ips, edges, 1) if p not in set(packets)]
    pairs = {frozenset((str(p.src_ip), str(p.dst_ip))) for p in extra}
    assert pairs and not (pairs & declared)


def test_ip_aliasing_removes_victim_source_address(scenario):
    roles, edges, ips, packets = scenario
    victim = A.pick_actor(edges)
    out = A.ip_aliasing(packets, ips[victim], 1)
    assert len(out) == len(packets)
    assert not any(str(p.src_ip) == ips[victim] or str(p.dst_ip) == ips[victim] for p in out)


def test_role_attacks_act_late_so_the_fingerprint_window_sees_them(scenario):
    roles, edges, ips, packets = scenario
    victim = ips[sorted(roles)[0]]
    out = A.fingerprint_noise(packets, victim, list(ips.values()), 1)
    new = [p for p in out if p not in set(packets)]
    assert new and min(p.timestamp for p in new) >= max(p.timestamp for p in packets) - timedelta(seconds=11)


def test_volume_dataset_ramp_and_labels():
    roles, edges = B.TOPOLOGY_LEVELS[LEVEL]()
    ips = assign_ips(list(roles))
    clean = A.volume_dataset(roles, edges, ips, "c", 42, "clean")
    slow = A.volume_dataset(roles, edges, ips, "c", 42, "low_and_slow")
    poisoned = A.volume_dataset(roles, edges, ips, "c", 42, "baseline_poisoning")
    assert clean.label_pairs == slow.label_pairs == poisoned.label_pairs
    assert slow.label_epoch == A.BASELINE_EPOCHS and clean.label_epoch == A.BASELINE_EPOCHS + 1
    assert len(poisoned.packets) > len(clean.packets)
    with pytest.raises(ValueError):
        A.volume_dataset(roles, edges, ips, "c", 42, "nope")


def test_hardening_defaults_are_bit_identical(scenario, tmp_path):
    roles, edges, ips, packets = scenario
    write_jsonl(packets_path(tmp_path, "adv"), packets)
    reconstruct_flows(tmp_path, "adv")
    default = build_topology_graph(tmp_path, "adv", graph_id="g")
    explicit = build_topology_graph(tmp_path, "adv", graph_id="g", min_edge_bidirectionality=0.0)
    assert default.nodes == explicit.nodes and default.edges == explicit.edges


def test_bidirectional_hardening_removes_spoofed_nodes_and_keeps_real_ones(scenario, tmp_path):
    roles, edges, ips, packets = scenario
    spoofed = A.spoofed_sources(packets, list(ips.values()), 1)
    write_jsonl(packets_path(tmp_path, "adv"), spoofed)
    reconstruct_flows(tmp_path, "adv")
    plain = build_topology_graph(tmp_path, "adv", graph_id="g")
    hard = build_topology_graph(tmp_path, "adv", graph_id="g", min_edge_bidirectionality=B.MIN_EDGE_BIDIRECTIONALITY)
    assert len(plain.nodes) > len(roles)
    assert {str(n.ip_addresses[0]) for n in hard.nodes} == set(ips.values())


def test_role_ood_detection_and_abstention(scenario, tmp_path):
    roles, edges, ips, packets = scenario
    attacker, mimic = B._pick_role_attacker(roles, ips, packets, tmp_path)
    assert attacker in roles and mimic != roles[attacker]
    clean = B._role_outcome(tmp_path, packets, roles, ips, attacker, mimic, hardened=True)
    assert clean["abstained"] == 0.0 and clean["correct"] == 1.0  # guard: clean traffic is not abstained on
    noisy = A.fingerprint_noise(packets, ips[attacker], list(ips.values()), 1)
    hard = B._role_outcome(tmp_path, noisy, roles, ips, attacker, mimic, hardened=True)
    assert hard["abstained"] == 1.0 and hard["not_confidently_wrong"] == 1.0


def test_robust_classifier_matches_default_when_in_distribution(scenario, tmp_path):
    roles, edges, ips, packets = scenario
    write_jsonl(packets_path(tmp_path, "adv"), packets)
    flows = reconstruct_flows(tmp_path, "adv")
    from backend.nettrace.topology.discovery import discover_nodes
    from backend.flowmind.fingerprints.node_fingerprint import assemble_node_fingerprint

    at = B.BASE_TIME + timedelta(seconds=B._WAVE_GAP_SECONDS + 60)
    name_of = {ip: n for n, ip in ips.items()}
    labeled = [(assemble_node_fingerprint(flows, n, ObservationWindow.MEDIUM, computed_at=at),
                roles[name_of[str(n.ip_addresses[0])]]) for n in discover_nodes(tmp_path, "adv")]
    model = fit_role_model(labeled)
    fp = labeled[0][0]
    assert not is_out_of_distribution(model, fp)
    assert classify_node_role_robust(model, fp).role_probabilities == classify_node_role(model, fp).role_probabilities


def _fp(node_id, epoch, byte_count):
    from backend.app.models.behavior import BehavioralFingerprint

    return BehavioralFingerprint(
        node_id=node_id, window=ObservationWindow.SHORT, computed_at=A.BASE_TIME + timedelta(seconds=60 * epoch),
        distinct_ports=[80], distinct_protocols=["TCP"], distinct_destinations=2, mean_flow_duration_seconds=0.1,
        outbound_byte_ratio=0.5, is_persistent_talker=False, total_byte_count=byte_count,
    )


def test_sustained_drift_flags_rising_series_not_flat_or_short():
    history = [_fp("n", e, 1000 + 10 * (e % 3)) for e in range(8)]
    baseline = build_node_baseline(history)
    rising = [_fp("n", 8 + k, 1000 + 400 * (k + 1)) for k in range(4)]
    flat = [_fp("n", 8 + k, 1010) for k in range(4)]
    out = detect_sustained_drift(baseline, rising)
    assert len(out) == 1 and out[0].dimension == AnomalyDimension.TRAFFIC_VOLUME
    assert out[0].detected_at == rising[2].computed_at  # first epoch where 3 rising, elevated epochs exist
    assert detect_sustained_drift(baseline, flat) == []
    assert detect_sustained_drift(baseline, rising[:2]) == []


def test_anchored_baseline_ignores_late_history():
    history = [_fp("n", e, 1000) for e in range(3)] + [_fp("n", 3 + e, 1000 + 500 * (e + 1)) for e in range(5)]
    assert build_anchored_baseline(history, anchor_count=3, min_observations=3).total_byte_count.median == 1000
    assert build_node_baseline(history).total_byte_count.median > 1000


def test_anchored_baseline_recovers_poisoned_recall_and_keeps_clean_recall(tmp_path):
    poisoned = [B.anomaly_cell("baseline_poisoning", LEVEL, 42, h, tmp_path)["recall"] for h in (False, True)]
    clean = [B.anomaly_cell("clean:volume", LEVEL, 42, h, tmp_path)["recall"] for h in (False, True)]
    assert poisoned[1] > poisoned[0]
    assert clean[1] >= clean[0] - 1e-9


def test_summary_rule_marks_success_only_beyond_clean_spread():
    def cell(variant, v, seed):
        return B.Cell("spoofed_sources", "small", seed, variant, {"node_f1": v})

    ok = [cell("clean", 1.0, 1), cell("attacked", 0.7, 1), cell("clean_hardened", 1.0, 1),
          cell("attacked_hardened", 1.0, 1),
          cell("clean", 1.0, 2), cell("attacked", 0.7, 2), cell("clean_hardened", 1.0, 2),
          cell("attacked_hardened", 1.0, 2)]
    s = B.summarize(A.ATTACKS[0], ok)
    assert s.succeeded and s.hardening_works and s.hardening_accepted and B.verdict(s) == "successful -> FIXED"
    flat = [cell(v, 1.0, sd) for sd in (1, 2) for v in ("clean", "attacked", "clean_hardened", "attacked_hardened")]
    assert not B.summarize(A.ATTACKS[0], flat).succeeded
    assert AnomalyDimension.TRAFFIC_VOLUME.value == "traffic_volume"
    assert ServiceRole.API.value  # roles used by the benchmark exist
