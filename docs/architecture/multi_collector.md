# Distributed Multi-Collector Capture (Phase 90)

`backend/nettrace/collectors/multi.py` (`MultiCollectorPipeline`) feeds several vantage points ("collectors") into one
reconstruction pipeline (Phase 85's `IncrementalTopology`). Built and measured; **not wired into the pipeline**; no
schema change (collector provenance lives outside the frozen `Packet`).

## Resolution rule
1. **De-duplicate across collectors.** One wire packet seen by two collectors must count once, because the Phase 31 edge
   confidence is a noisy-OR over pooled packet evidence. Identity = (src/dst ip+port, protocol, size, tcp_flags,
   direction); observations from DIFFERENT collectors within `dedupe_tolerance_s` (default 1 ms) are one packet (nearest
   match; each accepted packet is claimable once per collector, so a collector's own genuine repeats are never merged).
   First-seen timestamp wins.
2. **Pool, don't average.** The deduplicated union goes into one `IncrementalTopology`; nodes, flows, edges and
   confidences are recomputed from the pooled evidence. When collectors disagree about an edge, the fused confidence is
   what the pooled evidence supports, never a max/mean/vote of collector numbers.
3. **Optional quorum guard** (`quorum=True`): an edge backed by exactly one collector, while at least
   `quorum_min_absent` (default 2) other collectors saw BOTH endpoints and never saw the edge, is contested and dropped.
4. Every fused edge gets a `Resolution` (kind agree / existence / confidence / single_source; supporting, absent and
   blind collectors; per-collector confidences; kept or dropped_contested).

## Measured (`scripts/run_multi_collector_benchmark.py`; 4 topologies x 2 seeds; collectors simulated from scenario traffic)
- **Equivalence, checked directly.** When the union of N = 2, 3, 4 collectors covers the whole capture (overlap 0.5), the
  fused graph equals the single full-capture graph exactly (edge set, confidence to 1e-9, accepted packets == full
  capture): 96/96 runs, in-order and interleaved/shuffled arrival, zero skew and skew inside the tolerance (<= 0.6 ms).
- **Confidence resolution vs alternatives** (N=3, overlap 0.3, mean abs confidence error vs the full-capture graph, no
  packet loss): pooled 0.0000, naive concatenation without dedupe 0.0158 (large topology 0.042), union-max 0.0228,
  mean of collectors 0.0327. With packet loss the yardstick stops being fair: pooled is *lower* than the full capture
  because evidence is genuinely missing (loss 0.3: pooled 0.0156, naive 0.0071; loss 0.8: 0.142 vs 0.091) - naive
  double counting partly offsets the loss by accident; it is not more correct.
- **Existence disagreements are real only under heavy loss.** Loss 0.0/0.3: no existence conflicts, edge F1 1.0 for every
  method. Loss 0.8: existence conflicts appear (large: 3 and 1), best single collector edge F1 0.984 (mean 0.979),
  pooled 1.000 (fusion recovers edges no single collector had enough evidence for); quorum 0.984 (it drops a real edge).
  Every fused edge had a `Resolution`: 24/24 runs.
- **Cost**: large capture (2,832 packets) 165 ms single collector; fused 1/2/4 collectors 264/357/472 ms (1.6x / 2.2x /
  2.9x), which includes the per-collector local graphs used to detect disagreement.

## Failure cases (measured, multi_service + large, 2 seeds unless noted)
- **Clock skew beyond the tolerance** (50 ms vs 1 ms): duplicates survive, accepted packets = 2.0x the true count,
  confidence error up to 0.056; inside the tolerance the result is exact.
- **Tolerance too wide**: a genuine repeating stream (identical keepalive every 0.5 s, alternately seen by two collectors)
  loses half its packets at tolerance 1 s (60 of 120 falsely merged, confidence error 0.047); 0 merges at 1 ms.
- **Fabricated edge from one collector**: pooled evidence keeps it (3 false edges kept, N=3 and N=2). Quorum removes all 3
  at N=3. At N=2 the default quorum (2 absent collectors) cannot fire - a 1-vs-1 tie has no arbiter; setting
  `quorum_min_absent=1` drops the fabrication but is only "drop anything unconfirmed".
- **Collectors on different network segments** (each real edge visible from one vantage point): pooled edge recall 1.0,
  quorum mean recall 0.5 (0.0-1.0), because quorum reads "not seen by others" as "contested".
- **Direction-split collectors** (asymmetric path): fused confidence equals the full capture (error 0.0); each single
  collector's confidence is off by 0.076 on average (up to 0.147).
- **Colluding collectors** are not tested: two collectors fabricating the same edge outvote an honest one.

## Limits
In-process, single machine, no network transport; collector identity is trusted (no authentication); de-duplication is
greedy nearest-match and can depend on arrival order only when timestamps are closer than the tolerance to more than one
candidate; memory grows with every distinct packet identity; per-collector local graphs are recomputed on each
`resolutions()` call; the simulation gives every collector traffic from one true capture, so unmodelled sensor errors
(truncation, packet mangling) are not covered.
