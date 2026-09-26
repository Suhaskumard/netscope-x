# Explainable Causal Attribution (Phase 99)

`GET /api/v1/causal/{dependency_id}/attribution?capture_id=` (`backend/dependency/attribution.py`) and the
"Causal attribution" view (`frontend/src/Attribution.tsx`, `?view=attribution&capture=<id>`) show what drives a dependency's
strength score behind its Phase 56 evidence report.

## Definition
`combine_dependency_strength` is a five-signal noisy-OR: strength = 1 - Π(1 - tᵢ), tᵢ = frequency `1-exp(-f/scale)` and
`s·(persistence, directionality, traffic characteristics = the pair's Phase 31 edge confidence, temporal precedence)`, s = 0.3.
The spec lists four signals; the fifth (edge confidence) genuinely feeds the score, so it is shown rather than hidden. A
noisy-OR is not additive, so each signal's **contribution is its exact Shapley value** of v(S) = 1 - Π_{i∈S}(1 - tᵢ): the
average marginal gain over every order the signals can be added (32 subsets, no sampling). It is efficient (contributions sum
exactly to the strength), order independent, and 0 for a zero signal. The table also shows each signal's standalone
probability and the strength with that signal removed (drop-one, which does not sum). No second scoring formula exists:
the terms mirror `combine_dependency_strength` and `strength_from_terms` is checked against it. The API reports `residual`
(strength - Σ contributions, ~1e-16). The edge confidence is read from `discover_edges` (dependency i <-> edge i, as in
`estimate_dependency_strength`).

## Verified
- 6 tests: Σ contributions = strength to 1e-12 over 300 random inputs incl. saturating/zero signals; Shapley equals the
  average over all 120 orderings; equals `combine_dependency_strength`; drop-one equals recomputation; on a real capture the
  route's strength equals `GET /dependencies`, `traffic_characteristics.raw` equals the real `discover_edges` confidence, and
  the capture has dependencies with temporal precedence > 0; 404 and tenant isolation.
- **Real Chrome** (`scripts/verify_attribution_in_chrome.mjs`, CDP, headless): seeded a real pcap (Phase 70 lagged traffic over
  the `large` topology, 31,234 packets), selected each of the 11 listed dependencies (3 with temporal precedence > 0.5) and read
  the rendered DOM. References came from `scripts/attribution_expected.py`, which rewrites the formula and computes Shapley as
  the average over all 120 orderings, independent of `attribution.py`. For 11/11: displayed contributions sum to the displayed
  strength (within 4-dp rounding), the displayed strength equals the independent strength, every displayed contribution equals
  the independent Shapley value, the page's own in-browser consistency badge says consistent, no console errors.
  Example (0 -> 5, strength 0.9048): frequency 0.4751, persistence 0.1501, directionality 0.0007, traffic 0.1501, temporal 0.1288.

## Limits
Attribution explains the SCORE, not causation (the report's limitations say so and are shown). In these captures frequency
saturates and dominates (0.30-0.69 of strengths ~0.75-0.97), so the score is not very discriminating between dependencies. The
uniform signal weight s = 0.3 is uncalibrated. Verified on one 11-dependency capture in headless Chrome on Windows; the
recomputation on each request is slow on large captures (the route reruns dependency estimation, as `/causal` does).
