"""Phase 85: incremental topology reconstruction."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.nettrace.reconstruct import reconstruct_flows
from backend.nettrace.topology.discovery import discover_nodes
from backend.nettrace.topology.edges import bucket_flows_by_node_pair, bucket_flows_in_memory, discover_edges
from backend.nettrace.topology.incremental import IncrementalTopology
from experiments import incremental_topology_benchmark as B
from experiments.artifacts.io import write_jsonl
from experiments.artifacts.paths import packets_path


@pytest.fixture(scope="module")
def small_packets():
    return B.scenario_packets("small", 42)


def test_pcap_capture_is_rejected_not_silently_different():
    with pytest.raises(ValueError):
        IncrementalTopology("c", pcap_present=True)


def test_empty_ingest_and_empty_graph():
    inc = IncrementalTopology("c")
    stats = inc.ingest([])
    assert stats.packets == 0 and stats.flow_keys_total == 0
    g = inc.graph("g")
    assert g.nodes == [] and g.edges == [] and inc.flows() == []


def test_every_packet_prefix_matches_batch_exactly(small_packets, tmp_path):
    pk = small_packets[:60]
    inc = IncrementalTopology(B.CAPTURE)
    for i, p in enumerate(pk, start=1):
        inc.ingest([p])
        ref_flows, ref_graph = B.batch_reference(pk[:i], tmp_path)
        assert inc.flows() == ref_flows
        assert B.graphs_equal(inc.graph("g"), ref_graph), f"prefix {i}"


def test_full_capture_matches_batch_for_several_topologies(tmp_path):
    for level in ("medium", "large", "multi_path"):
        pk = B.sample_packets(B.scenario_packets(level, 43), 0.5, 43)
        inc = IncrementalTopology(B.CAPTURE)
        for end_a, end_b in zip([0, *B.chunk_bounds(len(pk), "random", 1)], B.chunk_bounds(len(pk), "random", 1)):
            inc.ingest(pk[end_a:end_b])
        ref_flows, ref_graph = B.batch_reference(pk, tmp_path)
        assert inc.flows() == ref_flows and B.graphs_equal(inc.graph("g"), ref_graph), level


def test_udp_sessions_split_across_chunk_boundaries_match_batch(tmp_path):
    pk = B.udp_session_packets(42)
    row = B.check_stream("udp", pk, "in_order", "random", 7, tmp_path)
    assert row.exact_matches == row.checks > 0
    inc = IncrementalTopology(B.CAPTURE)
    inc.ingest(pk)
    flows = inc.flows()
    assert any(f.features.is_persistent for f in flows)  # repeated five-tuples across idle gaps -> >1 unit per key
    assert len({(str(f.src_ip), f.src_port) for f in flows}) < len(flows)


def test_icmp_only_node_appears_without_an_edge(tmp_path):
    pk = B.udp_session_packets(42)
    inc = IncrementalTopology(B.CAPTURE)
    inc.ingest(pk)
    g = inc.graph("g")
    assert "10.1.5.5" in {str(n.ip_addresses[0]) for n in g.nodes}
    assert all("10.1.5.5" not in (e.source_node_id, e.target_node_id) for e in g.edges)


def test_ingest_touches_only_affected_flow_keys(small_packets):
    inc = IncrementalTopology(B.CAPTURE)
    first = inc.ingest(small_packets[:200])
    later = inc.ingest(small_packets[200:210])
    assert later.flow_keys_touched < later.flow_keys_total
    assert later.flow_keys_total >= first.flow_keys_total


def test_shuffled_arrival_exact_against_arrival_order_and_canonical_against_sorted(tmp_path):
    pk = B.sample_packets(B.scenario_packets("medium", 42), 0.5, 42)
    shuffled = B.check_stream("m", pk, "shuffled", "ten", 3, tmp_path)
    canon = B.check_stream("m", pk, "canonical", "ten", 3, tmp_path)
    assert shuffled.exact_matches == shuffled.checks
    assert canon.canonical_matches == canon.checks and canon.exact_matches == 0  # exact is never claimed here


def test_deterministic(small_packets):
    a, b = IncrementalTopology("c"), IncrementalTopology("c")
    a.ingest(small_packets)
    b.ingest(small_packets)
    assert a.flows() == b.flows() and B.graphs_equal(a.graph("g"), b.graph("g"))


def test_edge_refactor_is_behavior_preserving(small_packets, tmp_path):
    write_jsonl(packets_path(tmp_path, "c"), small_packets)
    flows = reconstruct_flows(tmp_path, "c")
    nodes = discover_nodes(tmp_path, "c")
    assert bucket_flows_in_memory(flows, nodes) == bucket_flows_by_node_pair(tmp_path, "c", nodes)
    assert discover_edges(tmp_path, "c", nodes)  # file path still works end to end
