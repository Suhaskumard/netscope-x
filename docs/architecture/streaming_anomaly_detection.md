# Real-Time Anomaly Detection Pipeline (Phase 86)

`backend/flowmind/anomaly/streaming.py` (`StreamingAnomalyDetector`) judges nodes while their behavioral window is
still open, instead of after it closes. It is built and measured; **not wired into the pipeline**.

## Design
- Packets feed Phase 85's `IncrementalTopology`. Time is cut into tumbling windows (same epochs as the Phase 76 batch
  dataset). Windows before `scoring_start` are history.
- After each `ingest`, only nodes touched by the chunk are re-fingerprinted over the open window and scored with the
  **same** `detect_node_anomalies` / `assemble_node_fingerprint` the batch path uses (no second detector).
- A partial window is not a whole one, so while open only checks that stay valid on partial evidence are trusted: new
  ports/protocols, and upward deviation of destinations / byte count (those only grow). Everything else is judged when
  the window closes. Each (node, dimension) alerts at most once per window.

## Measured (`scripts/run_streaming_anomaly_benchmark.py`; 54 cells = 6 topologies x 3 completeness x 3 seeds)
- Quality equals batch: recall 0.96-1.00 in both; F1 within 0.01 per topology; false positives 1,620 streaming vs
  1,641 batch (both high: the detector itself is unchanged).
- Detection latency in stream time, injected onset to alert: 1.6-2.6 s (streaming) vs about 59.8 s (batch, which must
  wait for the 60 s epoch to end).
- Equivalence at window close: 1576/1656 node-window fingerprints identical; all 80 mismatches are a five-tuple
  that recurs in a later window (batch drops it from the earlier window by its last packet; the stream had only seen
  the earlier part) - checked per mismatch, not assumed. Alert sets identical in 32/54 cells; streaming-only 9,
  batch-only 30 alerts, all in cells with such mismatches.
- Load (real per-chunk `perf_counter` time, virtual arrival clock, 25-packet chunks):
  - small (850 pkts): keeps up from 200 to 100,000 pps; end-to-end latency p50 0.05-0.48 s, max 1.11 s at 200 pps
    (chunk-assembly wait dominates at low rate). Sub-second holds except that one max.
  - **large (11,530 pkts): does not keep up at any tested rate.** Chunk time p95 ~180-250 ms, max ~740 ms; the detector
    finishes 9.5-27 s behind real time; latency p50 5.9-11.5 s, max ~16-19 s. **The sub-second target is not met
    on the large topology.**

## Why, and limits
- Cost is dominated by `IncrementalTopology.flows()` (linear in everything seen so far, re-run per chunk) and by the
  full-window rescoring at window close. State is unbounded.
- A late packet for a closed window is ingested but that window is not re-scored; a flow spanning a boundary is judged
  on what was seen at close. Packets must arrive in timestamp order.
- Latency here is single-threaded, in-process, virtual arrival clock; no network, no queue, one machine.
- Not fixed here: a windowed/evicting flow store and per-node incremental features would remove the linear term.
