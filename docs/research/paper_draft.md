# NETSCOPE-X: Reconstructing, Explaining and Stress-Testing a Network's Behaviour from Observed Traffic — Methods, Results and Limitations (Draft)

*Draft. Every number below is quoted from a measurement this project actually ran; each is tied to a ledger entry `[C<n>]` in `docs/research/paper_claims.json` and verified by `python -m scripts.check_paper_claims`. All evaluation is on a synthetic, controlled network laboratory. Where a hypothesis was not supported, this paper says so.*

## Abstract

NETSCOPE-X infers a network's topology, node roles, anomalies, dependencies, failure propagation and counterfactual outcomes from packet captures, and is scored against a versioned ground truth that inference code is never allowed to read. This draft reports what the measurements support and what they do not: topology and temporal reconstruction are perfect on the default synthetic traffic but degrade with sparse observation; held-out role inference and causal dependency discovery are weak; anomaly detection has high recall and low precision; and no evaluation on real-world traces has been run.

## 1. Introduction

The research questions RQ1-RQ7 (`docs/research/research_questions.md`) ask how well the system can recover topology, roles, anomalies, temporal change, dependencies, failure propagation and counterfactual effects without ground truth at inference time. This draft answers each with the results produced in Phases 01-106, including the results that contradict the original hypotheses.

## 2. Methods

**Ground-truth boundary.** A static check (`scripts.check_ground_truth_boundary`) fails if inference code imports the ground-truth generator; ground truth is used only to score.

**Laboratory and traffic.** Six synthetic topology archetypes are generated with seeded traffic; the seed varies traffic generation and observation sampling while the topologies stay fixed. Observation completeness is varied by sampling each packet independently.

**Experimental matrix.** Each cell runs the real pipeline and a scorer per research question, with ablations and multiple seeds; repeated runs are versioned rather than overwritten.

**Statistics.** Effects are compared with paired tests, bootstrap confidence intervals, minimum detectable difference and Holm correction; results that are all-zero differences are reported as identical, not as significant.

**Evaluation discipline.** Where an early result was later found to be wrong (an in-sample role score, a single favourable seed, a scoring bug), the corrected number replaces it and the correction is reported below.

## 3. Results

### RQ1 — Topology reconstruction

Hypothesis H1 (accurate at full observability, degrading as completeness falls) is supported only when observation is sparse. On the default traffic, topology reconstruction and temporal F1 were perfect across all seeds and completeness levels [C1]. That flatness is an artifact of packet volume: each declared edge carries so many packets that sampling almost never removes one. Under a low-volume sweep, topology F1 falls at every completeness level, for example on the large topology [C2]. A learned graph-network edge model did not beat the heuristic and was rejected [C3]. Incremental reconstruction reproduced batch results exactly [C5], and fusing several collectors reproduced the single full capture exactly [C4].

### RQ2 — Behavioural role inference

The in-sample scores first reported materially overstated quality. Under leave-one-node-out evaluation, held-out accuracy is low and varies strongly by topology [C6]. Across seeds the noisiest case showed that the earlier single-seed value had been a favourable one [C7]. Zero-shot transfer to unseen topology archetypes collapses on most of them [C8]. Against adversarial manipulation, most attacks succeed [C9]. H2 (high accuracy for distinct roles, calibrated confidence) is not established by these measurements.

### RQ3 — Anomaly detection

The detector finds nearly every injected anomaly but raises many false alarms [C10]. A learned sequence model was no better overall: it cut false alarms but lost most recall, so it was rejected [C11]. A streaming variant lowered detection latency [C12], but it did not keep up with the large topology at any tested rate [C13]. The hypothesised operating point that maximises F1 was not tuned; the detector was not retuned.

### RQ4 — Temporal change detection

Structural change detection was perfect on the synthetic evolution used, which is a ceiling effect and not evidence about hard cases [C1]. Over a simulated multi-week evolving topology, the default constants showed no measurable drift [C14]. Recalibration was nevertheless supported, for a static reason rather than drift [C15]. An ablation study found that only removing the temporal component changes any headline metric [C16], with the caveat about sample size [C17].

### RQ5 — Dependency inference

The originally claimed positive causal result for one topology did not survive multi-seed evaluation [C18]. A time-series causal-discovery method scored above the original candidate generator on both the lagged-traffic dataset and a control dataset, but remained poor [C19], with many spurious pairs [C20]. Automated constant calibration changed nothing on the static matrix [C21].

### RQ6 — Failure propagation

After a scoring bug was fixed, which invalidated all earlier failure-propagation numbers [C23], propagation prediction is accurate on the topologies tested [C22]. It also degrades under sparse observation [C24].

### RQ7 — Counterfactual simulation

Counterfactual accuracy is lower than failure-propagation accuracy, particularly on targets that are not articulation points, because the connectivity-only ground truth cannot confirm service-level effects [C25]. Root-cause ranking executes a real counterfactual for every ranked candidate, but is structural only [C26]. An active-learning policy for choosing experiments did not improve on the static ranking [C27].

## 4. Limitations

**No real-world validation.** The harness for real traces exists, but it has not been run on any real trace [C28].

**Synthetic data.** Every result above comes from a synthetic laboratory; effect sizes may not transfer to real networks, and the ceiling effects noted in RQ1 and RQ4 mean some "perfect" scores carry little information.

**Unverified language-model behaviour.** The language-model interfaces are verified only with a scripted model [C29].

**Sample sizes.** Seed counts are small and the variance covers traffic generation only, not topology [C17].

## 5. Reproducibility

The verification suite and both static gates can be re-run with one command (`repro/run.sh`). At Phase 106 the reported state was [C30]. This re-runs the project's own tests; it is not an independent re-derivation of the results.
