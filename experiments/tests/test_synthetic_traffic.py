"""Phase 68 synthetic traffic generation unit tests (pure, no Docker)."""

from __future__ import annotations

from experiments.synthetic_traffic import assign_ips, build_ground_truth_graph, generate_packets_for_scenario
from simulator.scenarios.topologies import simple_chain, star


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
