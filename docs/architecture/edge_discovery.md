# NETSCOPE-X — Edge Discovery

Phase 30 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 30 — EDGE DISCOVERY"): "Infer
communication relationships." FR-1.9 (`docs/requirements/system_requirements.md`) bundles Phases
29-30: "The system shall infer candidate nodes and edges exclusively from observed evidence, with no
access to laboratory ground truth at inference time." FR-1.10, tagged "(spec Phase 31)": "Every
inferred edge shall carry a confidence score, supporting evidence, observation count, timestamps, and
protocol list — never an arbitrary/unjustified confidence value."

Code: `backend/nettrace/topology/edges.py` (`discover_edges`), producing real `Edge`
(`backend/app/models/topology.py`, Phase 04) instances for the first time. Not yet called from
anywhere: `GET /topology` (`backend/app/api/routes/topology.py`) still raises `NotYetImplemented`,
since it needs a complete `TopologyGraph` (nodes + edges + confidence) — Phase 32's job, once this
phase's edges and Phase 29's nodes can be combined.

## Algorithm decision (made this phase)

Like node discovery (Phase 29), `docs/architecture/algorithm_selection.md` (Phase 05) does not cover
edge discovery — its 6 sections are flow reconstruction, role inference, anomaly detection, graph
criticality, path analysis, and dependency inference. This is an honest gap in the original Phase 05
planning, not silently papered over; the algorithm decision is made and justified here.

### Source: `flows.jsonl`, not raw packets — the opposite of node discovery

`docs/architecture/node_discovery.md` already committed to this design: an `Edge`'s `protocols`
(`List[str]`) and evidence need flow-level aggregation (protocol, byte/packet counts, session
boundaries) that a raw `Packet` doesn't provide on its own. `discover_edges` reads
`flows_path(root, capture_id)` via `reconstruct_flows`'s (Phase 23-28) already-reconstructed `Flow`
objects.

**This is a deliberate asymmetry with node discovery**, not an inconsistency: `reconstruct_flows`
excludes ICMP/OTHER packets from flow reconstruction by design (`reconstruct.py`'s own documented
scope), so a capture whose only traffic is ICMP produces real *nodes* (packets-based) but zero *edges*
(flows-based) — verified directly by
`test_discover_edges_icmp_only_capture_produces_zero_edges_despite_nodes_found`.

### Node-id resolution: `nodes` is a parameter, not re-derived

`discover_edges(root, capture_id, nodes, edge_confidence_packet_scale=...)` takes the caller's own
`discover_nodes(...)` output rather than re-scanning `packets.jsonl` itself. This keeps the function
pure and independently testable, avoids redundant I/O (the caller needs nodes anyway), and stays
correct if a future phase lifts Phase 29's "one IP → one Node" simplification — resolving through the
real `node_id` via a passed-in node list needs no rework then. A flow whose `src_ip`/`dst_ip` doesn't
resolve against the supplied `nodes` is silently skipped (never raised) — treated as caller-misuse,
consistent with `discover_nodes`'s own "never raise on bad/missing input" philosophy
(`test_discover_edges_flow_with_ip_not_in_nodes_is_skipped`). A flow whose `src_ip == dst_ip`
(self-referential) is skipped too: `Edge._no_self_loop` forbids a self-loop, and self-communication
isn't a relationship between two nodes
(`test_discover_edges_self_referential_flow_produces_no_self_loop_edge`).

### Edges are undirected

`source_node_id`/`target_node_id` are assigned by sorted `node_id` — a deterministic tie-break, not a
claim about who initiated the communication. When multiple flows between a pair disagree on initiator
(e.g. separate UDP sessions on different ports, or a TCP connection re-established in the opposite
direction later), there is no single honest "true" initiator to report at the edge level. Reporting one
anyway would itself be the kind of unjustified claim FR-1.10 explicitly forbids for *confidence*, and
the same honesty standard is applied here to directionality. Each flow's own `src_ip`/`direction`
already captures real per-flow initiation — that information isn't lost, just not collapsed into one
edge-level claim.

### Confidence: a provisional, evidence-backed formula — not Phase 31's job done early

`Edge.confidence` (`backend/app/models/topology.py`, Phase 04) is a required, non-optional `float` in
`[0, 1]`. `docs/architecture/data_contracts.md`'s own account of that schema's intent is explicit: "a
confidence score with no backing evidence cannot be constructed." So Phase 30 cannot construct a real
`Edge` without supplying *some* confidence value — leaving it out isn't an option the schema allows,
and a hardcoded placeholder constant (e.g. always `0.5`) would be exactly the "arbitrary/unjustified
confidence value" FR-1.10 forbids, arguably worse than a real, documented, provisional formula.

```
total_packet_count = sum(flow.features.packet_count for flow in this edge's flows)
confidence = 1 - exp(-total_packet_count / edge_confidence_packet_scale)
```

- **Real, not invented, signal**: `FlowFeatures.packet_count` (Phase 28) is already a genuine
  per-flow observation; this formula sums it across every flow aggregated into the edge.
- **Monotonic by construction**: `total_packet_count` is non-decreasing as more flows/evidence are
  aggregated (each contributes `>= 0` packets), and `1 - exp(-x)` is strictly increasing in `x` — so
  "more observed evidence never lowers confidence" holds structurally, not merely because
  `Edge.confidence`'s `Field(ge=0, le=1)` happens to allow it. Verified directly:
  `test_discover_edges_confidence_increases_with_more_observed_packets`.
- **Saturating, never certain**: the curve approaches but never reaches exactly `1.0` for any finite
  packet count — honest that packet volume alone should never claim absolute certainty. Verified with
  a 500-packet flow: `test_discover_edges_confidence_always_strictly_between_zero_and_one`.
- **Single-signal, deliberately**: `observation_count` (distinct flow count) is still reported on every
  `Edge` as its own required field, but is not separately weighted into the confidence formula.
  Combining two signals would need a second, currently-untuned weighting constant — exactly the
  "arbitrary" failure mode being avoided. `algorithm_selection.md` §6 (Dependency inference, a later,
  different concept — Phase 50+, scoring `DependencyEdge.strength`, not this `Edge.confidence`) uses a
  multi-signal weighted score for a structurally similar problem; its *shape* (interpretable,
  evidence-backed) is echoed here, but its specific machinery is not reused, since a much simpler
  single-signal formula already satisfies FR-1.10's "not arbitrary" bar for this simpler question
  ("do these two hosts talk," not "how strongly does one depend on the other").
- **One tunable parameter, `Settings`-driven (NFR-4)**: `edge_confidence_packet_scale`
  (`backend/app/core/config.py`, default `20.0`, `NETSCOPE_EDGE_CONFIDENCE_PACKET_SCALE`-overridable),
  following the `udp_session_idle_timeout_seconds` (Phase 25) precedent exactly. At
  `total_packet_count == scale`, confidence is `~0.63`. The default is a plausible, documented
  placeholder — explicitly **not** empirically calibrated. `discover_edges` itself takes this as a
  plain function parameter (default `20.0`, matching `Settings`'s own default) rather than reading
  `get_settings()` internally, mirroring `reconstruct_flows`'s own `udp_session_idle_timeout_seconds`
  parameter convention — only an API route (once one exists, Phase 32+) would read `get_settings()`
  and pass the value through.

**This is explicitly Phase 30's provisional answer to FR-1.9's "infer... from evidence," not Phase
31's "PROBABILISTIC EDGE CONFIDENCE" deliverable done early.** Phase 31 is expected to revisit,
calibrate, or replace this formula — informed by real lab data and, eventually, Phase 68's evaluation
matrix — not merely rubber-stamp it.

## Algorithm

`discover_edges(root, capture_id, nodes, edge_confidence_packet_scale=20.0)`:
1. Build `ip_to_node_id: Dict[str, str]` from every `str(ip)` in every `node.ip_addresses`.
2. If `flows_path(root, capture_id)` doesn't exist, return `[]`.
3. Read every `Flow`; empty list → `[]`.
4. Per flow, resolve `src_node_id`/`dst_node_id`; skip the flow if either is unresolved or they're
   equal.
5. Bucket surviving flows by `tuple(sorted((src_node_id, dst_node_id)))` — mirrors
   `reconstruct.py`'s own `_flow_key` canonicalization (A→B and B→A land in the same bucket) for the
   same reason.
6. Per bucket: `observation_count = len(flows)`; `protocols = sorted({f.protocol.value for f in
   flows})`; `first_observed`/`last_observed` = min/max of `first_seen`/`last_seen`; `evidence` = one
   descriptive string per flow (flow id, protocol, endpoints, packet/byte counts), ordered by
   `(first_seen, flow_id)`; `confidence` via the formula above.
7. Order edge buckets by `(first_observed, source_node_id, target_node_id)`; assign
   `edge_id = f"{capture_id}:edge:{index}"` — the same "first evidence observed" determinism rationale
   `discover_nodes`/`reconstruct_flows` already use, applied at edge granularity.

**Complexity:** O(F) for a single pass over F flows, plus O(F log F) to order evidence within buckets
and order the buckets themselves — dominated by the flow read, same shape as `discover_nodes`.

## Failure cases

- Missing or empty `flows.jsonl`: returns `[]`, never raises.
- A capture with flows but no TCP/UDP traffic at all (e.g. ICMP-only): `[]`, since no flows exist to
  aggregate — the documented asymmetry with node discovery.
- A flow referencing an IP outside the supplied `nodes`: that flow is skipped, not raised.
- A self-referential flow (`src_ip == dst_ip`): skipped, not raised, never constructs an invalid
  self-loop `Edge`.

## Known limitations

- **Undirected canonicalization.** No initiator is claimed at the edge level (see above) — a real,
  stated simplification, not an oversight.
- **Single-signal, uncalibrated confidence.** The formula is honest (real evidence, monotonic,
  saturating) but not yet validated against any ground truth or tuned against real lab traffic volumes
  — explicitly Phase 31/68's job.
- **No persistence artifact yet**, matching Phase 29: `discover_edges` returns `List[Edge]` only;
  nothing is written to `experiments/artifacts/paths.py`, deferred to Phase 32's combined
  `TopologyGraph`.
- **Not yet wired into any API route** — `GET /topology` remains `NotYetImplemented` pending Phase 32.

## Verification actually performed this phase

- `pytest backend/tests/test_nettrace_topology_edges.py -v` — **12/12 passed**: a single edge between
  two communicating nodes; multiple distinct node pairs with no cross-contamination; multiple flows
  for the same pair aggregating into one edge with correctly widened `first_observed`/`last_observed`
  and growing `observation_count`/`evidence`; `protocols` deduplicated and sorted across a
  TCP+UDP+TCP mix; deterministic ordering/ids across two identical runs; a missing and an empty
  `flows.jsonl` both returning `[]`; an ICMP-only capture producing zero edges despite `discover_nodes`
  finding both endpoints as nodes on the same capture; a self-referential flow producing no edge;
  confidence strictly higher for a heavily-observed pair than a lightly-observed one; confidence always
  in `[0, 1]` and never exactly `1.0` even for a 500-packet flow; a flow whose destination IP is absent
  from the supplied `nodes` list contributing no edge.
- Full repo suite (`pytest`, run from repo root) — **232/232 passed** (up from 220/220), no
  regressions.
- `python -m scripts.validate_data_contracts` — 38/38 passed, no regression (`Edge` unchanged since
  Phase 04).
- `python -m scripts.check_ground_truth_boundary` — clean: no import of `simulator.ground_truth`
  anywhere in `edges.py`.

## Status

Edge discovery (spec Phase 30, FR-1.9) is implemented and unit-verified: `discover_edges` produces
real `Edge` instances from real, already-reconstructed flow data, with a real (if provisional and
uncalibrated) evidence-backed confidence score, no ground-truth access, and no arbitrary values. It is
not yet wired into `GET /topology` or persisted to disk — both remain Phase 32's job, once a
`TopologyGraph` can combine this phase's edges with Phase 29's nodes. The confidence formula's
calibration is explicitly left open for Phase 31 to revisit.
