# NETSCOPE-X — Explainable Anomalies

Phase 41 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 41 — EXPLAINABLE ANOMALIES"):
"Every anomaly must provide actual evidence," with a worked example:

```
Node: API-2
New destination: X
Historical destinations: 4
Current destinations: 9
New port: 4444
Evidence: ...
```

FR-1.18: "Every reported anomaly shall include concrete supporting evidence (e.g., historical vs.
current destination counts, specific new ports observed) — never a bare label (spec Phase 41)."

Code: `backend/flowmind/anomaly/node_anomaly.py` (evidence-formatting fix, same functions modified,
not new ones) and `backend/flowmind/anomaly/explain.py` (new — `format_anomaly_report`).

## Two real gaps, resolved explicitly

Phase 40's own doc (`docs/architecture/multidimensional_anomaly_detection.md`) already noted that
FR-1.17 alone "unavoidably produces *some* real evidence as a side effect of computing each
deviation," but explicitly deferred standardizing/enriching that evidence to this phase. Two
concrete gaps existed, not just cosmetics:

**Formatting had drifted from the project's own established contract example.** Phase 04's own
`Anomaly` schema example (`scripts/validate_data_contracts.py`,
`evidence_values={"historical_destinations": "4", "current_destinations": "9"}`) uses clean values.
Phase 40's actual implementation always formatted continuous-feature evidence with `.3f`, producing
`"4.000"`/`"100.000"` instead — a real, demonstrable divergence, confirmed by the pre-existing test
`test_destinations_anomaly_has_expected_evidence_values` (which asserted the wrong, drifted value).
Fixed via `_format_value` in `node_anomaly.py`: a whole-numbered float renders as a clean integer
(`"4"`); a genuinely fractional value keeps 3-decimal precision (this still applies to `z_score`,
which is inherently a statistic, not a count).

**No renderer produced the spec's literal human-readable report shape.** `Anomaly.evidence`/
`evidence_values` (Phase 04) are consumed today only in raw form — nothing turned them into the
`Node: / <field>: <value> / Evidence: ...` block the spec's own worked example illustrates. This is
Phase 41's distinctive, additive deliverable: `format_anomaly_report` in the new
`backend/flowmind/anomaly/explain.py`.

## Scope decision: formatting, not new detection signals

FR-1.18's own literal wording asks for two things, both of which Phase 40 already produces per
dimension: "historical vs. current destination **counts**" (the continuous z-score checks) and
"specific new **ports** observed" (the novelty checks). Phase 41 therefore does not add new
detection signals — in particular, it does **not** add specific new-*destination*-identity tracking
(the spec's illustrative "New destination: X" line), even though the spec's worked example shows it
alongside a destination-count deviation for one node. Doing so would require threading the actual
set of outbound destination IPs (not just the count) through `NodeBehavioralFeatures` ->
`BehavioralFingerprint` -> `NodeBehavioralBaseline`, mirroring how `historical_ports`/
`historical_protocols` already work — a real, buildable enhancement, but a new detection capability,
not an evidence-formatting one, and out of this phase's confirmed scope. Documented here as a known,
honest limitation (see below), consistent with how every prior phase in this project scopes out
plausible-but-unrequested enhancements (e.g. Phase 40 scoping `TOPOLOGY` out to Phase 45) rather than
silently ignoring or inventing them.

## Design

### 1. Standardized `evidence_values` formatting (`node_anomaly.py`)

- **Continuous z-score checks** (`DESTINATIONS`, `TIMING`, `BEHAVIOR`, `TRAFFIC_VOLUME`): keys
  `historical_<label>`/`current_<label>`/`z_score`, unchanged in name; values now formatted via
  `_format_value` (clean integer for whole numbers, 3 decimals otherwise). `z_score` stays at fixed
  3-decimal precision always.
- **Novelty checks** (`PORTS`, `PROTOCOLS`): keys `new_<label>s` (comma-joined, unchanged),
  `historical_<label>_count` (unchanged), plus a new `current_<label>_count` — symmetric
  before/after counts, computed from data the function already has in hand (`current_values`),
  directly analogous to the continuous checks' historical/current pair.
- Dict keys stay semantically per-dimension (`historical_destinations`, not a generic
  `historical_value`) rather than becoming fully generic — this is *more* useful for the renderer
  below, since the label a human reads (`"Historical destinations"`) is derived directly from the
  key.
- Evidence sentences reworded for plainness (still one fact, same underlying statistic — no new
  signal): e.g. `"destinations moved from a historical typical value of 4 to 9 (robust z-score
  5.000, threshold 3.000)"`.

### 2. `format_anomaly_report` (`backend/flowmind/anomaly/explain.py`)

A pure function, `format_anomaly_report(anomalies: List[Anomaly]) -> str`, taking one or more
`Anomaly` objects that all share one `node_id` (e.g. everything `detect_node_anomalies` returned for
one fingerprint) and rendering:

```
Node: <node_id>
<Label>: <value>          # one line per key in every anomaly's evidence_values, in order
...
Evidence:
- <evidence sentence>     # one line per string in every anomaly's evidence, in order
...
```

Field labels are derived generically from each `evidence_values` key (`historical_destinations` ->
`"Historical destinations"`, underscore replaced with a space, first letter capitalized) — the
renderer does not hardcode per-dimension field names, so any current or future `AnomalyDimension`
renders unchanged. Raises `ValueError` on an empty list or a list spanning more than one `node_id`,
matching this project's established fail-fast convention for mismatched inputs (e.g.
`node_anomaly._check_fingerprint_matches_baseline`, `build_node_baseline`'s node/window checks).

### Worked example (reproducing the master spec's own API-2 scenario)

Given a node `API-2` whose historical `distinct_destinations` jitters around a median of 4, a new
observation with 9 destinations and a newly observed port `4444` produces:

```
Node: API-2
Historical destinations: 4
Current destinations: 9
Z score: 5.000
New ports: 4444
Historical port count: 1
Current port count: 2
Evidence:
- destinations moved from a historical typical value of 4 to 9 (robust z-score 5.000, threshold 3.000)
- new port(s) observed, not present in the historical set: 4444
```

Matches the master spec's own worked example's shape and numbers (`Node: API-2`, `Historical
destinations: 4`, `Current destinations: 9`, `New port(s): 4444`) exactly, aside from the spec's
illustrative (and, per the scope decision above, deliberately unimplemented) `New destination: X`
line and the additional statistic/count fields this project's real detector genuinely computes.

## Failure cases

`format_anomaly_report([])`: `ValueError`. A list of anomalies spanning more than one `node_id`:
`ValueError`. No other validation — `Anomaly` (Phase 04) already guarantees non-empty `evidence`.

## Known limitations

- **No specific new-destination identity tracking** — a `DESTINATIONS` anomaly names a count
  deviation only, never a specific new destination IP, per the scope decision above. Building this
  would mean threading an actual destination-IP set (not just its count) through
  `NodeBehavioralFeatures`/`BehavioralFingerprint`/`NodeBehavioralBaseline`, mirroring
  `historical_ports`/`historical_protocols` — a plausible future enhancement, not attempted here
  (NFR-9), left for a later phase if requested.
- **No persistence, no API wiring** — `GET /anomalies` remains a 501 stub
  (`backend/app/api/routes/anomalies.py`); there is still no anomaly persistence layer anywhere in
  this repo to source real records from, so there is nothing yet for an API response to render this
  format from.
- **Rendering only, not a new evidence source** — `format_anomaly_report` never computes anything;
  it is entirely downstream of `Anomaly.evidence`/`evidence_values`, so any future gap in the
  detector's own evidence content (e.g. the destination-identity gap above) will render exactly as
  incompletely as it is computed.

## Verification actually performed this phase

- `pytest backend/tests/test_flowmind_anomaly.py -v` — 12/12 passed (2 assertions updated for the
  clean-integer formatting fix; 2 new assertions for the added `current_<label>_count` keys).
- `pytest backend/tests/test_flowmind_anomaly_explain.py -v` — 7/7 passed (new): empty-list and
  mixed-node_id `ValueError`s; a single `DESTINATIONS` anomaly renders clean `Node:`/`Historical
  destinations:`/`Current destinations:`/`Evidence:` lines; a single `PORTS` anomaly names the
  specific new port plus before/after counts; combining a `DESTINATIONS` anomaly and a `PORTS`
  anomaly for one node reproduces the master spec's own worked-example shape in one report;
  deterministic output across repeated calls; a real end-to-end run through
  `build_node_baseline`/`detect_node_anomalies` (not hand-built fixtures) renders with clean integer
  values, confirming the formatting fix against genuinely detector-produced evidence, not just
  hand-constructed `Anomaly` objects.
- Full repo suite (`pytest backend/tests experiments/tests simulator/tests`, run from repo root) —
  **325/325 passed** (up from 318/318), no regressions.
- `python -m scripts.validate_data_contracts` — 38/38 passed, no regression (`Anomaly` schema
  unchanged).
- `python -m scripts.check_ground_truth_boundary` — clean.
- A real, manual end-to-end run (no Docker needed): built a synthetic 10-observation fingerprint
  history for node `API-2` (destinations jittering 3-5, median 4), ran `detect_node_anomalies`
  against a new fingerprint with 9 destinations and a newly observed port `4444`, then rendered the
  result through `format_anomaly_report` — output visually confirmed to match the master spec's
  literal PHASE 41 worked example block (reproduced above under "Worked example").

## Status

Explainable anomalies (spec Phase 41, FR-1.18) is implemented and unit-verified. Evidence formatting
across all 5 currently-producible `AnomalyDimension` values is standardized and matches this
project's own Phase 04 contract example; a new, generic `format_anomaly_report` renders any
`Anomaly` list into the master spec's literal human-readable report shape. No detection logic
changed — `TOPOLOGY` remains deferred to Phase 45 (Phase 40's own scope-out, unaffected by this
phase); specific new-destination identity is an honest, documented limitation, not silently
skipped. No persistence or API wiring exists yet — `/anomalies` stays a 501 stub pending a future
phase that builds an anomaly persistence/query layer.
