# NETSCOPE-X — Criticality Analysis

Phase 55 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 55 — CRITICALITY ANALYSIS"):
"Analyze: degree, betweenness, articulation points, path dependency, connectivity. Document why
each metric is relevant."

FR-1.29: *"The system shall compute graph criticality metrics (degree, betweenness, articulation
points, path dependency, connectivity) with documented rationale for each metric's relevance (spec
Phase 55)."*

Code: new `backend/dependency/criticality.py` (`compute_graph_criticality`, `NodeCriticality`,
`GraphCriticalityReport`, `METRIC_RATIONALE`).

## The algorithm and rationale were already committed at Phase 05

`docs/architecture/algorithm_selection.md` §4 selected *"Exact NetworkX implementations"* — degree
centrality, Brandes' betweenness centrality, Tarjan's articulation-points algorithm — and already
wrote the required "why each metric is relevant" documentation. This phase implements that
already-decided design; `METRIC_RATIONALE` carries that documentation as a real, in-code artifact
(adapted directly from §4's own text), satisfying FR-1.29's "documented rationale" requirement
literally, not only in prose in this doc.

## Which graph, and why

§4's own confidence caveat references `Edge.confidence` specifically — a `TopologyGraph`/`Edge`
(Phase 30-32) field, not anything `DependencyEdge` (Phase 50-54, which has `strength`, no raw
`confidence`) carries. Combined with §4's own rationale — betweenness as *"routing/proxy chokepoints
(Gateway, Load Balancer roles expected to score highly)"* and articulation points as *"structural
single points of failure"* — these describe the full inferred **communication** topology, not the
narrower, sparser dependency/causal-candidate graph. This phase operates on `TopologyGraph`,
confirmed by the algorithm-selection text itself.

## Where the code lives

`backend/dependency/__init__.py`'s own docstring (Phase 50) already named this: *"dependency-strength
estimation, temporal precedence, failure-propagation, **criticality metrics**, and causal evidence
reporting are later phases' additions here."* Confirmed directly, not assumed.

## Resolving the flagged open question

§4 explicitly flagged: *"a low-confidence edge contributing to a node's high betweenness score
should be flagged as lower-confidence criticality, not reported with false precision (an open
design question to resolve when this is implemented)."*

Resolved via `mean_incident_edge_confidence`: rather than weighting the betweenness/degree
computation itself by confidence — which would require inventing an unjustified distance/weight
transform the spec never asks for, and would silently distort the exact graph-theoretic numbers
§4 selected — each node's score is paired with the real, honest mean confidence of its own incident
edges. A consumer can see *"this node's high betweenness score rests on evidence with mean
confidence 0.42"* without the underlying centrality numbers being blended with an ad hoc weighting
scheme. `None` (never fabricated as `0.0`) for a node with no incident edges.

## `path_dependency_impact`: a graded refinement of the articulation-point flag

The binary "is it a cut vertex" flag alone doesn't distinguish a node whose removal strands one
other node from one that strands twenty. `path_dependency_impact` is a real, well-defined
graph-theoretic quantity: `(total other nodes) - (size of the largest connected component after
removing this node)` — how many *other* nodes end up stranded outside the main remaining component.
`0` for any non-critical node (equivalent to "not an articulation point"); a real, graded number for
a true structural bottleneck. This directly answers "path dependency" (how much do other nodes'
paths depend on this one existing) more precisely than the boolean flag alone, and ties to RQ6's
resilience quantification exactly as §4's rationale text anticipated.

## No combined/ranked score

The five named metrics are reported separately, exactly as the spec asks ("compute... metrics," not
"rank nodes"). Inventing a weighted combination formula without empirical justification is exactly
the kind of unjustified-weighting choice this project avoids elsewhere (Phase 31/51's uniform, not
hand-tuned, signal-strength constants) — left to a consumer, or a future phase with real calibration
evidence (Phase 68).

## No persistence, no API wiring

No `/criticality` route exists among Phase 09's 12 fixed endpoint groups at all.
`compute_graph_criticality` is a pure, unpersisted function over an already-assembled
`TopologyGraph`, mirroring Phase 41/42/45/53/54's own precedent.

## Worked example

A 5-node chain (A2–A1–Hub–B1–B2), where Hub is the sole connection between two otherwise-independent
clusters:

```
node_connectivity=1 connected_components=1

Hub  degree=0.500 betweenness=0.667 articulation=True  path_dep_impact=2 mean_conf=0.367
A1   degree=0.500 betweenness=0.500 articulation=True  path_dep_impact=1 mean_conf=0.462
B1   degree=0.500 betweenness=0.500 articulation=True  path_dep_impact=1 mean_conf=0.367
A2   degree=0.250 betweenness=0.000 articulation=False path_dep_impact=0 mean_conf=0.557
B2   degree=0.250 betweenness=0.000 articulation=False path_dep_impact=0 mean_conf=0.367
```

Hub correctly has both the highest betweenness (every A↔B path crosses it) and the highest
`path_dependency_impact` (removing it strands two nodes, the most of any node in this topology) —
`node_connectivity=1` correctly reflects that the whole graph can be disconnected by removing just
one node (any of the three articulation points).

## Verification actually performed this phase

- `pytest backend/tests/test_dependency_criticality.py -v` — **10/10 passed**: a star topology's hub
  has maximal degree/betweenness, is a genuine articulation point, and its `path_dependency_impact`
  matches a hand-computed value; a linear chain's two interior nodes are articulation points with
  correct, distinct impact values, the endpoints are not; a 4-cycle has zero articulation points and
  zero impact everywhere (full redundancy recognized) with `node_connectivity=2`; an isolated node
  scores all zeros/`None` correctly; `mean_incident_edge_confidence` matches a hand-computed mean;
  `node_connectivity` correctly reflects chain (1) vs. cycle (2) vs. disconnected (0) topologies; an
  empty graph returns an empty report, never an error; `METRIC_RATIONALE` documents every reported
  metric; identical repeated calls produce identical output; a real end-to-end run through
  `build_topology_graph` (not hand-built `TopologyGraph` fixtures) over a real hub-and-spoke capture
  confirms the gateway node is discovered as a genuine articulation point from real pipeline output.
- Full repo suite (`pytest backend/tests experiments/tests simulator/tests`, run from repo root) —
  **454/454 passed** (up from 444/444), no regressions.
- `python -m scripts.validate_data_contracts` — 38/38 passed, no regression (no schema changes this
  phase).
- `python -m scripts.check_ground_truth_boundary` — clean.
- A real, manual end-to-end run (no Docker needed): built a real 5-node hub-and-spoke capture, ran
  `build_topology_graph` then `compute_graph_criticality`, and confirmed the printed output exactly
  matches this doc's worked example.

## Status

Criticality analysis (spec Phase 55, FR-1.29) is implemented and unit-verified, using the exact
algorithm and rationale already committed at Phase 05. The confidence caveat §4 flagged as an open
question is now resolved via `mean_incident_edge_confidence`, reported alongside — not blended
into — the exact, unweighted centrality scores. No persistence or API wiring exists yet.
