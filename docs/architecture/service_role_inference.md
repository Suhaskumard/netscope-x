# NETSCOPE-X — Service Role Inference

Phase 36 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 36 — SERVICE ROLE INFERENCE"):
"Infer roles such as: Client, Gateway, API, Database, Cache, DNS, Worker, Load Balancer, Unknown."
FR-1.14 (`docs/requirements/system_requirements.md`): "The system shall infer a service role per node
... with a calibrated confidence distribution across candidate roles, not a single hard label (spec
Phase 36–37; RQ2)."

Code: `backend/flowmind/classification/role_classifier.py` (`fit_role_model`/`classify_node_role`) —
the first code to populate `backend/app/models/behavior.py`'s `RoleClassification` schema with real
data, and the first phase to implement `docs/architecture/algorithm_selection.md` §2's
already-selected role-inference algorithm.

## The Phase 36 vs. 37 boundary: "real posterior" vs. "calibrated"

FR-1.14 requires a "calibrated confidence distribution." RQ2 (`docs/research/research_questions.md`)
defines calibration precisely: "does a node classified 'Database: 72%' actually turn out to be a
database roughly 72% of the time across many such classifications?" — answering that requires scoring
predicted confidence against ground truth across many real classifications, which is explicitly
Phase 37/68 territory (the master spec's own Phase 37 title is "UNCERTAINTY-AWARE CLASSIFICATION";
RQ2's hypothesis names "calibration error established empirically in Phase 37/68"). Phase 36 produces
a **real, genuinely-computed posterior distribution** via Bayes' rule — not a fabricated value, not a
hard label — but has **not been validated as calibrated** in RQ2's sense. This mirrors the Phase
30→31→32/68 edge-confidence precedent exactly: Phase 30/31 built a real, evidence-backed but
uncalibrated score; genuine calibration against ground truth stayed deferred further out.

## Why this phase implements exactly `algorithm_selection.md` §2's already-made selection

Phase 05 already evaluated four alternatives for role inference and selected "(b) Naive-Bayes-style
probabilistic classifier over engineered behavioral features (port set entropy, protocol mix, traffic
directionality, persistence, destination diversity)... trained on a held-out labeled split of
lab-generated data (topology/role ground truth used only for training and evaluation splits, never
for the pipeline's live inference — per §4/REPRO-4)." This is not re-litigated here — Phase 36
implements it.

## No Docker, no real labeled training data this session — explicit, prominent limitation

`algorithm_selection.md` §2's own selection requires a "held-out labeled split of lab-generated data"
to fit the classifier's class-conditional likelihoods. This session's environment has no Docker, so no
real lab traffic can be captured and labeled — the same constraint every prior Docker-dependent phase
(21, 32) has already hit. **Phase 36's real, honest deliverable this session is the trainer/classifier
machinery itself** (`fit_role_model`/`classify_node_role`), verified with synthetic labeled test
fixtures — the same way every other phase's tests use synthetic `Flow`/`Packet` fixtures, since a
classifier's correctness is independently verifiable against known, controlled inputs regardless of
where real training data eventually comes from. **No model trained on real data is shipped or
persisted by this phase, and `GET /behaviors/{node_id}` stays a 501 stub** — wiring it would require
either a fabricated role (forbidden) or a synthetic-data-only "trained" model presented as real
(equally forbidden). Producing a genuine labeled dataset from the Docker lab is left to whichever
future phase actually has lab access.

## Algorithm

### Feature engineering

`BehavioralFingerprint`'s six real fields (Phase 33-35) are mapped onto §2's five named feature
families:

| §2's feature family | Representation | Type |
|---|---|---|
| Port set entropy | `port_count = len(distinct_ports)` | continuous (Gaussian) |
| Protocol mix | presence flags for `{TCP, UDP, ICMP, OTHER}` | binary (Bernoulli) |
| Traffic directionality | `outbound_byte_ratio` | continuous (Gaussian) |
| Persistence | `is_persistent_talker` | binary (Bernoulli) |
| Destination diversity | `distinct_destinations` | continuous (Gaussian) |
| (additional) | `mean_flow_duration_seconds` | continuous (Gaussian) |
| (additional) | well-known-port presence flags (80/443/5432/6379/53) | binary (Bernoulli) |

`port_count` is an explicitly stated simplification for "port set entropy": `BehavioralFingerprint`
only carries the *set* of ports observed, not per-port usage frequency, so true Shannon entropy isn't
computable from this schema — a count is the closest honest proxy. The 5 well-known ports reuse
`backend/nettrace/fingerprint.py`'s exact Phase 26 table (not re-derived or expanded), avoiding an
unjustified new port vocabulary.

### Fitting (`fit_role_model`)

Groups labeled `(BehavioralFingerprint, ServiceRole)` pairs by role; for each role, fits a per-feature
Gaussian (mean, variance) for continuous features and a Laplace-smoothed Bernoulli probability for
binary features, plus a frequency-based prior `P(role)`. Raises `ValueError` on empty input — unlike
other FLOWMIND functions' "honest zero for no evidence" convention, a classifier genuinely cannot be
fit from nothing, so this is a real failure, not gracefully-empty output.

- **Variance floor** (`variance_floor`, default `1e-6`): prevents a divide-by-zero when a role's
  training sample has identical values for some continuous feature (e.g. a single training example,
  or coincidentally uniform data) — without it, a zero-variance Gaussian's log-pdf is undefined.
- **Laplace smoothing** (`laplace_smoothing`, default `1.0`, add-one-style): prevents a binary
  feature's fitted probability from locking to exactly `0.0` or `1.0` from a small or unanimous
  sample, which would otherwise make one contrary observation log-probability `-∞` (infinitely
  improbable) rather than merely unlikely.

Both are standard, documented Naive Bayes practice — plain function parameters, not `Settings` fields,
since nothing calls this from an API route yet (consistent with `discover_nodes`/`discover_edges`
staying plain-parameter-configured until wired).

### Classification (`classify_node_role`)

For each candidate role: `log_posterior = log(prior) + Σ Gaussian_log_pdf(continuous features) +
Σ Bernoulli_log_pmf(binary features)`. Converted to a real probability distribution via a
numerically-stable softmax (subtract the max log-posterior before exponentiating, to avoid overflow).
The resulting `Dict[ServiceRole, float]` is passed straight into a real `RoleClassification` — that
model's own Phase 04 validator (sums to ~1.0, every value in `[0,1]`) is the genuine acceptance test
for this function's output, not re-implemented here.

## Complexity

Fitting: O(N·n) for N labeled training examples and n features (11 total: 4 continuous + 7 binary) —
matches `algorithm_selection.md` §2's own complexity note, "done offline/periodically, not
per-inference." Classification: O(k·n) per node for k candidate roles — negligible.

## Failure cases

Empty training data: `fit_role_model` raises `ValueError` (a real failure, not gracefully-empty
output — nothing meaningful can be classified without at least one example). A role with only one
training example: the variance floor still produces a finite, valid classification (verified:
`test_single_training_example_role_still_classifies_without_error`).

## Known limitations

- **No model trained on real Docker-lab data exists** — the single most important limitation this
  phase carries forward. Everything verified this session uses synthetic labeled fixtures.
- **Conditional feature independence** (the Naive Bayes assumption) is only approximately true — e.g.
  port count and protocol mix are correlated in reality — a known, accepted simplification per
  `algorithm_selection.md` §2's own stated limitation, not hidden here.
- **Not validated as calibrated** — explicitly Phase 37's job.
- **`GET /behaviors/{node_id}` stays unwired.**

## Verification actually performed this phase

- `pytest backend/tests/test_flowmind_role_classifier.py -v` — **7/7 passed**: `fit_role_model` raises
  on empty input; two clearly-separated synthetic profiles (DNS-like: UDP/port 53/low-duration;
  Database-like: TCP/port 5432/persistent/high-duration) each classify correctly on held-out data;
  `role_probabilities` always sums to ~1.0 with every value in `[0,1]`; a role with a single training
  example still produces a valid classification (variance-floor check); two profiles differing *only*
  in protocol (TCP-only vs. UDP-only, otherwise identical) each classify to their correct role,
  isolating the protocol-mix signal specifically; identical inputs produce identical output across
  repeated calls; a real end-to-end-shaped test building labeled fingerprints via
  `assemble_node_fingerprint` from constructed `Flow`/`Node` data (the actual FLOWMIND pipeline types,
  not just hand-built dataclasses) correctly classifies both roles.
- Full repo suite (`pytest`, run from repo root) — **279/279 passed** (up from 272/272), no
  regressions.
- `python -m scripts.validate_data_contracts` — 38/38 passed, no regression (`RoleClassification`
  schema unchanged since Phase 04; this phase populates it, doesn't modify it).
- `python -m scripts.check_ground_truth_boundary` — clean.

## Status

Service role inference's algorithm (spec Phase 36, FR-1.14) is implemented and unit-verified: a real
Naive Bayes trainer and classifier, computing genuine Bayes-rule posteriors over `BehavioralFingerprint`
features, exactly as `algorithm_selection.md` §2 already selected. No model trained on real lab data
exists yet (no Docker this session), and `GET /behaviors/{node_id}` remains unwired as a direct
consequence. Calibration (FR-1.14's full requirement) remains explicitly Phase 37's job.
