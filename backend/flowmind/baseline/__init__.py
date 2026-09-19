"""Behavioral baseline: a normal-behavior model from historical observations
(spec Phase 38, FR-1.15).

Implements the median/MAD-based robust baseline plus historical-set
novelty tracking that `docs/architecture/algorithm_selection.md` §3
already selected for anomaly detection. The EWMA-based transient-vs-drift
decision logic §3 also names is a separate, later concern (Phase 39,
FR-1.16) -- not built here. See
`docs/architecture/behavioral_baseline.md`.
"""
