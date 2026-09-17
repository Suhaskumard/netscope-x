# NETSCOPE-X — Algorithm Selection

Phase 05 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 05 — ALGORITHM SELECTION").
Evaluates candidate algorithms for the six required areas — flow reconstruction, role inference,
anomaly detection, graph criticality, path analysis, dependency inference — and documents
alternatives, advantages, limitations, computational complexity, and the selected method for each.
Selections are constrained by the preferred technology stack (spec §6: NetworkX, NumPy, Pandas,
SciPy) and by the project's own principles (spec §7: no overengineering without measurable benefit;
`docs/requirements/system_requirements.md` NFR-9). Where a more sophisticated algorithm exists but its
extra complexity isn't yet justified by a measured need, that is stated explicitly rather than silently
picking the simplest option.

---

## 1. Flow reconstruction

**Problem:** Group normalized packets (spec Phase 22) into bidirectional five-tuple flows with TCP
state tracking (spec Phase 23–24), and model UDP sessions from timing/endpoint heuristics
(spec Phase 25).

**Alternatives considered:**

| Approach | Advantages | Limitations |
|---|---|---|
| **(a) Five-tuple hash table + explicit TCP FSM**, keyed by `(src_ip, src_port, dst_ip, dst_port, protocol)` normalized to a canonical direction | Simple, deterministic, O(1) amortized lookup/update per packet; TCP state machine (SYN→ESTABLISHED→CLOSING→CLOSED/RESET) maps directly to spec Phase 24's required states; easy to unit-test in isolation | Requires an idle-timeout eviction policy for flows that never see FIN/RST (must be tuned, not hardcoded) |
| **(b) Full protocol-stack reassembly** (Zeek/Bro-style deep session reconstruction with TCP segment reordering/reassembly) | Much richer session fidelity; handles retransmission/out-of-order gracefully at the byte level | Substantially higher implementation and computational cost; NETSCOPE-X's observability model (metadata-level, not payload reassembly per spec §3 — problem_definition.md §3) doesn't require byte-level reassembly, so this cost isn't justified |
| **(c) NetFlow/IPFIX-style statistical aggregation** (fixed time-bucket flow summarization without explicit state tracking) | Very low memory footprint; standard in commercial NetFlow exporters | Loses TCP state detail required by FR-1.4 (SYN/ACK/FIN/RST/retransmission tracking) and connection-level granularity needed for role/behavior inference |

**Selected: (a) Five-tuple hash table with explicit TCP finite-state machine**, plus timing-window-
based UDP session grouping (spec Phase 25) using a configurable idle-timeout (not hardcoded — ties to
NFR-4).

**Complexity:** O(1) amortized per packet for hash lookup/update; O(F) memory for F concurrent flows.
State-machine transitions are O(1) per packet. Idle-timeout sweep is O(F) per sweep interval,
amortized against packet volume.

**Failure cases / limitations:** Cannot distinguish two flows that legitimately reuse the same 5-tuple
in rapid succession without a sufficient idle gap (NAT/port-reuse ambiguity — noted as a known
limitation, ties to spec §32 "NAT scenarios," "IP reuse" test requirement); partial flows (missing
handshake or teardown) are explicitly representable via `TCPState.PARTIAL` rather than forced into an
incorrect state.

---

## 2. Role inference

**Problem:** Infer a probability distribution over service roles (Client, Gateway, API, Database,
Cache, DNS, Worker, Load Balancer, Unknown) per node from its behavioral fingerprint (spec Phase 36–37;
RQ2).

**Alternatives considered:**

| Approach | Advantages | Limitations |
|---|---|---|
| **(a) Rule-based port/protocol heuristics** (e.g., port 5432 → Database) | Trivial to implement and explain | This is exactly the "hardcoded service classification" the spec forbids (§3) when used as the *only* signal, and fails for non-standard ports or multiplexed services |
| **(b) Naive-Bayes-style probabilistic classifier** over engineered behavioral features (port set entropy, protocol mix, traffic directionality, persistence, destination diversity), producing a calibrated posterior via Bayes' rule | Naturally produces the `Dict[ServiceRole, float]` output `RoleClassification` requires (spec Phase 37); interpretable — each feature's contribution to the posterior can be reported as evidence; computationally cheap; degrades gracefully (uncertain posterior) rather than crashing under low observability | Requires class-conditional feature likelihoods, which must be learned from a labeled training split of lab-generated data (never from the ground truth of the experiment being evaluated — ties to §4/REPRO-4) |
| **(c) Supervised ML (Random Forest / gradient boosting)** on the same feature set | Can capture non-linear feature interactions Naive Bayes misses; typically higher raw accuracy | Requires materially more labeled training data than the controlled lab topologies will initially produce; harder to explain per-prediction (feature importances are global, not naturally a calibrated per-class posterior); overkill relative to NFR-9 until Naive Bayes is shown to be a measured bottleneck |
| **(d) Unsupervised clustering (k-means/GMM) with post-hoc role labeling** | No labeled data required upfront | Cluster-to-role mapping still needs *some* ground truth to assign labels, and unsupervised clusters don't naturally yield a calibrated per-role confidence distribution — would require an extra calibration step, effectively re-deriving (b) |

**Selected: (b) Naive-Bayes-style probabilistic classifier** over behavioral features, trained on a
held-out labeled split of lab-generated data (topology/role ground truth used only for training and
evaluation splits, never for the pipeline's live inference — per §4/REPRO-4), producing a calibrated
posterior distribution directly compatible with the `RoleClassification` schema (Phase 04). Escalation
to (c) is deferred until Naive Bayes' measured accuracy (Phase 68) is shown insufficient — that
decision will be revisited with evidence, not assumed now.

**Complexity:** O(n·k) per node for n = feature count, k = candidate roles, both small constants;
negligible relative to flow reconstruction cost. Training (fitting class-conditional likelihoods) is
O(N·n) for N labeled training examples, done offline/periodically, not per-inference.

**Failure cases / limitations:** Naive Bayes assumes conditional feature independence given the role,
which is only approximately true (e.g., port diversity and protocol mix are correlated); this is a
known, accepted simplification, not hidden.

---

## 3. Anomaly detection

**Problem:** Detect multi-dimensional deviations (traffic volume, destinations, ports, protocols,
timing, topology, behavior — spec Phase 40) with mandatory per-anomaly evidence (spec Phase 41) and a
distinction between transient anomaly and concept drift (spec Phase 39; RQ3/RQ4).

**Alternatives considered:**

| Approach | Advantages | Limitations |
|---|---|---|
| **(a) Per-dimension statistical baseline** (robust z-score / MAD-based deviation against a rolling historical baseline per node/feature) + explicit set-difference novelty checks (new destination/port not in historical set) | Directly produces the exact evidence format spec Phase 41 requires ("historical destinations: 4, current destinations: 9") because the evidence *is* the statistic computed; cheap, streaming-friendly (rolling mean/MAD, O(1) update per observation); easy to reason about false-positive rate via a tunable z-score threshold | Purely univariate per dimension by default — correlated multi-dimensional anomalies need to be aggregated across dimensions explicitly, not discovered automatically |
| **(b) Unsupervised outlier detection (Isolation Forest / One-Class SVM)** over the full feature vector | Can capture multivariate anomalies a per-dimension approach misses | Much harder to produce human-readable, evidence-based explanations (spec Phase 41) from a tree-ensemble anomaly score; heavier compute; overkill relative to NFR-9 without a measured need |
| **(c) Autoencoder-based reconstruction error** | Can model complex non-linear "normal" manifolds | Requires substantial training data and compute NETSCOPE-X's controlled-lab scale doesn't justify; reconstruction error is not naturally explainable per spec Phase 41's evidence requirement; explicitly the kind of "generic ML anomaly detector" the spec's §35 "What Not To Do" warns against as the *sole* mechanism |

**Selected: (a) Per-dimension statistical baseline with explicit set-difference novelty detection**,
using a robust (median/MAD-based, outlier-resistant) rather than mean/std baseline to avoid the
baseline itself being skewed by prior anomalies. Concept drift (spec Phase 39) is distinguished from a
transient anomaly by tracking whether the deviation persists and the baseline itself should shift
(implemented as an EWMA-updated baseline with a slower update rate than the anomaly-detection window —
a sustained deviation that the EWMA baseline eventually absorbs is classified `concept_drift`; a
deviation that reverts before the baseline shifts is `transient_anomaly`).

**Complexity:** O(1) amortized per observation per monitored dimension (rolling statistic update);
O(D) per node per window for D monitored dimensions — linear, not combinatorial.

**Failure cases / limitations:** Requires a minimum baseline observation period before deviations are
meaningful (cold-start limitation — an anomaly detector has no baseline to compare against for a
newly observed node); will be less sensitive to subtle multivariate anomalies that don't show up
strongly in any single dimension — noted as a known limitation rather than addressed by escalating to
(b)/(c) without measured justification.

---

## 4. Graph criticality

**Problem:** Compute degree, betweenness, articulation points, path dependency, and connectivity
(spec Phase 55) to identify structurally critical components.

**Alternatives considered:**

| Approach | Advantages | Limitations |
|---|---|---|
| **(a) Exact classical graph algorithms via NetworkX**: degree centrality (O(V+E)), Brandes' betweenness centrality (O(VE) unweighted / O(VE + V²log V) weighted), Tarjan's articulation-points algorithm (O(V+E)) | Exact, well-understood, directly available in the pinned NetworkX dependency (spec §6) — no need to hand-roll graph algorithms; laboratory topologies (spec Phase 11/18: small/medium/large/multi-path/multi-service/dynamic) are small enough that exact computation is cheap | Exact betweenness is O(VE), which becomes expensive on very large graphs (thousands+ of nodes) — not a concern at controlled-lab scale, but noted for the performance-requirements phase (PERF-3) to actually measure, not assume |
| **(b) Approximate betweenness centrality** (sampling-based, e.g., Brandes-Pich approximation) | Sub-linear-in-samples runtime, scales to very large graphs | Introduces approximation error that would need its own confidence reporting — unjustified complexity at the lab's scale (NFR-9); would only be revisited if PERF-3 benchmarking on Phase 68's "large" topology category shows exact computation is a bottleneck |
| **(c) PageRank / eigenvector centrality** as an additional/alternative importance signal | Captures a different notion of "importance" (recursive influence rather than shortest-path betweenness) | Not what spec Phase 55 explicitly asks for (degree, betweenness, articulation points, path dependency, connectivity); could be added later as a supplementary signal but isn't required for this phase |

**Selected: (a) Exact NetworkX implementations** of degree centrality, Brandes' betweenness centrality,
and Tarjan's articulation-points algorithm, combined with connectivity/path-dependency analysis built
on the same graph. Documented rationale per metric (per spec Phase 55's explicit requirement to
document why each metric is relevant):
- **Degree** — cheap first-pass signal for "how many direct relationships does this node have."
- **Betweenness** — identifies nodes that lie on many shortest communication paths, i.e., likely
  routing/proxy chokepoints (Gateway, Load Balancer roles are expected to score highly here).
- **Articulation points** — identifies nodes whose removal would disconnect the graph, i.e.,
  structural single points of failure — directly feeds failure-injection experiment suggestions
  (spec Phase 67).
- **Path dependency / connectivity** — measures how much alternate-path availability exists, i.e., how
  much redundancy protects against a given node's failure (ties to RQ6, resilience quantification).

**Complexity:** As listed in the table above (NetworkX's standard implementations); to be actually
measured per PERF-3 once a real graph exists, not assumed.

**Failure cases / limitations:** Betweenness/articulation-point analysis on a topology whose edges
carry only probabilistic confidence (not certainty) means criticality scores inherit that uncertainty —
a low-confidence edge contributing to a node's high betweenness score should be flagged as
lower-confidence criticality, not reported with false precision (an open design question to resolve
when this is implemented, recorded here rather than glossed over).

---

## 5. Path analysis

**Problem:** Compute shortest paths, alternate paths, path costs, route changes, and disconnected
components under a (possibly failure-modified) graph (spec Phase 60).

**Alternatives considered:**

| Approach | Advantages | Limitations |
|---|---|---|
| **(a) Dijkstra's algorithm** for weighted shortest path (weight derived from edge confidence/latency), **Yen's algorithm** for k-shortest (alternate) paths, **BFS/union-find** for connected-component analysis after simulated failures | All three are standard, available via NetworkX, well-suited to the graph sizes involved; Yen's algorithm directly produces the "alternate paths" spec Phase 60 requires, ranked by cost, which feeds resilience quantification (spec Phase 62) | Yen's algorithm is O(K·V·(E + V log V)) for K alternate paths — grows with K; K will be kept small (e.g., top 3–5 alternates) since the use case is "is there a viable alternate route," not exhaustive path enumeration |
| **(b) All-pairs shortest path (Floyd–Warshall)** | Precomputes every pair at once, useful if many path queries are needed simultaneously | O(V³) — unnecessary cost when only a small number of source/target pairs are queried per simulation/counterfactual request, which is the actual access pattern here |
| **(c) A\* search** with a domain-specific heuristic | Can outperform Dijkstra when a good heuristic exists | No natural admissible heuristic exists for "network path cost" in this domain without additional assumptions (e.g., geographic distance, which doesn't apply to a logical service graph) — not adopted |

**Selected: (a) Dijkstra for weighted shortest path, Yen's algorithm (bounded K) for alternate paths,
BFS/union-find for connectivity and disconnected-component detection** after a simulated failure
(spec Phase 59–61) or counterfactual mutation (spec Phase 64–65) is applied to an isolated graph copy.

**Complexity:** Dijkstra O((V+E) log V); Yen's O(K·V·(E + V log V)) for bounded K; BFS/union-find
O(V+E) per connectivity check.

**Failure cases / limitations:** Edge weights derived from confidence/latency estimates are themselves
uncertain (same caveat as graph criticality above); path costs computed on a low-confidence edge should
be reported with that caveat rather than as a precise number.

---

## 6. Dependency inference

**Problem:** Distinguish "A communicates with B" from "A depends on B" (spec Phase 50; RQ5), and
generate causal candidates without equating correlation with causation (spec Phase 53).

**Alternatives considered:**

| Approach | Advantages | Limitations |
|---|---|---|
| **(a) Weighted multi-signal scoring function** combining frequency, persistence, directionality, and time-lagged cross-correlation (temporal precedence — spec Phase 52), thresholded to produce a `DependencyEdge.strength` score | Directly matches the `DependencyEdge` schema (Phase 04) fields; each signal is independently interpretable and reportable as evidence in a `CausalEvidenceReport` (spec Phase 56); computationally cheap; avoids overclaiming causation by design — the output is explicitly a "strength/confidence" score, never a boolean "causes" assertion | A heuristic weighting of signals requires some empirical tuning (e.g., relative weight of frequency vs. temporal precedence) — this tuning will itself need Phase 68 evaluation against ground-truth dependency edges to validate, not be assumed correct at design time |
| **(b) Granger causality testing** on time-series of node activity | A statistically grounded, well-established technique for "does A's past predict B's future beyond B's own past" | Requires stationarity assumptions on the underlying traffic time series that lab traffic (bursty, event-driven) will often violate; more complex to implement and explain per-edge than the multi-signal score; considered a candidate future enhancement once (a) is measured and its limitations are concretely identified via Phase 68, not adopted now without that evidence (ties to NFR-9) |
| **(c) Constraint-based causal discovery (PC algorithm / similar)** over the full node-activity dataset | Can, in principle, recover a causal DAG structure rather than pairwise scores | Substantially higher implementation complexity and stronger statistical assumptions (e.g., causal sufficiency, faithfulness) that are hard to justify or verify in this domain; explicitly out of scope for the current phase — the spec's own Phase 53 wording ("generate candidate causal relationships," "do not equate correlation with causation") is satisfied by a scored-candidate approach without requiring full causal-graph discovery |

**Selected: (a) Weighted multi-signal scoring function** (frequency + persistence + directionality +
time-lagged cross-correlation for temporal precedence), producing the `DependencyEdge.strength` and
`temporal_precedence_score` fields already defined in Phase 04's data contracts, and always
accompanied by a `CausalEvidenceReport` with explicit `limitations` (schema-enforced non-empty, per
Phase 04) — structurally preventing an unqualified causal claim. Escalation to (b)/(c) is an explicit,
documented future option, not silently deferred.

**Complexity:** O(T) per node pair for T time-bucketed observations (cross-correlation at a bounded
set of lag offsets), i.e., linear in observation volume per candidate pair; candidate pairs are
pruned first by the (already-inferred) topology edges, so this is not run on all O(V²) node pairs.

**Failure cases / limitations:** Multi-signal scoring can still misclassify a high-frequency,
persistent, one-directional *but coincidental* communication pattern as a dependency (e.g., a health-
check poller); this is the expected, measured failure mode that RQ5's evaluation (Phase 68) is
designed to quantify (precision/recall against ground-truth dependency edges), not eliminate by
construction.

---

## Cross-cutting note on validation

None of the algorithms selected above have been implemented or benchmarked yet — that begins with
Phase 06 (reproducible dev environment) and the pipeline-implementation phases (21+). Per spec §21 ("No
Fake Metrics") and Rule 2, no complexity or accuracy claim above should be read as a measured result;
all Big-O figures are analytical (standard, well-known complexities of standard algorithms), not
empirical, and all accuracy/precision claims are deferred to Phase 68 execution.

## Status

This document satisfies Phase 05: all six required algorithm areas (flow reconstruction, role
inference, anomaly detection, graph criticality, path analysis, dependency inference) are covered,
each with alternatives, advantages, limitations, computational complexity, and a selected method.
