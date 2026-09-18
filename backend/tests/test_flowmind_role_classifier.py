"""Phase 36 service role inference (Naive Bayes classifier) unit tests (pure, no Docker)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.app.models.behavior import BehavioralFingerprint, ObservationWindow, ServiceRole
from backend.app.models.flow import Flow, FlowFeatures
from backend.app.models.packet import TransportProtocol
from backend.app.models.topology import Node
from backend.flowmind.classification.role_classifier import classify_node_role, fit_role_model
from backend.flowmind.fingerprints.node_fingerprint import assemble_node_fingerprint

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _fp(
    node_id: str,
    ports,
    protocols,
    destinations: int,
    duration: float,
    ratio: float,
    persistent: bool,
) -> BehavioralFingerprint:
    return BehavioralFingerprint(
        node_id=node_id,
        window=ObservationWindow.MEDIUM,
        computed_at=BASE,
        distinct_ports=list(ports),
        distinct_protocols=list(protocols),
        distinct_destinations=destinations,
        mean_flow_duration_seconds=duration,
        outbound_byte_ratio=ratio,
        is_persistent_talker=persistent,
    )


def _dns_like(node_id: str, destinations: int = 1) -> BehavioralFingerprint:
    return _fp(node_id, [53], ["UDP"], destinations, 0.2, 0.5, False)


def _database_like(node_id: str, destinations: int = 1) -> BehavioralFingerprint:
    return _fp(node_id, [5432], ["TCP"], destinations, 5.0, 0.7, True)


def test_fit_role_model_raises_on_empty_training_data() -> None:
    with pytest.raises(ValueError):
        fit_role_model([])


def test_classify_recovers_correct_role_for_clearly_separated_profiles() -> None:
    labeled = [
        (_dns_like("dns-train-1", destinations=1), ServiceRole.DNS),
        (_dns_like("dns-train-2", destinations=2), ServiceRole.DNS),
        (_dns_like("dns-train-3", destinations=1), ServiceRole.DNS),
        (_database_like("db-train-1", destinations=1), ServiceRole.DATABASE),
        (_database_like("db-train-2", destinations=2), ServiceRole.DATABASE),
        (_database_like("db-train-3", destinations=1), ServiceRole.DATABASE),
    ]
    model = fit_role_model(labeled)

    dns_result = classify_node_role(model, _dns_like("dns-held-out"))
    db_result = classify_node_role(model, _database_like("db-held-out"))

    assert dns_result.best_role == ServiceRole.DNS
    assert db_result.best_role == ServiceRole.DATABASE


def test_role_probabilities_always_valid() -> None:
    labeled = [
        (_dns_like("dns-1"), ServiceRole.DNS),
        (_dns_like("dns-2"), ServiceRole.DNS),
        (_database_like("db-1"), ServiceRole.DATABASE),
        (_database_like("db-2"), ServiceRole.DATABASE),
    ]
    model = fit_role_model(labeled)
    result = classify_node_role(model, _dns_like("query"))

    total = sum(result.role_probabilities.values())
    assert abs(total - 1.0) < 1e-6
    assert all(0.0 <= p <= 1.0 for p in result.role_probabilities.values())


def test_single_training_example_role_still_classifies_without_error() -> None:
    labeled = [
        (_dns_like("dns-1"), ServiceRole.DNS),
        (_dns_like("dns-2"), ServiceRole.DNS),
        (_database_like("db-only"), ServiceRole.DATABASE),  # only one example -> zero raw variance
    ]
    model = fit_role_model(labeled)

    result = classify_node_role(model, _database_like("db-query"))

    assert result.best_role == ServiceRole.DATABASE
    assert abs(sum(result.role_probabilities.values()) - 1.0) < 1e-6


def test_protocol_mix_signal_distinguishes_otherwise_identical_profiles() -> None:
    # Same generic port, same duration/ratio/persistence -- only the protocol differs.
    tcp_only = lambda node_id: _fp(node_id, [9999], ["TCP"], 1, 1.0, 0.5, False)
    udp_only = lambda node_id: _fp(node_id, [9999], ["UDP"], 1, 1.0, 0.5, False)

    labeled = [
        (tcp_only("gw-1"), ServiceRole.GATEWAY),
        (tcp_only("gw-2"), ServiceRole.GATEWAY),
        (tcp_only("gw-3"), ServiceRole.GATEWAY),
        (udp_only("wk-1"), ServiceRole.WORKER),
        (udp_only("wk-2"), ServiceRole.WORKER),
        (udp_only("wk-3"), ServiceRole.WORKER),
    ]
    model = fit_role_model(labeled)

    assert classify_node_role(model, tcp_only("gw-query")).best_role == ServiceRole.GATEWAY
    assert classify_node_role(model, udp_only("wk-query")).best_role == ServiceRole.WORKER


def test_classification_is_deterministic() -> None:
    labeled = [
        (_dns_like("dns-1"), ServiceRole.DNS),
        (_dns_like("dns-2"), ServiceRole.DNS),
        (_database_like("db-1"), ServiceRole.DATABASE),
        (_database_like("db-2"), ServiceRole.DATABASE),
    ]
    model = fit_role_model(labeled)
    fixed_time = BASE

    first = classify_node_role(model, _dns_like("query"), computed_at=fixed_time)
    second = classify_node_role(model, _dns_like("query"), computed_at=fixed_time)

    assert first == second


def test_real_pipeline_types_via_assemble_node_fingerprint(tmp_path: Path) -> None:
    dns_node = Node(node_id="n-dns", ip_addresses=["10.0.0.1"], first_observed=BASE, last_observed=BASE)
    db_node = Node(node_id="n-db", ip_addresses=["10.0.0.2"], first_observed=BASE, last_observed=BASE)

    def _flow(flow_id, src_ip, dst_ip, dst_port, protocol) -> Flow:
        return Flow(
            flow_id=flow_id,
            capture_id="cap-1",
            src_ip=src_ip,
            dst_ip=dst_ip,
            src_port=51000,
            dst_port=dst_port,
            protocol=protocol,
            first_seen=BASE,
            last_seen=BASE + timedelta(seconds=1),
            features=FlowFeatures(
                packet_count=2,
                byte_count=100,
                duration_seconds=1.0,
                burstiness=0.0,
                mean_inter_arrival_seconds=0.1,
                forward_byte_ratio=0.5,
                destination_diversity=1,
                port_diversity=1,
                is_persistent=False,
            ),
        )

    dns_flows = [_flow("f0", "10.0.0.9", "10.0.0.1", 53, TransportProtocol.UDP)]
    db_flows = [_flow("f1", "10.0.0.9", "10.0.0.2", 5432, TransportProtocol.TCP)]
    # A second, independent example per role, built the same real way -- keeps
    # every training point on the same continuous-feature scale (unlike mixing
    # in the module-level _dns_like/_database_like helpers, whose hand-picked
    # duration/ratio values live on a different scale and would pull each
    # role's fitted Gaussian mean away from what assemble_node_fingerprint
    # actually produces).
    dns_flows_2 = [_flow("f2", "10.0.0.8", "10.0.0.1", 53, TransportProtocol.UDP)]
    db_flows_2 = [_flow("f3", "10.0.0.8", "10.0.0.2", 5432, TransportProtocol.TCP)]

    dns_fp = assemble_node_fingerprint(dns_flows, dns_node, ObservationWindow.MEDIUM)
    db_fp = assemble_node_fingerprint(db_flows, db_node, ObservationWindow.MEDIUM)
    dns_fp_2 = assemble_node_fingerprint(dns_flows_2, dns_node, ObservationWindow.MEDIUM)
    db_fp_2 = assemble_node_fingerprint(db_flows_2, db_node, ObservationWindow.MEDIUM)

    labeled = [
        (dns_fp, ServiceRole.DNS),
        (dns_fp_2, ServiceRole.DNS),
        (db_fp, ServiceRole.DATABASE),
        (db_fp_2, ServiceRole.DATABASE),
    ]
    model = fit_role_model(labeled)

    assert classify_node_role(model, dns_fp).best_role == ServiceRole.DNS
    assert classify_node_role(model, db_fp).best_role == ServiceRole.DATABASE
