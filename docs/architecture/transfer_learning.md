# Cross-Topology Transfer Learning (Phase 81)

Spec (master spec addendum, Arc B): train role/anomaly models on some Phase 18 topology families and measure
real zero-shot and few-shot generalization to unseen archetypes; report degradation honestly.

**Verdict: the role model does not transfer; the anomaly LSTM transfers (and matches MAD), but naive
few-shot adaptation hurts. Nothing is wired into the pipeline.** Code: `experiments/transfer_benchmark.py`,
CLI `scripts/run_transfer_benchmark.py`, tests `experiments/tests/test_transfer_benchmark.py`.

## Protocol
- Split unit is the **archetype**, not the matrix level: `medium` and `multi_service` are both stars, so
  leave-one-level-out (Phase 78) still leaves the archetype in training. Archetypes: chain, star, multi_tier,
  multi_path, redundant, dynamic (seeded random), each at two sizes.
- Leave-one-archetype-out. Seeds are pairwise disjoint: train 100-102, few-shot support 200-201, test 42-45
  (enforced; `ValueError` otherwise). Data are Phase 76's anomaly datasets at completeness 1.0; role samples are
  (fingerprint, declared role) per node per normal baseline epoch.
- Modes: `in_distribution` (train on the held-out archetype's own training seeds), `zero_shot` (other five),
  `few_shot k` (zero-shot + k labeled nodes from the support seeds, chosen round-robin over roles: role model
  pools their fingerprints; LSTM is fine-tuned 50 epochs at lr 0.003 with threshold re-derived from them),
  `scratch k` (same k nodes alone). Anomaly scoring is Phase 78's shared protocol at 8 history epochs; MAD is the
  transfer-free comparator.
- Unseen roles (a role present only in the held-out archetype, e.g. the star's GATEWAY) are reported as
  `unseen-role share`, with accuracy over seen roles separately.

## Results (real run, 6 folds; one run, seeds fixed, no confidence intervals)

### Role model (Naive Bayes) - accuracy
| held-out | in-dist | zero-shot | few-shot k=5 | scratch k=5 | unseen-role share (zero-shot) |
|---|---|---|---|---|---|
| chain | 0.984 | 0.543 | 0.543 | 1.000 | 0 |
| star | 1.000 | 0.815 | 0.868 | 0.955 | 0.143 |
| multi_tier | 1.000 | 0.972 | 0.974 | 1.000 | 0 |
| multi_path | 0.997 | 0.455 | 0.455 | 0.889 | 0 |
| redundant | 0.984 | 0.431 | 0.431 | 0.891 | 0 |
| dynamic | 0.859 | 0.431 | 0.574 | 0.761 | 0.357 |

Zero-shot degradation is large (0.03 to 0.55 accuracy) and ECE rises from ~0.01 to 0.45-0.56 for four
archetypes, i.e. the model is confidently wrong. Only multi_tier (whose roles overlap the training archetypes'
client/api/database pattern) transfers; star loses 0.19. Few-shot by pooling barely moves the model: k nodes (8 fingerprints
each) are swamped by thousands of source fingerprints. Training from scratch on the same 5 nodes beats the
"transferred + adapted" model on all 6 archetypes, so for the role model the source archetypes are a
liability. Role features here largely encode position/degree in the archetype, which does not carry across.

### Anomaly model (LSTM vs MAD) - F1
| held-out | MAD | LSTM in-dist | LSTM zero-shot | LSTM few-shot k=5 | LSTM scratch k=5 |
|---|---|---|---|---|---|
| chain | 0.480 | 0.352 | 0.478 | 0.194 | 0.225 |
| star | 0.576 | 0.604 | 0.662 | 0.424 | 0.196 |
| multi_tier | 0.328 | 0.351 | 0.367 | 0.275 | 0.088 |
| multi_path | 0.536 | 0.392 | 0.645 | 0.240 | 0.173 |
| redundant | 0.465 | 0.349 | 0.519 | 0.224 | 0.194 |
| dynamic | 0.391 | 0.365 | 0.404 | 0.145 | 0.106 |

The LSTM's inputs are normalized by each node's own history, so it learned topology-independent dynamics:
zero-shot F1 is at or above MAD on 5 of 6 archetypes (chain 0.478 vs 0.480 is a tie) and recall stays 0.72-1.0.
Precision is low everywhere (0.27-0.50), the same over-alarming Phase 78 found. Fine-tuning lowers F1 on every
archetype (e.g. multi_path 0.645 -> 0.240): re-deriving the alarm threshold from a handful of normal residuals
gives a too-low threshold and many false alarms; scratch on k nodes is worse still. (The threshold recomputation
is the probable cause; a variant keeping the zero-shot threshold was not run.)

### Caveat on "degradation"
LSTM in-distribution F1 is *lower* than zero-shot (negative degradation in every row). "In-distribution" here
is trained on one archetype's 3 seeds x 2 sizes, versus five archetypes for zero-shot, so it is a
smaller-training-set baseline, not an upper bound; the gap mixes topology shift with data quantity. For the
role model the in-distribution number is a fair upper bound only because Naive Bayes is cheap to fit on little
data.

## Limitations
- Six archetypes, two sizes each, one seed set, no confidence intervals; `dynamic` overlaps others loosely.
- Synthetic traffic with one generic HTTP/TCP edge type: shared traffic generator across archetypes probably
  flatters anomaly transfer; real networks would differ. Not measured.
- Role labels are declared roles on this generator; the star's hub and dynamic's CACHE/WORKER are unlearnable
  when held out, which the table reports rather than hides.
- Few-shot adaptation was a single recipe per model. Better recipes (weighted pooling, keeping the zero-shot
  threshold) were not tried, so "few-shot does not help" applies to these recipes only.

## Decision
Do not adopt transfer for role classification; per-network fitting (even 5 labeled nodes) is better. The
anomaly LSTM's zero-shot generalization is a measured property, but it only ties MAD, which needs no training,
so Phase 78's rejection stands. No API, matrix or pipeline change.
