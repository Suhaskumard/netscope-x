# Phase 80: active-learning experiment recommendation policy

Spec addendum Phase 80: replace Phase 67's static criticality-based experiment suggestion with a policy that
learns which experiment to run next to maximize digital-twin prediction accuracy (information gain), using a
real reward from Phase 63/66's prediction-validation results, and compare it with Phase 67's static ranking on
real accuracy improvement per experiment run.

**Decision: rejected as a replacement for Phase 67.** The learned policy was not better than the static
ranking on accuracy gained per experiment (0.009 versus 0.014), reached the same final accuracy only by
running about twice as many experiments, and pre-training on other topologies made no measurable difference.
The accuracy the twin gained came from repairing the twin around the experiments that were run, not from
anything that transferred to untested nodes (held-out gain about 0). The result is also a positive finding
for Phase 67: its static ranking is a strong baseline, roughly twice as good per experiment as random choice.

## What was built

- `backend/dependency/experiment_policy.py` (numpy; no ground truth):
  - **`LinUCBPolicy`**: a contextual bandit with one linear model shared across nodes. Features come only
    from the twin's own graph: bias, degree, betweenness, articulation flag, path-dependency impact,
    mean incident-edge confidence, predicted stranded fraction, and adjacency to an already repaired node.
    Score = theta.x + alpha sqrt(x A^-1 x); it never re-selects a tested node.
  - **`StaticPolicy`** (Phase 67's ranking, computed once, may run out before the budget) and
    **`RandomPolicy`** (seeded baseline).
  - **`repair_twin`**: the update. After failing a node, reality's largest surviving component is compared
    with the twin's. A twin component wholly inside reality's largest one but disconnected from the twin's
    best match is a false stranding, so ONE bridging edge is added per such component (between the nodes
    nearest the failed node), flagged as experiment-inferred with confidence 0.5. One experiment cannot say
    which real edge is missing, so a bridge is a guess. The repair only adds edges: it cannot fix a spurious
    edge (reported as `missing_stranding_count`) or a propagation false positive.
- `experiments/experiment_policy_benchmark.py`, `scripts/run_experiment_policy_benchmark.py`: the benchmark.

## The reward

For each experiment the twin's prediction for that failure is scored against the real outcome with Phase 63's
`evaluate_failure_propagation_prediction` (through the matrix's own `_evaluate_failure_target`, which also runs
Phase 66's counterfactual comparison). **Reward = 1 - affected-node F1**, the twin's real prediction error on
the experiment just run, before its repair. It is never synthesized; a unit test recomputes it independently.
Phase 66's counterfactual F1 is reported as a second accuracy measure but is not part of the reward, because
Phase 73 showed its connectivity-only truth cannot confirm service-level impacts.

The real outcome comes from the declared topology (no Docker lab exists here), the substitute Phases 68 and
73 already use.

## Benchmark

An episode is one twin, one policy, and a budget of 4 experiments. The twin is the matrix's own low-volume
capture (`SENSITIVITY_SWEEP`) at completeness 0.75, 0.5 and 0.25, where observation sampling really loses
edges. Policies: `static`, `linucb` (pre-trained on the other five topologies, then online), `linucb_cold`
(no pre-training), `random`; identical twins, budget and scoring. Leave-one-topology-level-out: pre-training
uses 75 episodes from the other levels with seeds 100-104, testing uses seeds 42-51, alpha 1.0 and ridge 1.0
fixed in advance. 712 episodes (2 twins with no discoverable node were skipped and counted).

Accuracy is the mean Phase 63 affected-node F1 over every node as a failure target (`all nodes`) and over the
nodes not yet experimented on (`held-out`, measured on the same final held-out set at start and end, so a
repair that merely fits the experiments it ran is not counted as learning).

### Results (pooled over 178 episodes per policy)

| policy | experiments run | accuracy start | accuracy end | gain / experiment (all nodes) | gain / experiment (held-out) | counterfactual F1 change | mean reward |
|---|---|---|---|---|---|---|---|
| static (Phase 67) | 1.89 | 0.947 | 0.979 | 0.014 ± 0.030 | -0.000 ± 0.019 | -0.021 | 0.155 |
| linucb | 3.80 | 0.947 | 0.981 | 0.009 ± 0.017 | 0.000 ± 0.004 | -0.023 | 0.088 |
| linucb_cold | 3.80 | 0.947 | 0.979 | 0.008 ± 0.016 | 0.000 ± 0.005 | -0.022 | 0.078 |
| random | 3.80 | 0.947 | 0.970 | 0.006 ± 0.014 | -0.000 ± 0.010 | -0.016 | 0.055 |

Mean twin accuracy after k experiments (all nodes):

| policy | 0 | 1 | 2 | 3 | 4 |
|---|---|---|---|---|---|
| static | 0.947 | 0.963 | 0.973 | 0.978 | 0.979 |
| linucb | 0.947 | 0.960 | 0.971 | 0.979 | 0.981 |
| linucb_cold | 0.947 | 0.963 | 0.973 | 0.975 | 0.979 |
| random | 0.947 | 0.951 | 0.957 | 0.963 | 0.970 |

Gain per experiment (all nodes) by topology: `small`, `medium` and `multi_service` are 0.000 for every
policy (nothing to gain). `large`: static 0.009, linucb 0.008, random 0.002. `multi_path`: static 0.044 ± 0.039,
linucb 0.020 ± 0.021, random 0.018 ± 0.020. `dynamic`: static 0.030 ± 0.043, linucb 0.023 ± 0.024, random 0.015.

Repairs: about 0.7 bridges per episode (0.47 for random), of which only 13-18% were a real declared edge.
Accuracy rose in 49-51 of 178 episodes, was unchanged in 127-136, and fell in 0-1.

## Findings

1. **Static beats the learned policy per experiment.** 0.014 against 0.009, and its curve is ahead after one
   experiment (0.963 versus 0.960) and equal after four. The metric favors a policy that stops early, and
   static does (1.89 experiments, because Phase 67 recommends only articulation points and above-average
   chokepoints); at a fixed budget of four the final accuracies are the same within noise (0.979 versus
   0.981). The per-experiment difference is about two standard errors, so it is suggestive, not decisive.
2. **Both beat random**, by roughly twice per experiment (0.014 and 0.009 versus 0.006): choosing by
   criticality helps, and the structure Phase 67 already ranks is most of what a structural-feature bandit
   can find.
3. **Pre-training did nothing measurable.** linucb 0.009 ± 0.017 against linucb_cold 0.008 ± 0.016. The
   pre-trained model does learn a weight for articulation points (a debug run showed it), but that is what
   Phase 67 already prioritizes, so it converges to the same choices.
4. **The twin's gains do not transfer to untested nodes.** Held-out gain per experiment is 0.000 ± 0.004 for
   linucb and -0.000 ± 0.019 for static. The all-node gain comes from fixing the nodes the experiments were
   run on. Consistent with this, only 13-18% of bridges were a real edge: the repair restores the connectivity
   an experiment observed, not the missing edge itself.
5. **The repair slightly hurts Phase 66's counterfactual F1** (-0.016 to -0.023 for every policy). This was
   not investigated; a plausible reading is that a wrong bridge changes counterfactual routing on other
   targets.
6. **The reward is sparse.** The twin starts at 0.947 accuracy, so most experiments have reward 0 (mean reward
   0.09 for linucb). A bandit learns from that little signal slowly, which is a limit of the setup, not proof
   that active learning cannot help.

## Limitations

The synthetic network has no spurious edges, so the repair only ever adds; topologies are tiny (3-12 nodes)
and the budget is 4, so there is little to learn; the bridging edge is a guess; features are structural, so
the learned policy can only rediscover what Phase 67 ranks; twin errors that are not missing connectivity
(propagation false positives) are unreachable by this repair; the outcome comes from the declared topology,
not a live lab; low-volume traffic only; the per-experiment metric favors early stopping. A Bayesian
edge-belief twin with an information-gain criterion (the other option considered) was not built.

## Why rejected, and what would change that

Rejected because it is not better than the static ranking it was meant to replace, and the learning does not
generalize. It would be worth revisiting with a repair that can identify the missing edge (so gains reach
untested nodes), a network with both missing and spurious edges, a larger budget, and real lab outcomes.

## Verification

- `backend/tests/test_experiment_policy.py` (10 tests): feature determinism and structure; LinUCB never
  re-selects and prefers high-reward nodes after learning; state round trip; static order equals Phase 67's
  and can run out; random is seeded; repair bridges only a real false stranding, is a no-op when the twin
  already agrees, reports stranding it cannot fix, never mutates its input.
- `experiments/tests/test_experiment_policy_benchmark.py` (7 tests): reward equals 1 - the real Phase 63 F1
  recomputed independently; held-out accounting excludes tested nodes; static can run fewer experiments than
  the budget; gain arithmetic; pre-training updates the policy; protocol guards; deterministic runs that never
  pre-train on the held-out level.
- Full suite 741/741; `validate_data_contracts` 55/55; `check_ground_truth_boundary` clean.
- A first full run crashed while printing (two twins with no node produced `None` accuracy); the harness now
  skips and counts them, and the run reported here is the fixed one.
