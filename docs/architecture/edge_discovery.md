# NETSCOPE-X — Edge Discovery and Probabilistic Edge Confidence

Phases 30-31 deliverable, per the master spec (`NETSCOPE (1).pdf`): §"PHASE 30 — EDGE DISCOVERY"
("Infer communication relationships") and §"PHASE 31 — PROBABILISTIC EDGE CONFIDENCE" ("Represent
Node A → Node B with: confidence, evidence, observation count, timestamps, protocols. Do not use
arbitrary confidence values."). FR-1.9 (`docs/requirements/system_requirements.md`) bundles Phases
29-30: "The system shall infer candidate nodes and edges exclusively from observed evidence, with no
access to laboratory ground truth at inference time." FR-1.10, tagged "(spec Phase 31)": "Every
inferred edge shall carry a confidence score, supporting evidence, observation count, timestamps, and
protocol list — never an arbitrary/unjustified confidence value."

Code: `backend/nettrace/topology/edges.py` (`discover_edges`), producing real `Edge`
(`backend/app/models/topology.py`, Phase 04) instances. Not yet called from anywhere: `GET /topology`
(`backend/app/api/routes/topology.py`) still raises `NotYetImplemented`, since it needs a complete
`TopologyGraph` (nodes + edges + confidence) — Phase 32's job, once these edges and Phase 29's nodes
can be combined.

This document originally described Phase 30's single-signal confidence formula; it is now updated in
place to describe Phase 31's multi-signal replacement, since both phases modify the same function
rather than adding a new pipeline stage.

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

### Confidence: a multi-signal, evidence-backed formula (Phase 31) — still provisional, not calibrated

`Edge.confidence` (`backend/app/models/topology.py`, Phase 04) is a required, non-optional `float` in
`[0, 1]`. `docs/architecture/data_contracts.md`'s own account of that schema's intent is explicit: "a
confidence score with no backing evidence cannot be constructed." So a real `Edge` can never omit
confidence or set it arbitrarily.

**What "probabilistic" means here, and what it deliberately does not mean.** RQ1
(`docs/research/research_questions.md`) explicitly defers all ground-truth-based accuracy/calibration
evaluation to Phase 32/68, and REPRO-4 forbids ground truth as an inference-time input. So Phase 31
cannot mean "validated against known-correct labels" (that's RQ2/role-inference's Phase 37/68 concept,
a different mechanism entirely). The applicable precedent in this project's own vocabulary is
`algorithm_selection.md` §6 (dependency inference, a later, different phase/field —
`DependencyEdge.strength`, not this `Edge.confidence`): "a weighted multi-signal scoring function
combining independent, interpretable signals," justified as satisfying "confidence, not certainty"
without full statistical rigor. Phase 31 mirrors that *shape* for `Edge.confidence`, using only
already-real `Flow`-derived signals — never claiming calibrated accuracy, only that each signal is
real, independently-observed evidence.

**Six independent terms, combined via noisy-OR:**
```
p_volume = 1 - exp(-total_packet_count / edge_confidence_packet_scale)     # Phase 30's original term
s = edge_confidence_signal_strength

i_established = 1 if any flow in the bucket has tcp_state == ESTABLISHED else 0    # TCP only
i_fingerprint = 1 if any flow in the bucket has fingerprinted_protocol is not None else 0
i_tls         = 1 if any flow in the bucket has tls_version is not None else 0     # TCP only
i_persistent  = 1 if any flow in the bucket has features.is_persistent else 0
bidir_max     = max(2 * min(r, 1-r) for r in each flow's forward_byte_ratio)       # 0..1, peaks at r=0.5

confidence = 1 - (1-p_volume) * (1-s*i_established) * (1-s*i_fingerprint)
                * (1-s*i_tls) * (1-s*i_persistent) * (1-s*bidir_max)
```
Implemented as `_signal_indicators` + `_confidence` in `edges.py`.

**Why noisy-OR, not a weighted average.** Each signal is treated as independent evidence *for* a real
relationship; noisy-OR (`1 - ∏(1 - term_i)`) is the standard way to combine independent "evidence for"
terms without needing relative-importance weights between them. Every `term_i ∈ [0, 1)`, so the
product is always `> 0` and confidence is always `< 1` — bounded by construction (no post-hoc
clamping needed), and monotonic by construction: a new positive signal can only shrink the product,
never grow it, so "more evidence never lowers confidence" holds structurally, generalizing Phase 30's
own packet-only monotonicity property. A weighted average has no such built-in guarantee.

**Why five *new* signals now, when Phase 30 explicitly declined to add a second weighted term for
`observation_count`.** Phase 30 rejected weighting `observation_count` because it is *redundant* with
packet volume — more flows almost always means more packets, not independent evidence. The five
Phase 31 signals are each structurally independent of packet volume and of each other: a handshake
completing, a protocol being fingerprinted, TLS negotiating, a five-tuple recurring, and traffic being
bidirectional are different observable facts packet count alone cannot capture. `duration_seconds` and
`byte_count` were considered and rejected for the same redundancy reason Phase 30 already established;
`burstiness` was rejected because its evidentiary direction is genuinely ambiguous (no defensible
monotonic "more real" mapping exists without an arbitrary judgment call).

**One shared tunable, not one per signal.** All four boolean signals share a single
`edge_confidence_signal_strength` constant (`backend/app/core/config.py`, default `0.3`,
`NETSCOPE_EDGE_CONFIDENCE_SIGNAL_STRENGTH`-overridable, `gt=0, lt=1`) as their evidence-strength
ceiling — there is no principled basis today to claim TLS negotiation matters more than an established
handshake, and asserting different per-signal weights would itself be exactly the "arbitrary" judgment
FR-1.10 forbids. Bidirectionality uses the same shared constant but a fixed, parameter-free mapping
(`2 * min(r, 1-r)`) rather than a second threshold — self-evidently justified by its endpoints (0 at
one-way traffic, 1 at perfectly balanced traffic), so no new tunable was needed for it.

**Structurally-inapplicable signals are never penalized.** `tcp_state`/`tls_version` are always `None`
for a UDP-only bucket (`Flow`'s own validators enforce this) — the indicator is `0`, contributing a
multiplicative identity factor of `1`, exactly as if the signal simply hadn't fired. A UDP-only edge is
never worse off than an otherwise-identical bucket that structurally can't produce TCP-only evidence;
it just doesn't get that particular boost. Verified directly:
`test_discover_edges_udp_only_edge_has_no_tcp_signals_but_confidence_still_sensible`.

**Existence, not fraction, semantics.** A boolean signal fires if *any* flow in the bucket exhibits it
— not a fraction of flows. This is required for monotonicity: a fraction would shrink as more
(unrelated, weaker) flows join the same edge, which would mean adding evidence could lower confidence.
One strong flow's evidence is never diluted away by other, weaker flows sharing its edge.

**Worked examples** (`packet_scale=20.0`, `signal_strength=0.3`):
- 2 packets, incomplete handshake, no other signals, one-way traffic → `confidence = p_volume ≈ 0.095`
  (identical to what Phase 30 alone would have produced — no regression when no new signal fires).
- Same 2 packets, but handshake completed, fingerprinted, `forward_byte_ratio=0.4`:
  `p_volume=0.095`, `i_established=i_fingerprint=1`, `bidir=0.8` → `confidence ≈ 0.663`. A large jump
  at identical packet volume — qualitative evidence, not just volume, now moves confidence.
- 40-packet UDP edge, persistent, fingerprinted `dns`, balanced traffic (TCP-only signals structurally
  inapplicable): `p_volume=0.865`, `i_fingerprint=i_persistent=1`, `bidir=1.0` → `confidence ≈ 0.954`.

All three examples are directly exercised (not just hand-derived) by
`test_discover_edges_confidence_higher_with_established_handshake_than_partial`,
`test_discover_edges_confidence_higher_with_tls_negotiated`,
`test_discover_edges_confidence_higher_with_fingerprinted_protocol`,
`test_discover_edges_confidence_higher_with_bidirectional_traffic`, and the pure-math
`test_discover_edges_confidence_monotonic_with_combined_signals` /
`test_discover_edges_all_positive_signals_exceeds_packet_volume_alone`.

**`evidence` extension.** Each per-flow line (`_evidence_line`) now also states any signal facts that
fired for that flow (`tcp_state=established`, `fingerprinted_protocol=http`, `tls_version=TLS 1.3`,
`is_persistent=True`, `forward_byte_ratio=0.400`), keeping one line per flow
(`len(evidence) == observation_count + 1`, see next point). A bucket-level summary line
(`_evidence_summary_line`) is appended after every per-flow line, e.g. `"confidence signals:
established_handshake=yes, fingerprinted_protocol=yes, tls=no, persistent=no,
bidirectional_strength=0.800 (signal_strength=0.3) -> confidence=0.663"` — so a reviewer can see *why*
a value was assigned without hand-deriving the formula. This is a deliberate change from Phase 30:
`evidence` now has `observation_count + 1` entries, not `observation_count` — verified by
`test_discover_edges_evidence_summary_line_present_and_reflects_signals` and reflected in the revised
`test_discover_edges_aggregates_multiple_flows_for_same_pair`.

This remains explicitly provisional: real calibration against ground truth is Phase 32/68's job, kept
strictly out of this module per REPRO-4. Nothing here claims measured accuracy — only that six signals
are each real, independently-observed evidence, combined without an arbitrary relative weighting.

## Algorithm

`discover_edges(root, capture_id, nodes, edge_confidence_packet_scale=20.0,
edge_confidence_signal_strength=0.3)`:
1. Build `ip_to_node_id: Dict[str, str]` from every `str(ip)` in every `node.ip_addresses`.
2. If `flows_path(root, capture_id)` doesn't exist, return `[]`.
3. Read every `Flow`; empty list → `[]`.
4. Per flow, resolve `src_node_id`/`dst_node_id`; skip the flow if either is unresolved or they're
   equal.
5. Bucket surviving flows by `tuple(sorted((src_node_id, dst_node_id)))` — mirrors
   `reconstruct.py`'s own `_flow_key` canonicalization (A→B and B→A land in the same bucket) for the
   same reason.
6. Per bucket: `observation_count = len(flows)`; `protocols = sorted({f.protocol.value for f in
   flows})`; `first_observed`/`last_observed` = min/max of `first_seen`/`last_seen`; `confidence` via
   the noisy-OR formula above; `evidence` = one descriptive string per flow (flow id, protocol,
   endpoints, packet/byte counts, plus any signal facts that fired for it), ordered by
   `(first_seen, flow_id)`, followed by one bucket-level confidence-signal summary line.
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
- **Multi-signal but still uncalibrated.** All five corroborating signals share one uniform strength
  constant rather than empirically-justified relative weights — there is no basis yet (absent
  ground-truth calibration, which REPRO-4 forbids here) to claim one signal matters more than another.
  Real calibration remains Phase 32/68's job, not invented in this module.
- **`is_persistent`'s structural UDP-only asymmetry.** Per Phase 28's own documented scope,
  `is_persistent` only ever fires for UDP flows under the current pipeline — a TCP-only edge can never
  benefit from this signal, purely because of how flows are structurally built, not because TCP
  connections are less persistent in reality. Accepted as a real, stated limitation.
- **No persistence artifact yet**, matching Phase 29: `discover_edges` returns `List[Edge]` only;
  nothing is written to `experiments/artifacts/paths.py`, deferred to Phase 32's combined
  `TopologyGraph`.
- **Not yet wired into any API route** — `GET /topology` remains `NotYetImplemented` pending Phase 32.

## Verification actually performed this phase

- `pytest backend/tests/test_nettrace_topology_edges.py -v` — **20/20 passed** (12 from Phase 30,
  revised where needed, plus 8 new Phase 31 tests): a single edge between two communicating nodes;
  multiple distinct node pairs with no cross-contamination; multiple flows for the same pair
  aggregating into one edge with correctly widened `first_observed`/`last_observed` and growing
  `observation_count`/`evidence`; `protocols` deduplicated and sorted across a TCP+UDP+TCP mix;
  deterministic ordering/ids across two identical runs; a missing and an empty `flows.jsonl` both
  returning `[]`; an ICMP-only capture producing zero edges despite `discover_nodes` finding both
  endpoints as nodes on the same capture; a self-referential flow producing no edge; confidence
  strictly higher for a heavily-observed pair than a lightly-observed one; confidence always in
  `[0, 1]` and never exactly `1.0`; a flow whose destination IP is absent from the supplied `nodes`
  list contributing no edge; confidence strictly higher with an established handshake than a partial
  one (equal packet counts); strictly higher with a real negotiated TLS session than without (equal,
  already-established handshakes); strictly higher with a fingerprinted protocol than without (equal
  packet counts/state); strictly higher with genuinely bidirectional traffic than one-way traffic
  (equal packet counts); non-decreasing confidence as packet volume, then each of the five signals in
  turn, are added one at a time (pure `_confidence` math test); all-positive-signals confidence
  exceeding packet-volume-alone by a real, non-negligible margin; a UDP-only bucket reaching high
  confidence via non-TCP signals with no penalty for the structurally-inapplicable TCP-only signals;
  the bucket-level evidence summary line present and reflecting the actual fired signals.
- Full repo suite (`pytest`, run from repo root) — **240/240 passed** (up from 232/232), no
  regressions.
- `python -m scripts.validate_data_contracts` — 38/38 passed, no regression (`Edge` unchanged since
  Phase 04).
- `python -m scripts.check_ground_truth_boundary` — clean: no import of `simulator.ground_truth`
  anywhere in `edges.py`.

## Status

Edge discovery (spec Phase 30, FR-1.9) and probabilistic edge confidence (spec Phase 31, FR-1.10) are
both implemented and unit-verified: `discover_edges` produces real `Edge` instances from real,
already-reconstructed flow data, with a real, multi-signal, evidence-backed confidence score combining
packet volume with five independent corroborating signals via noisy-OR — no ground-truth access, no
arbitrary relative weighting between signals. It is not yet wired into `GET /topology` or persisted to
disk — both remain Phase 32's job, once a `TopologyGraph` can combine these edges with Phase 29's
nodes. Real calibration of the confidence formula (as opposed to its current honest-but-provisional
shape) remains explicitly out of scope until Phase 32/68's ground-truth-backed evaluation.
