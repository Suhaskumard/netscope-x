# Incremental Topology Reconstruction (Phase 85)

Spec (master spec addendum, Arc C): replace batch, whole-capture topology rebuilds with real incremental updates as
packets arrive; verify equivalence with a from-scratch batch rebuild over the same evidence, checked directly.

**Verdict: the incremental graph matched the batch rebuild exactly on every prefix checked, and updates are about
5-10x cheaper than a batch rebuild of the same prefix. It is not wired into the pipeline.** Code:
`backend/nettrace/topology/incremental.py`, `experiments/incremental_topology_benchmark.py`, CLI
`scripts/run_incremental_topology_benchmark.py`, tests `experiments/tests/test_incremental_topology.py`.

## Design
`IncrementalTopology.ingest(packets)` keeps packets in memory, per-IP first/last observation times and per five-tuple
flow units; only flow keys a batch touches are re-derived. `flows()` and `graph()` then number flows and compute the
per-source aggregates over cached units, and build nodes/edges. To make equivalence structural rather than hoped-for, the
batch code was split (behavior-preserving; old vs new `reconstruct_flows` identical on 20 real cells, and a test checks
the edge bucketing) into `derive_units`, `assemble_flows`, `nodes_from_observations`, `bucket_flows_in_memory` and
`discover_edges_from_flows`, which both paths call. What stays O(everything) on purpose: flow numbering (`flow_id`
appears in edge evidence text) and per-source aggregates are recomputed at materialization.

## Equivalence (real run: 6 topologies x completeness {1.0, 0.5, 0.25} x seeds 42-44, plus a UDP-session capture; 354 streams)
Exact model equality (flows incl. features, nodes, edges incl. ids, evidence text, confidence) after every chunk:
| arrival | streams | prefixes | exact | order-free (canonical) | mismatching streams |
|---|---|---|---|---|---|
| in order | 120 | 3418 | 3418 | 3418 | 0 |
| shuffled (late arrival), vs batch on the same arrival order | 117 | 1738 | 1738 | 1738 | 0 |
| shuffled, vs batch on timestamp-sorted packets | 117 | 1738 | 0 exact claimed | 1738 | 0 |
Last row: only order-free content (IP sets, edge pairs, confidence, counts, first/last seen) is compared, because ids and
evidence numbering can legitimately differ on timestamp ties; no exactness is claimed there. Chunkings: 10 equal chunks
and random sizes (plus every-packet granularity on the small cells and the UDP capture, which repeats one five-tuple across
idle gaps so session splitting and `is_persistent` are exercised).

## Speed (measured, per chunk of a 20-chunk stream: update + graph vs batch rebuild of the same prefix)
| capture | packets | incremental ms | batch ms | speedup |
|---|---|---|---|---|
| small, 15 pkts/edge | 576 | 19.6 | 187.7 | 9.6x |
| small, 200 pkts/edge | 1232 | 43.3 | 297.4 | 6.9x |
| multi_service, 15 pkts/edge | 2060 | 80.7 | 450.0 | 5.6x |
| multi_service, 200 pkts/edge | 5716 | 208.8 | 1135.8 | 5.4x |

## Limits
- The speedup is against the file-based batch path (which re-reads and re-parses JSONL); part of it is avoided I/O, not
  only avoided recomputation. Speedup shrinks as captures grow (5.4x at 5.7k packets) because `graph()` is still linear in
  flows. Timings were taken while the full test suite ran concurrently, so absolute numbers are inflated; ratios are the claim.
- Memory grows with all ingested packets (no eviction). pcap-derived TLS versions are unsupported (constructor raises).
  `as_of` time-travel is still batch. Only topology is incremental; dependency strength (Phase 87) is not.
- Equivalence covers the synthetic generators and one UDP capture; real captures with other protocols are unchecked.
