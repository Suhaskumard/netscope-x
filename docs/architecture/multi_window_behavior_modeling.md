# NETSCOPE-X — Multi-Window Behavior Modeling

Phase 34 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 34 — MULTI-WINDOW BEHAVIOR
MODELING"): "Model behavior over: short, medium, long observation windows." FR-1.12's parenthetical
(`docs/requirements/system_requirements.md`): "...across short/medium/long observation windows
(Phase 34)."

Code: `backend/flowmind/features/windows.py`
(`compute_node_features_for_window`/`compute_node_features_all_windows`). This phase decides how
Phase 33's deliberately window-agnostic `compute_node_behavioral_features`
(`backend/flowmind/features/node_features.py`) gets invoked per window — no new feature math, only
window delimiting and orchestration.

## Explicit non-scope: this is not Phase 35

This phase's output is `Dict[ObservationWindow, NodeBehavioralFeatures]` — three feature vectors, not
three `BehavioralFingerprint` instances. `BehavioralFingerprint` (`backend/app/models/behavior.py`,
Phase 04) additionally needs `node_id`/`window`/`computed_at` identity fields and persistence — that
assembly step is explicitly Phase 35's job (FR-1.13, "per-node behavioral fingerprints... spec Phase
35"), not reached ahead of here, consistent with every phase since 29 staying narrowly scoped to its
own spec-line wording.

## Design decision: no spec-mandated durations or delimiting semantics

Neither the master spec, FR-1.12, any NFR, nor `docs/architecture/algorithm_selection.md` gives
concrete window durations or says how a window should be delimited (trailing vs. calendar-bucket vs.
count-based; anchored on what reference point). `ObservationWindow` is a pure label enum with no
duration field anywhere in its schema. This phase must decide both — the same "self-defined and
justified here" situation prior uncovered phases (26, 29-32) were already in.

### Delimiting semantics: trailing window, anchored on the node's own latest activity

For a node and a window size, take that node's own touching flows (`flows_touching_node`, extracted
from Phase 33's `node_features.py` in this phase — a behavior-preserving refactor, not a new feature),
find the latest `last_seen` among them, and keep only flows within `window_seconds` before that
anchor.

- **Not calendar time**: every existing duration field in this codebase (`udp_session_idle_timeout_seconds`,
  every `*_duration_seconds`) is a relative duration, never a calendar bucket — nothing in this
  simulated lab is anchored to wall-clock calendar time.
- **Anchored per-node, not per-capture**: anchoring on the whole capture's latest activity would let
  one busy, late-active node drag every other (quiet) node's window forward with it, making a quiet
  node's "recent" window reflect activity that happened long after its own last real event.
- **Nested, not partitioned**: because all three windows share the same node-specific anchor and only
  differ in how far back they reach, `long ⊇ medium ⊇ short` by construction — verified directly:
  `test_windows_are_nested_long_superset_of_medium_superset_of_short`. This matches RQ2's own framing
  ("does *more* observation improve accuracy and calibration" — an expanding-window question, not a
  segmentation question).

### Default durations: 10s / 60s / 300s — evidence-graded, not uniformly guessed

No spec text or FR gives numbers. Grounded in what this repo's own captures/tests actually exercise:
- **`short = 10.0s`**: matches `simulator/capture/live.py`'s own default `--duration` and
  `simulator/traffic/generate.py`'s real, verified capture runs (10-12s) — the smallest unit this repo
  has actually exercised end-to-end.
- **`medium = 60.0s`**: matches the scale `simulator/tests/test_patterns.py` already needs for its
  `burst`/`periodic` pattern tests to complete multiple full cycles.
- **`long = 300.0s` (5 minutes)**: has **no direct supporting evidence** anywhere in this repo — every
  capture/test found runs under a minute. This is an explicit extrapolation (5x `medium`), documented
  as provisional pending real multi-minute lab data, using the same "provisional default pending real
  calibration" framing already established for `edge_confidence_packet_scale`/
  `edge_confidence_signal_strength` (Phase 30-31).

All three are `Settings` fields (`backend/app/core/config.py`:
`behavior_window_{short,medium,long}_seconds`, `NETSCOPE_`-prefixed-overridable, per NFR-4), guarded
by a `model_validator` requiring strictly increasing order — misconfiguring this would silently break
the nesting property the whole design (and RQ2's comparison) depends on.

## Algorithm

`compute_node_features_for_window(flows, node, window, window_seconds=None)`:
1. Resolve `window`'s duration (from the supplied override dict, or `DEFAULT_WINDOW_SECONDS`).
2. Filter `flows` to those touching `node` (`flows_touching_node`).
3. If none, delegate directly to `compute_node_behavioral_features([], node)` — the same honest
   all-zero result Phase 33 already defines for "no evidence."
4. Otherwise, anchor on `max(last_seen)` among touching flows, keep only those with
   `last_seen > anchor - window_duration`, and delegate to `compute_node_behavioral_features`.

`compute_node_features_all_windows(flows, node, window_seconds=None)` calls the above once per
`ObservationWindow` member, returning all three results.

**Complexity**: O(F) per window for F touching flows (filter + max + filter), so O(3F) = O(F) total
for all three windows — dominated by the flow scan, same shape as every prior FLOWMIND/topology
function.

## Failure cases

A node with no touching flows at all: honest all-zero features for every window, never an error. A
node with touching flows but none within a given window's trailing duration: the same honest all-zero
result for that window only — other windows are computed independently and may still have real data.

## Known limitations

- **`long`'s duration is unvalidated against any real multi-minute capture** — flagged explicitly
  above, not silently assumed accurate.
- **No `BehavioralFingerprint` assembly or persistence** — explicitly Phase 35's job.
- Inherits Phase 29's "one IP → one Node" simplification and Phase 33's destination-only
  `distinct_ports`/outbound-only `distinct_destinations` conventions unchanged.

## Verification actually performed this phase

- `pytest backend/tests/test_flowmind_windows.py -v` — **8/8 passed**: a trailing short window
  correctly excludes an older flow; the anchor is confirmed to be the node's own latest activity, not
  unrelated later traffic elsewhere in the same flow list; the three windows are confirmed strictly
  nested (1/2/3 distinct destinations as the window widens over a hand-constructed timestamp spread);
  `compute_node_features_all_windows` returns exactly the three `ObservationWindow` keys; a node with
  no touching flows returns honest zeros for all three windows; a custom `window_seconds` override
  changes the windowing (1 vs. 2 destinations for the same flow set); `DEFAULT_WINDOW_SECONDS` matches
  the `Settings` defaults exactly; a real end-to-end run through `reconstruct_flows`/`discover_nodes`
  with a second flow deliberately placed 45s after the first, confirming it's excluded from the short
  window but included in medium/long.
- `pytest backend/tests/test_flowmind_node_features.py -v` — **9/9 passed**, confirming the
  `flows_touching_node` extraction didn't change Phase 33's established behavior.
- Full repo suite (`pytest`, run from repo root) — **265/265 passed** (up from 257/257), no
  regressions.
- `python -m scripts.validate_data_contracts` — 38/38 passed, no regression (no Pydantic schema
  changed).
- `python -m scripts.check_ground_truth_boundary` — clean.
- Manually confirmed `Settings()` loads with the real defaults (`10.0, 60.0, 300.0`) and the new
  ordering validator doesn't reject them.

## Status

Multi-window behavior modeling (spec Phase 34, FR-1.12) is implemented and unit-verified: real,
evidence-graded window boundaries, a defensible nested-trailing-window delimiting design, and a
working per-window/all-windows computation built directly on Phase 33's feature function with no
duplicated logic. It produces no `BehavioralFingerprint` and persists nothing — both remain Phase 35's
job.
