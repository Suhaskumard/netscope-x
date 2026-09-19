# NETSCOPE-X — Failure Propagation Graph

Phase 54 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 54 — FAILURE PROPAGATION
GRAPH"): "Represent: Primary failure, Secondary impact, Tertiary impact."

FR-1.28: *"The system shall represent failure propagation as a multi-order impact graph (primary →
secondary → tertiary impact) (spec Phase 54)."* This FR sits in section "1.6 Dependency and causal
reasoning" — not "1.7 Digital twin, simulation, and counterfactuals" (FR-1.31/Phase 57+) — a real
structural signal that this phase belongs alongside Phase 50-53's `backend/dependency/` package,
not a new "simulation" package.

Code: new `backend/dependency/failure_propagation.py` (`propagate_failure`) — the first real use of
`backend/app/models/failure.py`'s `PropagationImpact`/`ImpactOrder` (Phase 04).

## The schema already exists, unused until now

`PropagationImpact` — `scenario_id`, `affected_node_id`, `order: ImpactOrder`
(`PRIMARY`/`SECONDARY`/`TERTIARY`, the master spec's own bullet list verbatim), `caused_by_node_id`
(`None` for primary, required otherwise, schema-enforced by a `model_validator`), `evidence`
(non-empty) — is docstring-tagged *"spec Phase 54, 61"* and has never been constructed anywhere.
`FailureScenario` (the failure-injection *request*) and `POST /simulation` are both explicitly
scoped to *"spec Phase 59-61"* in their own docstrings — later phases. This phase needs only the
simplest possible representation of "what failed": a plain node id, not that later injection
machinery.

## A real design decision: which edges to propagate over, and why

`Edge`/`DependencyEdge.source_node_id`/`target_node_id` are **undirected** — `discover_edges`
assigns them by alphabetically sorting the node-id pair
(`backend/nettrace/topology/edges.py`: *"Edges are undirected... assigned by sorted node_id (a
deterministic tie-break)"*), not by any real dependency direction. Propagating failure along a raw
`DependencyEdge`'s `source -> target` would often mean following a direction with **zero**
supporting evidence (a `temporal_precedence_score` of exactly `0.0`) — an artifact of alphabetical
sorting, not a causal claim.

Phase 53's `CausalCandidate`s are exactly the subset of `DependencyEdge`s where `source -> target`
carries genuine, positive temporal-precedence evidence for that specific direction (Phase 53's own
qualifying rule: sufficient `strength` **and** `temporal_precedence_score > 0.0`). **This phase
propagates over `List[CausalCandidate]`, not raw `List[DependencyEdge]`** — the only edge set in
this codebase where "if source fails, target is impacted" is actually justified by real evidence,
rather than an alphabetical labeling accident. This is the natural, evidence-grounded continuation
of Phase 51 → 52 → 53's own progression.

## Algorithm

`propagate_failure(candidates, scenario_id, failed_node_id)`:

1. **Primary**: one `PropagationImpact` for `failed_node_id` itself, `caused_by_node_id=None` —
   always present, regardless of whether any candidates involve this node.
2. **Secondary/Tertiary**: a breadth-first traversal over `CausalCandidate.source_node_id ->
   target_node_id`, exactly two hops deep — matching the spec's literal three-order list, no further
   cascading (a deeper/configurable cascade is a plausible future enhancement, not attempted here,
   NFR-9). Each node is visited at most once across the whole traversal — a cycle can never loop, and
   a diamond-shaped candidate graph (two paths converging on the same descendant) never double-counts
   a node; the first order/candidate that reaches it wins.
3. Processing order is fully deterministic: frontier nodes are visited sorted by node id, and each
   node's outgoing candidates are sorted by `dependency_id` — so "first reached" is well-defined and
   reproducible, not incidentally dependent on dict/set iteration order.
4. Each secondary/tertiary impact's `evidence` cites the specific `CausalCandidate`'s own
   `strength`/`temporal_precedence_score` (e.g. *"impact propagates from `<node>` via a causal
   candidate (strength=0.850, temporal_precedence=0.720)"*) — concrete, never a bare label, matching
   `PropagationImpact.evidence`'s own non-empty requirement with genuine content.
5. Returns `[PRIMARY only]` for a failed node with no outgoing candidates, or if `candidates` is
   empty — never an error, consistent with this project's "missing means minimal, not an error"
   convention.

No new `Settings` field — the edge set to propagate over is already governed by Phase 53's own
`causal_candidate_strength_threshold`.

## No persistence, no API wiring

`POST /simulation` stays untouched — its own docstring already scopes it to *"spec Phase 59-61"*.
`propagate_failure` is a pure, unpersisted function over caller-supplied `CausalCandidate`s,
mirroring Phase 41/42/45/53's own precedent.

## Worked example

The same 3-hop lagged-activity chain from Phase 52/53's own worked examples, extended one more hop
(A precedes B precedes C, each via a dedicated dummy side-conversation partner, plus minimal direct
A↔B and B↔C exchanges — no direct A↔C traffic at all):

```
Failure at 10.0.0.1:
  order=primary   affected=10.0.0.1   caused_by=None
    evidence: <A> is the primary failure
  order=secondary affected=10.0.0.2   caused_by=10.0.0.1
    evidence: impact propagates from <A> via a causal candidate (strength=1.000, temporal_precedence=0.892)
  order=tertiary  affected=10.0.0.3   caused_by=10.0.0.2
    evidence: impact propagates from <B> via a causal candidate (strength=1.000, temporal_precedence=0.690)
```

C is discovered at `TERTIARY` purely through real propagation via B — there is no direct A↔C edge
at all, confirming the multi-hop traversal is genuine, not a shortcut.

## Verification actually performed this phase

- `pytest backend/tests/test_dependency_failure_propagation.py -v` — **8/8 passed**: a simple chain
  produces exactly primary/secondary/tertiary, with a fourth hop correctly excluded; a node with no
  outgoing candidates produces only the primary impact; a diamond pattern visits the shared
  descendant exactly once, deterministically attributed; a cycle never infinite-loops or revisits an
  already-impacted node; every non-primary impact's evidence references the real candidate values
  that caused it; empty input produces only the primary impact; repeated calls produce identical,
  identically-ordered output; a real end-to-end run through `estimate_dependency_strength` →
  `generate_causal_candidates` (not hand-built `CausalCandidate` fixtures) over a genuine 3-hop
  lagged-activity capture confirms real primary/secondary/tertiary impacts.
- Full repo suite (`pytest backend/tests experiments/tests simulator/tests`, run from repo root) —
  **444/444 passed** (up from 436/436), no regressions.
- `python -m scripts.validate_data_contracts` — 38/38 passed, no regression (`PropagationImpact`/
  `ImpactOrder` unchanged — first real use only).
- `python -m scripts.check_ground_truth_boundary` — clean.
- A real, manual end-to-end run (no Docker needed): built the same 3-hop lagged-activity capture,
  ran the full `estimate_dependency_strength` → `generate_causal_candidates` → `propagate_failure`
  pipeline, and confirmed the printed output exactly matches this doc's worked example.

## Status

The failure propagation graph (spec Phase 54, FR-1.28) is implemented and unit-verified.
`propagate_failure` produces a real, evidenced, three-order impact graph by traversing Phase 53's
already-evidenced `CausalCandidate`s — deliberately not raw, undirected `DependencyEdge`s, a design
decision now explicitly documented. No persistence or API wiring exists yet — both remain natural
jobs for Phase 59-61 (controlled failure injection, the connected simulation pipeline).
