"""Multi-dimensional anomaly detection (spec Phase 40, FR-1.17).

Decides WHETHER a node's observed behavior deviates enough from Phase
38's baseline to flag, across 5 of the 7 `AnomalyDimension` values
(`TOPOLOGY` is explicitly deferred to Phase 45's graph-diff machinery;
see `docs/architecture/multidimensional_anomaly_detection.md`). Hands any
flagged continuous-feature deviation to Phase 39's `track_feature_drift`
to classify as transient or drift when a sequence is available.
"""
