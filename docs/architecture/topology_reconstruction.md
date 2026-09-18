# NETSCOPE-X — Probabilistic Topology Reconstruction

Phase 32 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 32 — PROBABILISTIC TOPOLOGY
RECONSTRUCTION"): "Produce the complete inferred network graph. Output: nodes, edges, confidence,
evidence, timestamps, protocols. Compare against ground truth." FR-1.11: "The system shall produce a
complete probabilistic topology graph (nodes, edges, confidence, evidence, timestamps, protocols) and
support comparison against ground truth for evaluation purposes only (spec Phase 32; RQ1)."

This phase has two halves, deliberately split across the ground-truth-import boundary
(`scripts/check_ground_truth_boundary.py`, spec §4, REPRO-4): **Half A** assembles and serves the
real inferred graph (inference-side, never touches ground truth); **Half B** compares that graph
against ground truth (evaluation-only, never reachable from inference). This document covers both,
building on `docs/architecture/node_discovery.md` (Phase 29) and `docs/architecture/edge_discovery.md`
(Phase 30-31), which it references rather than duplicates.

## Half A: assembling and serving the real graph

### `build_topology_graph` (`backend/nettrace/topology/graph.py`)

```python
def build_topology_graph(root, capture_id, graph_id, edge_confidence_packet_scale=20.0,
                          edge_confidence_signal_strength=0.3) -> TopologyGraph:
    nodes = discover_nodes(root, capture_id)
    edges = discover_edges(root, capture_id, nodes, edge_confidence_packet_scale, edge_confidence_signal_strength)
    return TopologyGraph(graph_id=graph_id, generated_at=now, nodes=nodes, edges=edges)
```

A thin, pure combination of Phase 29's `discover_nodes` and Phase 30-31's `discover_edges` — no new
inference logic, just assembly. `graph_id` is a caller-supplied parameter, not derived internally,
for the same reason `discover_edges` takes `nodes` as a parameter rather than re-deriving it: keeps
the function pure and testable, with the identity-scheme decision left to the caller.

### `graph_id` scheme: the capture_id itself

`GET /topology` passes `graph_id=capture_id` — a stable, non-timestamped, non-content-hashed label.
Rejected alternatives:
- **A timestamp** would break the "same input → same output" determinism story every other id scheme
  in this pipeline (`node_id`, `edge_id`, `flow_id`) already guarantees — two calls against an
  unchanged capture would report different `graph_id`s for no real reason (NFR-3).
- **A content hash** (of nodes+edges) would make `graph_id` unstable across mere `Settings` tuning —
  changing `edge_confidence_packet_scale` by a hair would silently change `graph_id`, which is the
  wrong scope of "identity": the graph's identity is "the topology as currently understood for this
  capture," not "this exact confidence snapshot."

Ground truth's own `graph_id="lab-ground-truth"` (a stable constant label, not derived from content or
time) is direct precedent for keeping `graph_id` a stable identity label.

### `GET /topology` (`backend/app/api/routes/topology.py`)

Mirrors `GET /flows` exactly: read `get_settings()`, check `pcap_path(...).is_file()` (404
`capture_not_found` via `CaptureNotFoundError` if missing), call `normalize_pcap` then
`reconstruct_flows` inline (required because `discover_nodes`/`discover_edges` read
`packets.jsonl`/`flows.jsonl`, neither of which exists on a freshly-ingested capture that has only had
`raw.pcap` staged), build the graph via `build_topology_graph`, **persist it via
`write_json(topology_path(root, capture_id, graph.graph_id), graph)`, then return it**.

**This is not a cache.** The route never reads `topology_path` back — every call recomputes the graph
fresh from `packets.jsonl`/`flows.jsonl`, exactly like `/flows` recomputes flows fresh on every call.
The write is a side-effect research artifact for `experiments/`-layer consumers (Half B, ad hoc
analysis, a future Phase 68 sweep) to pick up without duplicating the reconstruction call themselves.
This is not a new pattern: `reconstruct_flows` (which `/flows` already calls every request) already
writes `flows.jsonl`/`packets.jsonl` on every call — Phase 32 extends the same "recompute and persist
fresh, no cache" contract one layer up, to the combined graph.

`edge_confidence_packet_scale`/`edge_confidence_signal_strength` are read from `get_settings()` and
passed through, exactly mirroring how `/flows` passes `udp_session_idle_timeout_seconds` through.

## Half B: comparison against ground truth (evaluation-only)

### Location: `experiments/metrics/topology_comparison.py`

New package — the first real population of that spec-named directory (`experiments/artifacts/`
already existed for generic serialization I/O; `experiments/metrics/` is a different concern,
analysis/comparison, not storage). Never imported by anything under `backend/nettrace/`/`backend/app/`
— see the ground-truth-boundary compliance argument below.

### Identity mismatch: why matching goes through IP addresses, not ids

Inferred ids (`f"{capture_id}:node:{index}"`, `f"{capture_id}:edge:{index}"`) and ground-truth ids
(the lab's own service names, e.g. `node_id="server"`, `edge_id="client->server"`) come from two
independently-run schemes with no shared vocabulary — comparing them by string equality would always
report zero matches, regardless of actual structural agreement. The one genuinely shared identity
space on both sides is `Node.ip_addresses` (`IPvAnyAddress` on both). So:
- **Nodes match** by exact `ip_addresses`-set equality (not overlap — a future phase may correlate
  multiple addresses per node on either side, and overlap would over-count that case).
- **Edges match** by the *unordered* pair of their two endpoints' resolved IP sets — `frozenset({source_ips,
  target_ips})` — not by `source_node_id`/`target_node_id` position.

### Worked example: why edge matching is direction-agnostic

Inferred edge: `source_node_id="cap-1:node:1"` (10.0.0.2), `target_node_id="cap-1:node:0"` (10.0.0.1) —
`discover_edges` (Phase 30) canonicalizes by sorted `node_id`, carrying no initiator claim. Ground
truth: `edge_id="client->server"`, `source="client"` (10.0.0.1), `target="server"` (10.0.0.2) — a real
directional declaration from the lab's own architecture. Comparing `(source, target)` tuples directly
would report these as *different* edges (`{2,1}` vs `{1,2}` in positional terms) despite them being the
same real relationship. Resolving both to the unordered pair `{{"10.0.0.1"}, {"10.0.0.2"}}` correctly
matches them. Treating this as a mismatch would penalize inference for correctly declining to claim an
initiator it has no honest basis to claim (per Phase 30's own undirected-edges design decision) —
exactly the kind of unjustified precision FR-1.10 already rejected for confidence, applied here to
directionality. Verified directly: `test_edge_matching_ignores_source_target_direction`.

### Precision/recall/F1

Standard set-based precision/recall over the matched IP-identity sets:
```
precision = |matched| / |predicted|
recall    = |matched| / |actual|
f1        = 2 * precision * recall / (precision + recall)
```
Two conventions stated explicitly (never left implicit): **empty vs. empty** (nothing on either side)
is defined as perfect agreement (`1.0`/`1.0`/`1.0` — there is nothing to disagree on); **empty vs.
nonempty** is `0.0` on whichever metric involves the empty side as its denominator. Both verified by
`test_empty_vs_empty_is_perfect_agreement_and_empty_vs_nonempty_is_zero`.

### `graph_similarity = (node_f1 + edge_f1) / 2`

No formula is spec-mandated (RQ1 names "a graph-similarity metric" without specifying one;
`docs/architecture/algorithm_selection.md` doesn't cover graph comparison either — the same "self-
defined and justified here" situation Phases 26/29-31 were already in for their own uncovered
algorithms). Equal weighting between node and edge agreement is chosen because nothing today justifies
weighting one over the other — the identical "no principled basis to weight one signal above another"
reasoning already used and defended for Phase 31's noisy-OR edge-confidence signals, reused here rather
than re-derived from scratch. Rejected alternatives: edge-weighted averaging (would need a new,
currently-unjustifiable weight constant); graph-edit-distance (expensive, and edit operations don't map
cleanly onto confidence-scored, evidence-backed edges); Jaccard over raw combined edge sets alone
(ignores node correctness, double-counts what F1 already balances). This is explicitly a **provisional,
self-defined metric**, not a claim of validated accuracy — real formula validation against a range of
real topologies is Phase 68's job (RQ1's own "Status: RQ1→Phase 32/68" framing).

### `TopologyComparisonResult`, not `MetricResult`

`MetricResult` (`backend/app/models/metric.py`, Phase 04) requires a non-optional `experiment_id` —
"a metric with no experiment behind it is not legitimate" per its own design intent. No experiment
registry exists anywhere in this repository yet (`experiments/runners/` doesn't exist). Inventing a
plausible-looking `experiment_id` (e.g. `f"{capture_id}-{timestamp}"`) with no real registered
`Experiment` behind it would itself be exactly the kind of metric that *looks* legitimate but isn't —
precisely what spec §21 ("No Fake Metrics") forbids. `compare_topology_to_ground_truth` therefore
returns a plain, frozen `TopologyComparisonResult` dataclass. Wrapping this in a real `MetricResult` is
left to whichever future phase (68) has a genuine experiment to anchor it to — inventing that wrapper
prematurely would be worse than not having it.

### Ground-truth-boundary compliance

Import graph, traced explicitly: `backend/app/api/routes/topology.py` imports
`backend/nettrace/topology/graph.py`, which imports `discovery.py`/`edges.py` — none of these import
anything under `experiments/metrics/` or `simulator.ground_truth`. `experiments/metrics/
topology_comparison.py` imports only `backend/app/models/topology.py` (the shared data contracts,
not inference code) and is itself never imported from anywhere under `backend/`. Ground truth data
reaches this module only via `experiments/artifacts/io.py::read_ground_truth_generation` (an existing
Phase 17 primitive, already used outside `simulator/`) — `topology_comparison.py` never imports
`simulator.ground_truth` directly either. `scripts/check_ground_truth_boundary.py`'s AST scan confirms
zero violations after this phase. `compare_topology_to_ground_truth` is invoked only from
`experiments/tests/test_topology_comparison.py` — never from a live API response, honoring FR-1.11's
"for evaluation purposes only."

## Known limitations

- Node/edge attribute agreement (protocol correctness, confidence accuracy) is out of scope for this
  phase's comparison — only structural presence/absence (which nodes/edges exist) is measured. Attribute-
  level evaluation is a natural Phase 68 extension.
- `graph_similarity`'s equal node/edge weighting is a documented, provisional choice, not an
  empirically-derived one.
- `experiments/artifacts/paths.py::ground_truth_topology_path` is a stale, unused leftover from Phase
  10's non-versioned layout — real ground truth reads/writes go through the versioned
  `write_ground_truth_generation`/`read_ground_truth_generation` machinery (Phase 17). Not touched by
  this phase; noted here so a future phase doesn't accidentally start using the dead path.
- No end-to-end run against real Docker-lab ground truth was performed this phase (no Docker in this
  session's environment, consistent with every prior Docker-dependent phase's own limitation note) —
  `compare_topology_to_ground_truth` is verified against synthetic `TopologyGraph` fixtures only.

## Verification actually performed this phase

- `pytest backend/tests/test_api.py -v -k topology` — **4/4 passed**: 404 on an unknown capture; a
  real end-to-end `POST /capture` → `GET /topology` producing a real graph (4 nodes, 2 edges from a
  real 2-flow pcap) with every edge's `confidence` in `[0,1]` and non-empty `evidence`/`protocols`;
  `graph_id == capture_id`; identical `nodes`/`edges` across two calls against the same capture;
  persistence to `topology_path` round-tripping via `read_json`.
- Full `pytest backend/tests/test_api.py` — **29/29 passed** (the old generic-501 topology case
  removed, four new real-behavior tests added).
- `pytest experiments/tests/test_topology_comparison.py -v` — **5/5 passed**: perfect match gives all
  metrics `1.0`; a ground-truth-only extra node/edge drops recall but not precision; an inferred-only
  extra node/edge drops precision but not recall; empty-vs-empty and empty-vs-nonempty handled per the
  documented convention; edge matching correctly ignores declared direction.
- Full repo suite (`pytest`, run from repo root) — **248/248 passed** (up from 240/240), no
  regressions.
- `python -m scripts.validate_data_contracts` — 38/38 passed, no regression (`TopologyGraph`/`Node`/
  `Edge` unchanged since Phase 04).
- `python -m scripts.check_ground_truth_boundary` — clean: no import of `simulator.ground_truth`
  anywhere in `backend/` or the new `experiments/metrics/` module.

## Status

Probabilistic topology reconstruction (spec Phase 32, FR-1.11) is implemented and verified end-to-end
for real: `GET /topology` now returns a genuine, persisted `TopologyGraph` combining Phase 29's nodes
and Phase 30-31's edges, recomputed fresh on every request. Ground-truth comparison is implemented as a
real, tested, evaluation-only capability (`compare_topology_to_ground_truth`), strictly isolated from
the inference pipeline and never claiming validated accuracy — that remains Phase 68's job, informed by
real lab runs this session's environment cannot execute (no Docker).
