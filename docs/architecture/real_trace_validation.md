# Cross-domain validation against real traces (Phase 103)

`python -m scripts.run_real_trace_validation --traces-dir <dir of .pcap/.pcapng/.cap> [--root experiments_data] [--labels labels.json]`
(`experiments/real_trace_validation.py`). You supply the pcaps; nothing is downloaded. Output: `<root>/real_trace_validation/report.{json,md}`.

**Real traces have no ground-truth topology, so no number here is accuracy against truth.** Every metric is a proxy and the report
says so first.

## Per trace
1. Full pipeline: `ingest_pcap` -> `ensure_packets` -> `reconstruct_flows` -> `build_topology_graph` -> `estimate_dependency_strength`.
2. **Accounting** against an independent Scapy stream count: frames, IP frames, non-IP skipped, packets normalized, and
   `unexplained_drops` (IP frames the pipeline lost; anything nonzero is a defect finding), plus flows/nodes/edges.
3. **Edge recovery** against the flow record: share of flows landing on an edge, and edges with no supporting flow.
4. **Role agreement (proxy)**: a transparent well-known-port labeler (443/80/8080/8443 API, 5432 Database, 6379 Cache, 53 DNS,
   initiate-only Client; everything else left unlabeled) vs the classifier under leave-one-node-out, beside the majority-class
   baseline. Inflated by construction: the classifier also sees the ports.
5. **Stability** under packet subsampling (completeness 1.0/0.75/0.5/0.25): edge-set Jaccard and node retention vs the full trace.
6. Optional `--labels` (`{"<file>": {"edges": [[ip, ip], ...]}}`) gives true edge precision/recall for that trace.

A file that fails to parse is reported FAILED with the exception class; one over `--max-bytes` (default 200 MB, ingest reads the
whole file) is REFUSED. Neither is skipped silently.

## Real vs synthetic
The same stability function runs on a synthetic `small` capture, and the table flags every completeness level where real is worse.
Truth-based synthetic edge F1 is listed for context only; it has no real-trace counterpart.

## Verified
`experiments/tests/test_real_trace_validation.py`, on pcaps written by the test with Scapy (known exchange, an ARP frame, an IPv6
frame): accounting equals the independent count with 0 unexplained drops; labeler distribution, edge recovery, determinism, stability
at 1.0 is exactly identical, labeled precision/recall, FAILED/REFUSED handling, NOT RUN with no traces, no `ground_truth` import.
These prove the harness computes what it claims. They are not real-world traces.

## NOT verified
**No real-world trace has been run.** No pcaps were supplied in this session, so there is no external-validity result yet; the run
prints NOT RUN and produces no numbers. Behavior on large captures is untested (whole-file read; no streaming ingest).

## Limits
Proxy metrics can reveal breakage and fragility, but cannot show the topology is correct. Non-IP traffic is skipped by the
normalizer. Traces with few nodes give too few labeled nodes for the role check (reported as insufficient, not guessed).
