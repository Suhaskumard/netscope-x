# NETSCOPE-X — Research Questions and Hypotheses

Phase 02 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 02 — RESEARCH QUESTIONS AND
HYPOTHESES"). Builds directly on `docs/research/problem_definition.md` (Phase 01), particularly its
observability model (§3) and success-criteria table (§8). Each question below defines a hypothesis,
its variables, the evaluation metric(s) used to test it, and the experiment design that will produce
evidence — no question is answered here; answering them is the job of later phases (Phase 32 for RQ1,
Phase 42 for RQ3, Phase 68 for the full matrix, etc.).

This document covers the seven areas the spec requires: topology reconstruction, behavioral
inference, anomaly detection, temporal change detection, dependency inference, failure propagation,
and counterfactual simulation.

---

## RQ1 — Topology reconstruction

**Question:** How accurately can NETSCOPE-X reconstruct the true node/edge topology of a controlled
network purely from observed traffic, without access to ground truth at inference time, and how does
that accuracy degrade as observation completeness decreases?

**Hypothesis (H1):** Node and edge precision/recall will exceed a usable threshold (to be
empirically established, not assumed — see Phase 32/68) at 100% observability, and will degrade
monotonically as observation completeness drops (100% → 90% → 75% → 50% → 25%, per spec Phase 68),
with edge recall degrading faster than node recall because rare/low-frequency edges are the first to
disappear under partial capture.

**Variables:**
- Independent: observation completeness (%), topology complexity (small / medium / large / multi-path
  / multi-service / dynamic — Phase 18 scenario set), capture vantage point(s).
- Dependent: node precision, node recall, edge precision, edge recall, F1, overall graph similarity
  score (Phase 32).

**Evaluation metric:** Node precision/recall, edge precision/recall, F1, and a graph-similarity metric
comparing the inferred graph to the versioned, hashed ground truth (Phase 17), computed automatically
by the Validation Engine — never asserted by hand.

**Experiment design:** For each topology archetype (Phase 18) and each observation-completeness level
(Phase 68), run the full capture → NETTRACE → topology-inference pipeline against replayed,
deterministic traffic (Phase 19), then diff the inferred graph against ground truth (Phase 45's
graph-difference machinery reused for evaluation). Repeat across multiple traffic-generation seeds to
report variance, not a single point estimate.

---

## RQ2 — Behavioral inference (role classification)

**Question:** How accurately can NETSCOPE-X infer the functional role of a node (Client, Gateway,
API, Database, Cache, DNS, Worker, Load Balancer, Unknown) from its behavioral fingerprint alone, and
is its confidence calibrated — i.e., does a node classified "Database: 72%" actually turn out to be a
database roughly 72% of the time across many such classifications?

**Hypothesis (H2):** Role-classification accuracy will be high for roles with structurally distinct
traffic signatures (e.g., DNS, Database) and lower for roles that resemble each other behaviorally
(e.g., generic API vs. Worker), and the system's stated confidence will be reasonably calibrated
(calibration error below a threshold established empirically in Phase 37/68) rather than systematically
over- or under-confident.

**Variables:**
- Independent: node's true role (ground truth), traffic mix/protocol diversity, observation window
  length (short/medium/long — Phase 34).
- Dependent: classification accuracy, precision, recall, F1 per role, calibration error (predicted
  confidence vs. observed frequency of correctness).

**Evaluation metric:** Per-role accuracy/precision/recall/F1, confusion matrix across roles, and a
calibration curve/metric (e.g., expected calibration error) — all computed from Phase 36/37 output
against ground-truth role labels (Phase 16), never hand-assigned.

**Experiment design:** Run role inference against each generated topology/dataset, holding out
ground-truth role labels from the classifier and only revealing them to the Validation Engine for
scoring. Compare classification behavior across the three behavioral-window sizes to see whether
longer observation windows improve accuracy and calibration.

---

## RQ3 — Anomaly detection

**Question:** How effectively can NETSCOPE-X detect genuine behavioral deviations (new destinations,
new ports, volume/timing/protocol/topology shifts) while keeping the false-positive rate low enough
to be usable, and how quickly are true anomalies detected after they start?

**Hypothesis (H3):** Detection precision/recall will trade off against the anomaly-sensitivity
threshold; there exists an operating point where F1 is maximized, and detection latency (time from
anomaly onset to flagged anomaly) will be materially shorter for large, abrupt deviations than for
gradual concept drift (which RQ3 must distinguish from genuine anomalies — spec Phase 39).

**Variables:**
- Independent: anomaly type (volume, destination, port, protocol, timing, topology, behavior —
  Phase 40), anomaly magnitude, background traffic noise level (dataset_noisy), detection-sensitivity
  configuration.
- Dependent: precision, recall, F1, false-positive rate, false-negative rate, detection latency
  (Phase 42).

**Evaluation metric:** Precision/recall/F1/false-positive-rate/false-negative-rate/detection-latency,
computed against `dataset_anomaly` and `dataset_noisy` (Phase 19-generated, with injected known
anomalies whose onset time and type are recorded as ground truth), never inferred informally.

**Experiment design:** Inject controlled, timestamped anomalies of each type from Phase 40's list into
replayed traffic, run FLOWMIND's anomaly detector, and score detections against the injected-anomaly
log. Additionally run the detector against `dataset_incomplete`/`dataset_noisy` to test robustness
under degraded observability, and require every reported anomaly to carry evidence (Phase 41) rather
than a bare label.

---

## RQ4 — Temporal change detection

**Question:** How accurately and how quickly can NETSCOPE-X detect real changes to network topology
and node behavior over time, and can it distinguish a temporary anomaly from a persistent behavioral
evolution (concept drift)?

**Hypothesis (H4):** Structural changes (node/edge additions or removals) will be detected with high
precision/recall because they are discrete, evidenced events (Phase 45's graph-diff engine), while
gradual behavioral drift will be harder to separate cleanly from anomaly detection (RQ3) and will
require a longer observation window to classify correctly as "evolution" rather than "anomaly."

**Variables:**
- Independent: change type (node/edge addition/removal, attribute change, gradual behavioral drift),
  change magnitude, time between snapshots.
- Dependent: change precision, change recall, detection latency (Phase 42/68's temporal-analysis
  metrics).

**Evaluation metric:** Change precision/recall and detection latency, scored against a ground-truth
topology-event timeline (Phase 16/47) generated alongside the controlled experiment.

**Experiment design:** Script a sequence of controlled topology/behavior changes in the laboratory
(e.g., add a service, remove a route, gradually shift a node's traffic pattern), capture continuously,
and compare NETSCOPE-X's detected event timeline (Phase 47) against the scripted ground-truth event
log, including whether each event was correctly attributed to evidence (Phase 48) without overclaiming
causation.

---

## RQ5 — Dependency inference

**Question:** Given that observed communication between two nodes does not by itself imply dependency
(spec Phase 50), how accurately can NETSCOPE-X distinguish true dependencies from incidental
communication, and how well does its estimated dependency strength correlate with actual operational
dependency?

**Hypothesis (H5):** Dependencies with high frequency, persistence, consistent directionality, and
consistent temporal precedence (Phase 51/52) will be correctly identified as dependencies with high
precision, while low-frequency or bidirectional/exploratory communication will correctly receive low
dependency-strength scores; some false positives are expected for communication patterns that mimic
dependency signatures without being one, and this must be measured, not hidden.

**Variables:**
- Independent: true dependency relationships (ground truth: e.g., API-1 → Redis), communication
  frequency/persistence/directionality, presence of confounding "chatty but independent" traffic.
- Dependent: dependency precision, dependency recall, impact-prediction accuracy, propagation accuracy
  (Phase 68's causal-analysis metrics).

**Evaluation metric:** Dependency precision/recall against the ground-truth dependency graph (which
must never leak into the inference pipeline per spec §4), plus downstream impact-prediction and
propagation accuracy once failures are simulated (ties to RQ6).

**Experiment design:** Use topologies with known dependency edges (Phase 16 ground truth) and
deliberately include non-dependency "noise" communication between unrelated services. Run causal
candidate generation (Phase 53) and dependency-strength estimation (Phase 51), then score against
ground truth. Every accepted dependency claim must carry the causal evidence report format (Phase 56):
relationship, evidence, confidence, counter-evidence, limitations.

---

## RQ6 — Failure propagation

**Question:** How accurately can NETSCOPE-X's digital twin predict how a real controlled failure will
propagate through the network (which components are affected, how connectivity/paths/latency change),
compared to what actually happens when that failure is executed for real?

**Hypothesis (H6):** Propagation predictions will be most accurate for direct, first-order impacts
(the immediately dependent node) and will lose accuracy for higher-order (secondary/tertiary) impacts,
because those depend on compounding uncertainty in the dependency graph (RQ5) and on the dynamic-path
engine's (Phase 60) modeling of rerouting behavior, which may not perfectly match real infrastructure
behavior.

**Variables:**
- Independent: failure type (node failure, edge failure, latency injection, packet loss, bandwidth
  reduction, service degradation — Phase 59), point of injection, network resilience characteristics
  (redundancy, alternate paths).
- Dependent: path-prediction accuracy, affected-node-prediction accuracy, connectivity-prediction
  accuracy, resilience-indicator accuracy (connectivity, reachable-node ratio, affected services, path
  degradation, bottleneck emergence, alternative-path availability — Phase 62).

**Evaluation metric:** Prediction-vs-actual comparison (Phase 63/68's PathForge metrics): path
prediction, affected-node prediction, connectivity prediction — each measured by running the *actual*
controlled failure in the lab and diffing real observed impact against the digital twin's prediction
made *before* the real failure was executed.

**Experiment design:** For each candidate critical component identified by criticality analysis
(Phase 55: degree, betweenness, articulation points), (1) record the twin's predicted propagation
before touching the real network, (2) execute the real failure in the isolated lab, (3) capture the
actual impact, (4) score prediction against reality. This is the core of the Digital Twin Validation
phase (Phase 63) and must never be skipped or approximated.

---

## RQ7 — Counterfactual simulation

**Question:** How well do NETSCOPE-X's counterfactual predictions ("what if we removed this node /
added this route / increased this latency") match what a real controlled experiment shows when that
same hypothetical change is actually made in the lab?

**Hypothesis (H7):** Counterfactuals that closely resemble scenarios already covered by RQ6's failure
types (e.g., REMOVE node) will show similar accuracy to RQ6; counterfactuals with no direct real-world
analogue tested yet (e.g., ADD route, INCREASE traffic) will need their own controlled validation and
may show larger prediction-vs-actual gaps, which the ablation studies (Phase 68/69) will help attribute
to specific missing model components (temporal features, behavioral features, dependency weighting,
confidence modeling).

**Variables:**
- Independent: counterfactual scenario type (REMOVE node/edge, INCREASE latency, REDUCE bandwidth,
  INCREASE traffic, ADD route — Phase 64), baseline network state at time of query.
- Dependent: predicted-vs-actual match on paths, connectivity, latency, affected services,
  bottlenecks, propagation (Phase 66).

**Evaluation metric:** Same structural comparison as RQ6 (predicted outcome vs. actual controlled
experiment), applied specifically to counterfactual scenarios rather than only real injected failures,
plus the four minimum ablation comparisons the spec requires (full system vs. without temporal
features / without behavioral features / without dependency weighting / without confidence modeling)
to isolate which model components drive counterfactual accuracy.

**Experiment design:** Generate a counterfactual scenario using the scenario language (Phase 64),
compute its predicted impact on an isolated alternate graph state that never mutates the real baseline
(Phase 65), then — where physically realizable in the lab — actually execute the equivalent real
change and compare. Where a counterfactual is not realizable in the lab (e.g., purely hypothetical
route that doesn't exist), report the prediction as unvalidated rather than implying it was tested.

---

## Cross-cutting requirement

Every research question above inherits the constraints from Phase 01 (`problem_definition.md` §6,
Research Boundaries): no fabricated metrics, no ground-truth leakage into inference, and every
reported number must come from an actual executed experiment against real (or realistically
simulated/replayed) traffic in the controlled laboratory. Where an experiment cannot yet be run
because the underlying pipeline stage doesn't exist yet (true for all seven RQs as of this phase),
that is recorded as a limitation, not answered with a placeholder result.

## Status

This document satisfies Phase 02 of the 69-phase execution plan. It is documentation-only — no code
or experiments exist yet to produce results for any RQ; each RQ explicitly defers its answer to the
phase where the relevant pipeline component and validation engine exist (RQ1→Phase 32/68, RQ2→Phase
36/37/68, RQ3→Phase 40-42/68, RQ4→Phase 43-49/68, RQ5→Phase 50-56/68, RQ6→Phase 57-63/68,
RQ7→Phase 64-68). Verification for this phase consists of confirming all seven required research areas
are covered, each with hypothesis, variables, evaluation metric, and experiment design — which they
are, above.
