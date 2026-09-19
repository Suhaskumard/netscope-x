"""Concept drift detection (spec Phase 39, FR-1.16).

Implements exactly the mechanism `docs/architecture/algorithm_selection.md`
§3 already selected: "implemented as an EWMA-updated baseline with a
slower update rate than the anomaly-detection window -- a sustained
deviation that the EWMA baseline eventually absorbs is classified
`concept_drift`; a deviation that reverts before the baseline shifts is
`transient_anomaly`."

`track_feature_drift` runs an incremental EWMA
(`ewma_t = alpha*x_t + (1-alpha)*ewma_{t-1}`), seeded at Phase 38's
robust baseline median, over a caller-supplied sequence of newly observed
values for one feature. Classification is based on the FINAL EWMA's
distance (in baseline MADs) from the original median: a sustained
deviation has time to pull the slow-moving EWMA away from where it
started (`CONCEPT_DRIFT`); a deviation that reverts before the EWMA can
move stays classified `TRANSIENT_ANOMALY`. This captures §3's distinction
using only the EWMA's own slow rate against the ORIGINAL static baseline
-- no separately-defined "anomaly-detection window" rate is needed
(Phase 40, which would define one, doesn't exist yet).

Precondition, stated explicitly rather than silently assumed: this
function is only meaningful when applied to a sequence already known or
suspected to deviate (Phase 40's eventual job to flag). Calling it on
ordinary, non-deviating history returns `TRANSIENT_ANOMALY` vacuously (the
EWMA never moves far) -- an accepted scope limitation, not a bug.

`mad_floor` deliberately lives here, not in Phase 38's `RobustFeatureBaseline`
-- that phase's own doc explicitly left MAD-flooring to "whichever future
phase actually computes a z-score." This is that phase.

Never imports `simulator.ground_truth` (spec §4;
`scripts/check_ground_truth_boundary.py` would reject it if it did).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from backend.app.models.anomaly import AnomalyClass
from backend.app.models.behavior import BehavioralFingerprint
from backend.flowmind.baseline.node_baseline import NodeBehavioralBaseline, RobustFeatureBaseline

@dataclass(frozen=True)
class DriftTrackingResult:
    feature_name: str
    ewma_trace: List[float]
    final_ewma: float
    baseline_median: float
    anomaly_class: AnomalyClass


def track_feature_drift(
    baseline: RobustFeatureBaseline,
    feature_name: str,
    observed_values: List[float],
    alpha: float = 0.05,
    drift_threshold_mads: float = 2.0,
    mad_floor: float = 1e-6,
) -> DriftTrackingResult:
    """Classifies `observed_values` (a sequence of new observations for one
    feature, in time order) against `baseline` as `CONCEPT_DRIFT` or
    `TRANSIENT_ANOMALY`. Raises `ValueError` on empty `observed_values` --
    nothing to classify from no observations, mirroring every other
    "cannot compute from nothing" function already in this project.
    """
    if not observed_values:
        raise ValueError("track_feature_drift requires at least one observed value")

    ewma = baseline.median
    trace: List[float] = []
    for value in observed_values:
        ewma = alpha * value + (1 - alpha) * ewma
        trace.append(ewma)

    effective_mad = max(baseline.mad, mad_floor)
    deviation_in_mads = abs(ewma - baseline.median) / effective_mad
    anomaly_class = (
        AnomalyClass.CONCEPT_DRIFT if deviation_in_mads >= drift_threshold_mads else AnomalyClass.TRANSIENT_ANOMALY
    )

    return DriftTrackingResult(
        feature_name=feature_name,
        ewma_trace=trace,
        final_ewma=ewma,
        baseline_median=baseline.median,
        anomaly_class=anomaly_class,
    )


def track_node_drift(
    baseline: NodeBehavioralBaseline,
    new_fingerprints: List[BehavioralFingerprint],
    alpha: float = 0.05,
    drift_threshold_mads: float = 2.0,
    mad_floor: float = 1e-6,
) -> Dict[str, DriftTrackingResult]:
    """Runs `track_feature_drift` across all 4 continuous
    `NodeBehavioralBaseline` features for `new_fingerprints` (a caller-
    supplied, time-ordered sequence of the SAME node's newly observed
    fingerprints). Raises `ValueError` on empty `new_fingerprints`, or if
    any fingerprint's `node_id`/`window` doesn't match `baseline`'s (a
    real correctness guard, the same spirit as Phase 38's own mixed-
    history guard in `build_node_baseline`).
    """
    if not new_fingerprints:
        raise ValueError("track_node_drift requires at least one new fingerprint")

    for fp in new_fingerprints:
        if fp.node_id != baseline.node_id:
            raise ValueError(
                f"fingerprint node_id {fp.node_id!r} does not match baseline node_id {baseline.node_id!r}"
            )
        if fp.window != baseline.window:
            raise ValueError(
                f"fingerprint window {fp.window!r} does not match baseline window {baseline.window!r}"
            )

    feature_values: Dict[str, List[float]] = {
        "distinct_destinations": [float(fp.distinct_destinations) for fp in new_fingerprints],
        "mean_flow_duration_seconds": [fp.mean_flow_duration_seconds for fp in new_fingerprints],
        "outbound_byte_ratio": [fp.outbound_byte_ratio for fp in new_fingerprints],
        "port_count": [float(len(fp.distinct_ports)) for fp in new_fingerprints],
    }

    return {
        feature_name: track_feature_drift(
            getattr(baseline, feature_name),
            feature_name,
            values,
            alpha,
            drift_threshold_mads,
            mad_floor,
        )
        for feature_name, values in feature_values.items()
    }
