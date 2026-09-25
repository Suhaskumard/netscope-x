# Phase 77: GNN-based topology and edge-confidence model

Spec addendum Phase 77: train a graph neural network to predict edge existence/confidence from flow
features as an alternative to Phase 31's noisy-OR heuristic, benchmark it head-to-head with Phase 32's
`compare_topology_to_ground_truth`, and document complexity, training-data requirements, failure cases and
whether it is adopted or rejected, with measured evidence.

**Decision: rejected as a replacement for the heuristic.** On the same six topologies it never beat the
heuristic on edge F1 in a way larger than seed noise, and it added a real failure mode (hallucinated edges
on an unseen topology shape). It is left in the repository as a tested, measured alternative; nothing in
`build_topology_graph`, the API or the matrix uses it.

## What was built

- `backend/nettrace/topology/gnn_edge_model.py` — a small graph neural network in plain numpy (torch is not
  a project dependency; `requirements.txt` is unchanged) with hand-written backpropagation.
  - Input: `GraphExample` from observed evidence only (flows plus the heuristic graph): six node features
    (distinct destinations, outbound byte ratio, log total bytes, listening-port count, observed degree,
    observed weighted degree) and three pair features (log observation count, heuristic confidence,
    observed flag).
  - Model: `A_hat = D^-1/2 (A + I) D^-1/2`; `H1 = relu(A_hat X W1 + b1)`; `H2 = A_hat H1 W2 + b2`;
    `logit(u, v) = w . [H2_u * H2_v, |H2_u - H2_v|, P_uv] + b`. `A` is the heuristic confidence of each
    observed pair. Scores are symmetric and node-permutation equivariant (tested).
  - It scores **every** node pair, so unlike the heuristic it can propose an edge with no flow evidence
    (link prediction) and can reject an observed one.
  - Training: full-batch Adam, class-balanced binary cross-entropy over all node pairs, L2, deterministic
    per seed. The backpropagation is checked against numerical gradients for every parameter block.
  - Labels are a plain array supplied by the caller; the module never imports `simulator.ground_truth`.
- `experiments/gnn_benchmark.py` and `scripts/run_gnn_benchmark.py` — the benchmark.

## Benchmark protocol

Three methods, all scored by `compare_topology_to_ground_truth` (which scores the edge *set*, so each
method is turned into a `TopologyGraph`):

| method | edges kept |
|---|---|
| `heuristic` | every node pair with any flow (the existing graph as-is) |
| `heuristic_thresholded` | heuristic edges with confidence >= 0.5 |
| `gnn` | every node pair with GNN probability >= 0.5 (unobserved pairs get a synthesized edge whose evidence says "GNN link prediction, no observed flows") |

- **Leave-one-topology-level-out.** For each of the six matrix topologies the GNN is trained on the other
  five (training seeds 100-104, both traffic settings, five completeness levels) and tested on the
  held-out one (test seeds 42-51). It never sees the held-out topology or any test seed. The 0.5 threshold
  was fixed in advance.
- **Two traffic settings.** `default` is the matrix's own volume. At that volume every declared edge
  survives sampling with probability >= 0.9999 (Phase 74), so the completeness axis is flat and there is
  nothing to recover; it is a sanity row. `lowvol` is Phase 74's low-volume sweep (1 request/response
  pair per edge, no pulses), where edges are genuinely lost to observation sampling.
- Real run: 6 folds, 249-250 training examples and 5.3k-8.4k node pairs per fold, 268 parameters
  (hidden 16, embedding 8, 200 epochs), final training loss 0.059-0.100; 10 test seeds x 5 completeness
  levels x 2 settings per topology.

## Results (10 test seeds; mean ± sample stdev over all test examples)

Edge F1 / precision / recall over every topology and completeness level:

| setting | metric | heuristic | heuristic_thresholded | gnn |
|---|---|---|---|---|
| default | F1 | 1.000 ± 0.000 | 0.994 ± 0.024 | 0.998 ± 0.012 |
| default | precision | 1.000 ± 0.000 | 1.000 ± 0.000 | 0.996 ± 0.022 |
| default | recall | 1.000 ± 0.000 | 0.990 ± 0.043 | 1.000 ± 0.000 |
| lowvol | F1 | 0.912 ± 0.152 | 0.489 ± 0.334 | 0.877 ± 0.165 |
| lowvol | precision | 0.993 ± 0.082 | 0.807 ± 0.396 | 0.923 ± 0.171 |
| lowvol | recall | 0.867 ± 0.205 | 0.391 ± 0.312 | 0.873 ± 0.199 |

Per-topology, `lowvol` edge F1 (heuristic vs GNN) at selected points:

| topology | completeness | heuristic | gnn |
|---|---|---|---|
| large | 1.0 | 1.000 ± 0.000 | 0.682 ± 0.010 |
| large | 0.5 | 0.835 ± 0.048 | 0.758 ± 0.038 |
| large | 0.25 | 0.619 ± 0.085 | 0.635 ± 0.058 |
| dynamic | 0.5 | 0.861 ± 0.065 | 0.823 ± 0.070 |
| small, medium, multi_path, multi_service | all 20 cells | within 0.01 of the heuristic (identical in 17) | |

What the GNN did to the edge set (mean per test example, averaged over all six topologies, so the
hallucination count is dominated by one topology; see finding 3):

| setting | completeness | recovered (true, unobserved) | hallucinated (not an edge) | dropped observed |
|---|---|---|---|---|
| default | 1.0 / 0.5 / 0.25 | 0.00 / 0.00 / 0.00 | 0.00 / 0.00 / 0.72 | 0.00 |
| lowvol | 1.0 | 0.00 | 4.98 | 0.00 |
| lowvol | 0.75 | 0.13 | 4.48 | 0.00 |
| lowvol | 0.5 | 0.12 | 1.35 | 0.00 |
| lowvol | 0.25 | 0.37 | 0.75 | 0.00 |

Expected calibration error of edge confidence against edge truth (`lowvol`): GNN 0.093-0.123, heuristic
0.219-0.362. At default volume the two are close (GNN 0.011-0.033, heuristic 0.013-0.064).

## Findings

1. **No F1 gain.** Where the two differ, the GNN is mostly slightly worse or tied; the only cell where it is
   ahead (`large`, c=0.25, +0.016) is well inside one stdev. Where it recovers edges the heuristic missed,
   it recovers almost none: at most 0.37 true edges per example at c=0.25, at the cost of hallucinations.
2. **Most of the time it copies the heuristic.** In all 20 `lowvol` cells of the four topologies other than
   `large` and `dynamic` its F1 is within 0.01 of the heuristic's (identical in 17), because "observed" is among its inputs and observed pairs are all real in
   this synthetic data. Recovery of unobserved edges needs structure it has to generalize from other
   topologies, and that is where it failed.
3. **Failure case: unseen topology shape.** Holding out `large` (tiers 2-4-4-2, 32 declared edges), at full
   observation the GNN keeps every true edge but precision is 0.517 and F1 0.682 versus the heuristic's
   1.000. That implies roughly 60 predicted edges, about 30 of them not real (derived from the reported
   precision and recall, not counted directly). The 4.98 in the table above is this one topology's
   contribution averaged over six. The
   cause was not isolated; a plausible reading is that the other five topologies contain no layered
   structure, so it extrapolates tier adjacency incorrectly. That is a hypothesis, not a measurement. With
   6 topology shapes this is a real limit on how much can be said.
4. **Thresholded heuristic confidence is a poor edge classifier** (`lowvol` F1 0.489). The noisy-OR value is
   evidence strength, not the probability that an observed pair is an edge. Its ECE is worse than the
   GNN's for that reason; this is not evidence the heuristic mis-ranks anything, because the benchmark's
   heuristic graph keeps every observed edge regardless of confidence.
5. **The benchmark favors the heuristic on precision.** The synthetic traffic contains no spurious pairs,
   so any observed pair is a true edge. On a network with scanning, misconfigured or shared-infrastructure
   traffic a learned model could do better; this benchmark cannot show it.

## Complexity

- Parameters: 268 (features 6, pair features 3, hidden 16, embedding 8). Scoring all pairs of an n-node
  graph costs O(n^2 (embedding + pair features)) plus O(n^2 hidden) for message passing on the dense
  matrix, so it is a small-network model; for large networks the dense all-pairs form would need a sparse
  or candidate-pair variant.
- Training: full-batch over all pairs of all examples; about 250 examples took seconds per fold in numpy.

## Training-data requirements

- Needs labeled topologies. The heuristic needs none. Here the labels are the declared scenario edges; a
  real deployment would need a network whose true edges are known.
- Needs a distribution match. The one topology with a shape absent from training (`large`) is where it
  failed. With only six shapes, "how many topologies are enough" was not measured and is left open.

## Why rejected, and what would change that

Rejected because the measured benefit is zero or negative and it adds a failure mode plus a labeled-data
requirement. It would be worth revisiting with (a) traffic that contains spurious observed pairs, where the
heuristic's precision is no longer 1.0, (b) many more topology shapes, and (c) a sparse candidate-pair
formulation. The lower ECE is real but not, on its own, a reason to adopt it, because the confidence value
does not change the edge set that `compare_topology_to_ground_truth` scores.

## Verification

- `backend/tests/test_gnn_edge_model.py` (7 tests): numerical-gradient check for every parameter block,
  determinism per seed, valid probabilities, permutation equivariance, loss decreases and a learnable graph
  is fit, parameter count, invalid inputs rejected.
- `experiments/tests/test_gnn_benchmark.py` (9 tests): labels match declared edges by IP; low volume loses
  edges the default keeps; unknown variant rejected; threshold respected; unobserved predictions labelled as
  model predictions; calibration error; the held-out level and seeds are excluded from training; scoring
  uses the real `compare_topology_to_ground_truth`.
- `scripts.check_ground_truth_boundary` is clean (no backend import of `simulator.ground_truth`).
