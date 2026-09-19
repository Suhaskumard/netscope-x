"""Concept drift detection: distinguish transient anomaly from persistent
behavioral evolution (spec Phase 39, FR-1.16).

Implements the EWMA-based mechanism `docs/architecture/algorithm_selection.md`
§3 already selected, consuming Phase 38's `NodeBehavioralBaseline`. Does
NOT decide whether a sequence is anomalous in the first place -- that
detection/thresholding decision is Phase 40's job. See
`docs/architecture/concept_drift_detection.md`.
"""
