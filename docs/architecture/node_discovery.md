# NETSCOPE-X — Node Discovery

Phase 29 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 29 — NODE DISCOVERY"): "Infer
active nodes exclusively from observations." FR-1.9 (`docs/requirements/system_requirements.md`):
"The system shall infer candidate nodes and edges exclusively from observed evidence, with no access
to laboratory ground truth at inference time (spec §4; Phase 29–30)."

Code: `backend/nettrace/topology/discovery.py` (`discover_nodes`), producing real `Node`
(`backend/app/models/topology.py`, Phase 04) instances for the first time — the data contract has
existed since Phase 04 but was unpopulated until now. `discover_nodes` is not called from anywhere
yet: `GET /topology` (`backend/app/api/routes/topology.py`) still raises `NotYetImplemented`, since it
needs a complete `TopologyGraph` (nodes + edges + confidence), which is Phase 32's deliverable, built
on top of Phase 30's edge discovery. This phase's output is implemented and unit-verified, but not yet
consumed by any other module or API route.

## Algorithm decision (made this phase)

Like protocol fingerprinting (Phase 26), `docs/architecture/algorithm_selection.md` (Phase 05) does
not cover node discovery — that doc's 6 sections are flow reconstruction, role inference, anomaly
detection, graph criticality, path analysis, and dependency inference. This is an honest gap in the
original Phase 05 planning, not silently papered over here; the algorithm decision is made and
justified in this document instead.

**Source: `packets.jsonl`, not `flows.jsonl`.** FR-1.9 requires nodes to be inferred "exclusively from
observed evidence" — the full set of evidence a capture provides is every normalized packet
(`backend/nettrace/normalize.py`, Phase 22's output), not just the TCP/UDP subset
`reconstruct_flows` (Phase 23) groups into flows. `reconstruct.py`'s own docstring is explicit that
flow reconstruction's "Scope: only TCP and UDP are grouped into flows... ICMP/OTHER packets are
excluded." A host whose only observed traffic is ICMP (e.g. only ever answering pings, or only ever
sending an unreachable error) would be invisible to a flows-based node discovery — that is evidence
being discarded, not "exclusively from observed evidence." Reading `packets.jsonl` directly costs
nothing (`flows.jsonl` is itself derived from the same file — `reconstruct_flows` reads the identical
`packets_path`) and makes the node set a strict superset of every IP any flow could reference.

This stays coherent with a future Phase 30: edges are inherently a *flow* concept (an `Edge` needs
`protocols: List[str]`, which only pairwise `Flow` aggregation provides), so the natural design is
edges derived from `flows.jsonl` while nodes (this phase) are the broader packets-based set. Because
node discovery's IP set is a superset of anything a flow could reference, every future edge's
`source_node_id`/`target_node_id` will always resolve against an existing node —
`TopologyGraph._edges_reference_known_nodes`'s validator is satisfiable by construction, not by luck.

**Algorithm:** `discover_nodes(root, capture_id)`:
1. If `packets_path(root, capture_id)` doesn't exist, return `[]` immediately.
2. Read every `Packet` in the capture.
3. For each packet, treat `str(src_ip)` and `str(dst_ip)` as observed node addresses; maintain a
   running per-IP min/max of `timestamp`.
4. Order the distinct IPs by `(first_observed, ip)` — the same "first packet observed" determinism
   rationale `reconstruct_flows` already uses for its own flow ordering, applied at node granularity.
5. Emit one `Node` per IP: `node_id=f"{capture_id}:node:{index}"`, `ip_addresses=[ip]`,
   `first_observed`, `last_observed`.

**Complexity:** O(P) for a single pass over P packets (dict lookups/updates are O(1) amortized), plus
O(N log N) to order the N distinct IPs found — dominated by the packet read, same shape as
`reconstruct_flows`.

## One IP → one Node (a deliberate simplification)

`Node.ip_addresses` is a list, anticipating a future need to correlate multiple observed addresses as
one physical node (NAT, a multi-homed host, a host that changes address mid-capture). This phase
always emits a single-element list. Merging addresses needs *additional* evidence this phase doesn't
compute — a shared behavioral fingerprint, a shared link-layer address (`Packet` carries no MAC field
at all) — and inventing that correlation now, without a concrete later-phase requirement driving it,
would be exactly the kind of unjustified complexity the spec's engineering principles warn against.
Left as a real, stated limitation, not silently assumed away.

## No persistence artifact yet

`discover_nodes` returns `List[Node]` only; nothing is written to disk. `experiments/artifacts/paths.py`
has no `nodes_path()`, and none was added. Phase 32 is what actually needs to persist a *combined*
`TopologyGraph` (nodes + edges + confidence together, at `topology_path`), and inventing a
Phase-29-only file format now risks being redefined the moment that combined shape is known — the
same reasoning that kept Phase 26's protocol fingerprinting a pure function consumed by
`reconstruct_flows` rather than its own artifact.

## Failure cases

- Missing `packets.jsonl` (capture never ingested, or wrong `capture_id`): returns `[]`, never raises.
- Empty `packets.jsonl` (capture ingested but zero packets recorded): also returns `[]`.
- A packet appearing only as a source, or only as a destination, across the whole capture: the address
  is still discovered as a node either way — nothing about the algorithm favors one role.

## Verification actually performed this phase

- `pytest backend/tests/test_nettrace_topology_discovery.py -v` — **8/8 passed**: multiple distinct
  IPs are each discovered as their own node; `first_observed`/`last_observed` reflect the true
  cross-packet min/max for an IP appearing as both source and destination over time (not just the
  first or last packet in the capture); repeated calls on identical input are byte-for-byte identical
  (proving determinism), with a same-timestamp tie between two IPs breaking lexicographically; a
  missing `packets.jsonl` and an existing-but-empty one both return `[]` without raising; an ICMP-only
  packet's two endpoints are discovered as nodes even though the same fixture produces zero flows from
  `reconstruct_flows` (directly exercising the packets-vs-flows design decision above); an IP that only
  ever appears as a destination, and one that only ever appears as a source, are each still discovered.
- Full backend suite (`pytest backend/tests`) — **122/122 passed**, no regressions.
- Full combined suite (`pytest backend/tests experiments/tests simulator/tests`, run from repo root as
  plain `pytest`) — **220/220 passed**, no regressions.
- `python -m scripts.validate_data_contracts` — 38/38 passed, no regression (unaffected by this phase,
  `Node` was already a valid contract since Phase 04).
- `python -m scripts.check_ground_truth_boundary` — clean: "OK: no import of simulator.ground_truth
  found outside the allowed generation/evaluation/test code." `discovery.py` imports nothing from
  `simulator.ground_truth`.

## Status

Node discovery (spec Phase 29, FR-1.9) is implemented and unit-verified: `discover_nodes` produces
real `Node` instances from real observed packet data, with no ground-truth access, for any capture
already ingested and normalized (Phases 21-22). It is not yet wired into `GET /topology` or any other
route — that remains Phase 32's job, once Phase 30 (edge discovery) also exists and both can be
combined into one `TopologyGraph`. One-IP-per-node and the absence of a persistence artifact are
documented, deliberate scope limits, not gaps.
