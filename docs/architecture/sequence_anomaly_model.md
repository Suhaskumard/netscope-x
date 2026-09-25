# Phase 78: deep sequence model for anomaly detection

Spec addendum Phase 78: implement an LSTM- or Transformer-based sequence model over per-node behavioral
fingerprint history as an alternative to Phase 38-40's MAD/z-score detector, benchmark it against the
existing detector on Phase 76's injected-anomaly ground truth, and document cold-start requirements and the
interpretability lost relative to Phase 41's evidence reports.

**Decision: rejected as a replacement.** On the same labeled data the LSTM found 14% of the injected
anomalies where MAD/z-score found 99%. It raised roughly a sixth as many false alarms, but the recall loss
outweighs that (F1 0.149 versus 0.384). It is left as a tested, measured alternative; nothing in the
detector, the matrix or the API uses it.

## What was built

- `backend/flowmind/anomaly/sequence_model.py`: a one-layer LSTM (hidden 16, 1,412 parameters) plus a linear
  head in plain numpy (torch is not a project dependency; `requirements.txt` is unchanged), with
  hand-written backpropagation through time checked against numerical gradients for every parameter block.
  LSTM rather than Transformer: with 8-epoch histories a Transformer has nothing to attend over.
  - Features per epoch: `distinct_destinations`, `mean_flow_duration_seconds`, `outbound_byte_ratio`,
    `log1p(total_byte_count)`, mapped to DESTINATIONS, TIMING, BEHAVIOR and TRAFFIC_VOLUME. PORTS and
    PROTOCOLS (set-novelty checks) are not covered.
  - Each node's history is normalized by its own median and a MAD-based scale with provisional floors, and
    clipped to ±10 scales. The clip was added after a trial run showed the training loss at about 3x10^7:
    a 2-3 epoch history gives a badly estimated scale, so a few samples normalized to thousands and dominated
    the squared error. The clip was chosen from the training loss, not from test scores, but the trial
    tables were visible when it was made.
  - The network reads a node's preceding epochs and predicts the next epoch's normalized features. Trained
    on NORMAL histories only (never an anomaly or a label). The residual scale and the alarm threshold (the
    99th percentile of pooled training residuals) come from training data and were fixed in advance.
  - `detect_sequence_anomalies` returns the existing `Anomaly` model, one per feature whose scaled residual
    exceeds the threshold, with observed-versus-expected evidence text.
- `experiments/anomaly_fingerprints.py`: the per-epoch fingerprint builder, factored out of the matrix's
  Phase 76 scoring so every detector sees the same history (Phase 76 numbers unchanged, tests green).
- `experiments/sequence_anomaly_benchmark.py` and `scripts/run_sequence_benchmark.py`: the benchmark.

## Benchmark protocol

Both detectors are scored by `evaluate_anomaly_detection` on Phase 76's datasets (same labels, same
fingerprints). Comparison is restricted to the four shared continuous dimensions, with `total_checks` =
nodes x 4 x test epochs for both; MAD detections on PORTS/PROTOCOLS were dropped (3,034 of them over the
run) and counted. Leave-one-topology-level-out: the LSTM trains on the normal baseline epochs of the other
five topologies (training seeds 100-104, completeness 1.0 and 0.5, both traffic settings) and is tested on
the held-out one (test seeds 42-46, five completeness levels, both settings). MAD builds its baseline from the
`history_epochs` baseline epochs before the test epochs. The LSTM is online: each test epoch is judged from
those epochs plus every earlier test epoch, so an earlier injected anomaly contaminates later predictions,
as it would in deployment. A cold-start sweep varies `history_epochs` over 2, 3, 5 and 8.

## Results (mean ± sample stdev over all topologies and completeness levels)

Default traffic (the matrix's own volume):

| history epochs | method | recall | precision | F1 | clean-epoch false-alarm rate |
|---|---|---|---|---|---|
| 2 | MAD/z-score | 0.000 | 0.000 | 0.000 | 0.000 |
| 2 | LSTM | 0.139 ± 0.114 | 0.158 ± 0.145 | 0.132 ± 0.102 | 0.028 |
| 3 | MAD/z-score | 0.000 | 0.000 | 0.000 | 0.000 |
| 3 | LSTM | 0.144 ± 0.114 | 0.169 ± 0.147 | 0.138 ± 0.104 | 0.028 |
| 5 | MAD/z-score | 0.995 ± 0.030 | 0.193 ± 0.083 | 0.316 ± 0.115 | 0.218 |
| 5 | LSTM | 0.142 ± 0.116 | 0.192 ± 0.175 | 0.143 ± 0.112 | 0.026 |
| 8 | MAD/z-score | 0.994 ± 0.033 | 0.246 ± 0.104 | 0.384 ± 0.133 | 0.145 |
| 8 | LSTM | 0.144 ± 0.118 | 0.226 ± 0.227 | 0.149 ± 0.118 | 0.025 |

Low-volume traffic, 8 epochs: MAD recall 0.710 ± 0.306, precision 0.173, F1 0.264, clean-epoch false-alarm
rate 0.186; LSTM recall 0.165 ± 0.157, precision 0.462 ± 0.417, F1 0.218, false-alarm rate 0.019.

Per topology (default, 8 epochs): on `small` the LSTM found none of the injected anomalies at any
completeness level (recall 0.000, F1 0.000, against MAD recall 1.000); on `medium` at full observation it
found 12.5% (F1 0.177 versus 0.551). Latency is at least one epoch for both (about 59.8 s); the LSTM's
mean is higher (61.5 s default, 95.6 s low-volume) because some detections come an epoch later.

Training: 680-860 histories and 4,080-5,160 samples per fold; 18-46 s per fold (measured while other jobs
were running, so an upper bound); final training loss 2.18-2.36; alarm threshold 4.65-4.93 scaled residual
units.

## Findings

1. **Recall collapses.** Recall is 0.144 against 0.994 at 8 epochs. The trade is real: the clean-epoch
   false-alarm rate falls from 0.145 to 0.025. But an anomaly detector that finds one injected anomaly in
   seven is not useful, and F1 is 0.149 versus 0.384.
2. **Probable mechanism (a hypothesis, not isolated).** The alarm level is a training-residual quantile. The
   training residuals are heavy-tailed (short prefixes normalize noisily, clipped at ±10), so the threshold
   lands at about 4.8 scaled units, and a clipped ±10 deviation divided by the residual scale is only just
   above it. The MAD detector's threshold (z = 3 on an un-scaled MAD) is far more sensitive. Threshold
   sensitivity was **not swept**, so how much recall is recoverable by a different quantile is unknown.
   An early 2-seed, 60-epoch, 3-topology exploratory run had recall about 0.76 with a threshold near 3.3,
   which shows recall depends strongly on this one number; it is not a measured result.
3. **Cold start.** MAD needs 5 observations (Phase 38) and returns nothing below that (recall 0.000 at 2 and
   3 epochs). The LSTM scores from 2 epochs, but at that point it finds only about 14% of the anomalies
   (F1 0.13), so the advantage is real but small. It does not improve with more history (0.139 at 2 epochs,
   0.144 at 8): the history in this dataset is too short and too featureless for the network to use.
4. **The synthetic baseline has almost no temporal structure.** Normal epochs are independent jitter around
   a constant, so there is nothing for a sequence model to learn beyond what a median already captures. A
   sequence model's advantage would need trends, periodicity or drift; this benchmark has none.
5. **Contamination.** Because the LSTM is online, the spike epoch is part of the history when the next epoch
   is judged. The effect was not isolated from the recall loss.

## Interpretability lost versus Phase 41

Phase 41's reports state a named historical statistic ("moved from a typical value of 4 to 9, robust z-score
7.2, threshold 3.0"). The LSTM's evidence states the observed value, the model's expected value and a scaled
residual, but the expectation is the output of a learned function of the sequence, not a statistic a reader
can recompute or audit. It also gives no explanation for why the expectation was what it was, and it covers
four of the six dimensions.

## Complexity

1,412 parameters; one forward pass over a window of at most 8 steps per node per epoch (small in absolute
terms, but far more than the MAD baseline's per-feature median). Training needs a corpus of normal
histories from other networks; the detector needs none.

## Why rejected, and what would change that

Rejected on measured recall, plus a labeled-data requirement (normal histories) and weaker explanations. It
would be worth revisiting with (a) longer histories with real temporal structure, (b) a threshold chosen
against a held-out validation set rather than a fixed training quantile, and (c) PORTS/PROTOCOLS coverage.

## Limitations

Synthetic, spurious-free traffic; two injection types; six topology shapes; the ±2 volume jitter and the
scale floors are provisional constants; the threshold quantile was fixed in advance and never swept; the MAD
side keeps its Phase 40 defaults, so this compares defaults, not tuned detectors.

## Verification

- `backend/tests/test_sequence_anomaly_model.py` (8 tests): BPTT matches numerical gradients for every
  parameter block, prefix sampling, determinism, loss decreases, a volume spike and a destination burst are
  flagged while normal behavior is not, cold start returns nothing below `min_history`, invalid inputs
  rejected.
- `experiments/tests/test_sequence_anomaly_benchmark.py` (8 tests): example construction and labels, the
  shared fingerprint path matches the matrix's, MAD returns nothing below 5 epochs and matches a direct call
  to `detect_node_anomalies`, both methods scored on identical labels, train and test disjoint, the
  held-out level is never trained on.
- Full suite 708/708; `validate_data_contracts` 55/55; `check_ground_truth_boundary` clean.
