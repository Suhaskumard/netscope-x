"""Phase 68 synthetic traffic generation unit tests (pure, no Docker).

Phase 70 additions (temporal-lag pulses) are grouped at the bottom.
"""

from __future__ import annotations

from pathlib import Path

from backend.dependency.temporal_precedence import estimate_temporal_precedence
from backend.nettrace.reconstruct import reconstruct_flows
from backend.nettrace.topology.discovery import discover_nodes
from experiments.artifacts.io import write_jsonl
from experiments.artifacts.paths import packets_path
from experiments.synthetic_traffic import (
    _compute_tiers,
    assign_ips,
    build_ground_truth_graph,
    generate_packets_for_scenario,
)
from simulator.scenarios.topologies import multi_tier, simple_chain, star


def test_assign_ips_gives_unique_stable_ips() -> None:
    ips = assign_ips(["b", "a", "c"])
    assert len(set(ips.values())) == 3
    assert assign_ips(["b", "a", "c"]) == ips  # deterministic regardless of call order


def test_build_ground_truth_graph_matches_declared_scenario() -> None:
    roles, edges = star(4)
    ips = assign_ips(list(roles.keys()))
    graph = build_ground_truth_graph(roles, edges, ips, graph_id="gt")

    assert len(graph.nodes) == len(roles)
    assert len(graph.edges) == len(edges)
    assert all(e.confidence == 1.0 for e in graph.edges)


def test_generate_packets_produces_bidirectional_pairs() -> None:
    roles, edges = simple_chain(3)
    ips = assign_ips(list(roles.keys()))
    packets = generate_packets_for_scenario(roles, edges, ips, "cap-1", seed=1, packets_per_edge=5)

    assert len(packets) == len(edges) * 5 * 2
    directions = {(str(p.src_ip), str(p.dst_ip)) for p in packets}
    # every declared edge should show traffic in both directions (request + response)
    for e in edges:
        assert (ips[e.source], ips[e.target]) in directions
        assert (ips[e.target], ips[e.source]) in directions


def test_wave_2_edges_are_timestamped_later() -> None:
    roles, edges = simple_chain(4)
    ips = assign_ips(list(roles.keys()))
    packets = generate_packets_for_scenario(
        roles, edges, ips, "cap-1", seed=1, packets_per_edge=3, wave_2_edges=1, wave_gap_seconds=1000.0
    )

    last_edge = edges[-1]
    wave2_packets = [p for p in packets if str(p.src_ip) == ips[last_edge.source] and str(p.dst_ip) == ips[last_edge.target]]
    other_packets = [
        p
        for p in packets
        if not (str(p.src_ip) == ips[last_edge.source] and str(p.dst_ip) == ips[last_edge.target])
        and not (str(p.src_ip) == ips[last_edge.target] and str(p.dst_ip) == ips[last_edge.source])
    ]
    assert wave2_packets
    assert other_packets
    assert min(p.timestamp for p in wave2_packets) > max(p.timestamp for p in other_packets)


def test_deterministic_for_same_seed() -> None:
    roles, edges = star(3)
    ips = assign_ips(list(roles.keys()))
    first = generate_packets_for_scenario(roles, edges, ips, "cap-1", seed=5, packets_per_edge=4)
    second = generate_packets_for_scenario(roles, edges, ips, "cap-1", seed=5, packets_per_edge=4)
    assert [p.packet_id for p in first] == [p.packet_id for p in second]
    assert [p.timestamp for p in first] == [p.timestamp for p in second]


# --- Phase 70: lag-encoded intensity pulses ---


def test_compute_tiers_matches_bfs_depth_from_root() -> None:
    # simple_chain is a pure path -- BFS depth from the root is unambiguous per node.
    roles, edges = simple_chain(5)
    tiers = _compute_tiers(roles, edges)

    root = next(iter(roles))
    assert tiers[root] == 0
    assert tiers == {"node-1": 0, "node-2": 1, "node-3": 2, "node-4": 3, "node-5": 4}


def test_compute_tiers_uses_real_bfs_distance_not_declared_tier_label() -> None:
    # multi_tier declares "tier0-2" as tier 0, but it shares no direct edge with the root
    # ("tier0-1") -- every tier-0 node only connects to tier-1 nodes, so tier0-2's real BFS
    # distance from the root is 2 hops (via any tier-1 node), not 0. _compute_tiers must
    # reflect genuine graph distance, not the generator's own label.
    roles, edges = multi_tier([2, 4, 4, 2])
    tiers = _compute_tiers(roles, edges)

    assert tiers["tier0-1"] == 0
    assert tiers["tier1-1"] == 1
    assert tiers["tier0-2"] == 2
    assert tiers["tier2-1"] == 2
    assert tiers["tier3-1"] == 3


def test_pulses_disabled_by_default_is_byte_identical() -> None:
    roles, edges = simple_chain(4)
    ips = assign_ips(list(roles.keys()))
    without_pulse_kwarg = generate_packets_for_scenario(roles, edges, ips, "cap-1", seed=1, packets_per_edge=5)
    with_zero_cycles = generate_packets_for_scenario(
        roles, edges, ips, "cap-1", seed=1, packets_per_edge=5, pulse_cycles=0
    )
    assert [p.packet_id for p in without_pulse_kwarg] == [p.packet_id for p in with_zero_cycles]
    assert [p.timestamp for p in without_pulse_kwarg] == [p.timestamp for p in with_zero_cycles]


def test_pulses_add_extra_packets_when_enabled() -> None:
    roles, edges = simple_chain(4)
    ips = assign_ips(list(roles.keys()))
    baseline = generate_packets_for_scenario(roles, edges, ips, "cap-1", seed=1, packets_per_edge=5)
    with_pulses = generate_packets_for_scenario(
        roles, edges, ips, "cap-1", seed=1, packets_per_edge=5, pulse_cycles=6, pulse_packets_per_node=2
    )
    assert len(with_pulses) > len(baseline)


def test_pulse_flows_produce_real_positive_temporal_precedence(tmp_path: Path) -> None:
    """Real, end-to-end check: feed pulse-enabled synthetic packets through the actual
    pipeline and confirm `estimate_temporal_precedence` -- unmodified Phase 52 code -- finds
    a genuine positive-lag correlation for a real tier-separated pair. This is the actual
    fix Phase 70 exists for; a direct assertion of the previously-broken behavior is more
    honest than only testing the generator's own internal shape."""
    root = tmp_path / "artifacts"
    roles, edges = simple_chain(5)
    ips = assign_ips(list(roles.keys()))
    packets = generate_packets_for_scenario(
        roles, edges, ips, "cap-1", seed=1, packets_per_edge=15,
        pulse_cycles=12, pulse_packets_per_node=2, pulse_intensity_range=(1, 5),
    )
    write_jsonl(packets_path(root, "cap-1"), packets)
    flows = reconstruct_flows(root, "cap-1")
    nodes = discover_nodes(root, "cap-1")
    ip_to_node = {str(n.ip_addresses[0]): n for n in nodes}

    scores = []
    for e in edges:
        a, b = ip_to_node[ips[e.source]], ip_to_node[ips[e.target]]
        scores.append(max(estimate_temporal_precedence(flows, a, b), estimate_temporal_precedence(flows, b, a)))

    assert any(score > 0.0 for score in scores), (
        "expected at least one real positive temporal_precedence_score with pulses enabled"
    )
