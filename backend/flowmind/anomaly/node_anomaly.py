"""Multi-dimensional anomaly detection (spec Phase 40, FR-1.17).

Decides WHETHER a node's observed behavior deviates enough from Phase
38's `NodeBehavioralBaseline` to flag as an anomaly -- the decision Phase
39's `track_feature_drift`/`track_node_drift` explicitly left undecided
("classifies a *given* deviating sequence... does not itself decide
*whether* a sequence deviates enough to flag in the first place").

Two mechanisms, both exactly what `docs/architecture/algorithm_selection.md`
§3 already selected:
  - Continuous z-score deviation (DESTINATIONS, TIMING, BEHAVIOR,
    TRAFFIC_VOLUME): a robust z-score against the matching
    `RobustFeatureBaseline`, flagged when `|z| >= z_threshold`.
  - Set-difference novelty (PORTS, PROTOCOLS): flagged when the current
    fingerprint has a port/protocol absent from the baseline's historical
    set -- "explicit set-difference novelty checks (new destination/port
    not in historical set)."

`AnomalyDimension.TOPOLOGY` is never produced here -- time-series
graph-diffing (comparing a topology at T1 vs T2) is explicitly Phase 45's
job (`GraphChangeEvent`/`NetworkSnapshot`, Phase 04 schemas already
reserved but unimplemented); building a shadow diff engine here would
duplicate/pre-empt that phase. A documented, honest scope-out, not a
silent gap -- see `docs/architecture/multidimensional_anomaly_detection.md`.

Cold-start: both entry points return `[]` immediately if
`baseline.is_sufficient` is `False` -- an unreliable, barely-estimated
baseline should never produce a confident-looking anomaly, reusing Phase
38's own flag for exactly the purpose it was built for.

`detect_node_anomalies` (single new fingerprint) always assigns
`AnomalyClass.TRANSIENT_ANOMALY` -- a documented, provisional label: one
observation cannot itself establish drift (Phase 39's mechanism needs a
*sequence*). `detect_node_anomalies_with_drift` (a caller-supplied
sequence of new fingerprints) upgrades this to a real classification by
handing each continuous-feature anomaly to Phase 39's
`track_feature_drift` over the full sequence.

Never imports `simulator.ground_truth` (spec §4;
`scripts/check_ground_truth_boundary.py` would reject it if it did).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Optional

from backend.app.models.anomaly import Anomaly, AnomalyClass, AnomalyDimension
from backend.app.models.behavior import BehavioralFingerprint
from backend.flowmind.baseline.node_baseline import NodeBehavioralBaseline, RobustFeatureBaseline
from backend.flowmind.drift.node_drift import track_feature_drift

# Continuous feature name -> (AnomalyDimension, human-readable evidence label).
# port_count has no dimension here -- PORTS is covered by the novelty check
# below, not a magnitude check, to avoid double-detecting the same signal.
_CONTINUOUS_DIMENSIONS: Dict[str, AnomalyDimension] = {
    "distinct_destinations": AnomalyDimension.DESTINATIONS,
    "mean_flow_duration_seconds": AnomalyDimension.TIMING,
    "outbound_byte_ratio": AnomalyDimension.BEHAVIOR,
    "total_byte_count": AnomalyDimension.TRAFFIC_VOLUME,
}
_DIMENSION_TO_FEATURE: Dict[AnomalyDimension, str] = {v: k for k, v in _CONTINUOUS_DIMENSIONS.items()}
_FEATURE_LABELS: Dict[str, str] = {
    "distinct_destinations": "destinations",
    "mean_flow_duration_seconds": "duration_seconds",
    "outbound_byte_ratio": "outbound_byte_ratio",
    "total_byte_count": "byte_count",
}


def _feature_value(fingerprint: BehavioralFingerprint, feature_name: str) -> float:
    return float(getattr(fingerprint, feature_name))


def _format_value(value: float) -> str:
    """Renders a whole-numbered float as a clean integer string (`"4"`, not
    `"4.000"`) and a genuinely fractional value to 3 decimals -- matching
    the evidence_values convention Phase 04 itself already established
    (`scripts/validate_data_contracts.py`'s `"historical_destinations": "4"`
    example), which Phase 40's original `.3f`-everywhere formatting had
    drifted from (spec Phase 41, FR-1.18)."""
    if value == int(value):
        return str(int(value))
    return f"{value:.3f}"


@dataclass(frozen=True)
class _Candidate:
    dimension: AnomalyDimension
    evidence: List[str]
    evidence_values: Dict[str, str]
    score: float


def _continuous_candidate(
    dimension: AnomalyDimension,
    label: str,
    baseline_feature: RobustFeatureBaseline,
    current_value: float,
    z_threshold: float,
    mad_floor: float,
) -> Optional[_Candidate]:
    effective_mad = max(baseline_feature.mad, mad_floor)
    z = (current_value - baseline_feature.median) / effective_mad
    if abs(z) < z_threshold:
        return None

    score = 1 - math.exp(-abs(z) / z_threshold)
    historical_str = _format_value(baseline_feature.median)
    current_str = _format_value(current_value)
    return _Candidate(
        dimension=dimension,
        evidence=[
            f"{label} moved from a historical typical value of {historical_str} to {current_str} "
            f"(robust z-score {z:.3f}, threshold {z_threshold:.3f})"
        ],
        evidence_values={
            f"historical_{label}": historical_str,
            f"current_{label}": current_str,
            "z_score": f"{z:.3f}",
        },
        score=score,
    )


def _novelty_candidate(
    dimension: AnomalyDimension,
    label: str,
    current_values,
    historical_values: FrozenSet,
    novelty_scale: float,
) -> Optional[_Candidate]:
    new_items = sorted(set(current_values) - historical_values, key=str)
    if not new_items:
        return None

    new_items_str = ", ".join(str(item) for item in new_items)
    score = 1 - math.exp(-len(new_items) / novelty_scale)
    return _Candidate(
        dimension=dimension,
        evidence=[f"new {label}(s) observed, not present in the historical set: {new_items_str}"],
        evidence_values={
            f"new_{label}s": new_items_str,
            f"historical_{label}_count": str(len(historical_values)),
            f"current_{label}_count": str(len(set(current_values))),
        },
        score=score,
    )


def _check_fingerprint_matches_baseline(baseline: NodeBehavioralBaseline, fp: BehavioralFingerprint) -> None:
    if fp.node_id != baseline.node_id:
        raise ValueError(f"fingerprint node_id {fp.node_id!r} does not match baseline node_id {baseline.node_id!r}")
    if fp.window != baseline.window:
        raise ValueError(f"fingerprint window {fp.window!r} does not match baseline window {baseline.window!r}")


def _detect_candidates(
    baseline: NodeBehavioralBaseline,
    fingerprint: BehavioralFingerprint,
    z_threshold: float,
    novelty_scale: float,
    mad_floor: float,
) -> List[_Candidate]:
    candidates: List[_Candidate] = []

    for feature_name, dimension in _CONTINUOUS_DIMENSIONS.items():
        baseline_feature: RobustFeatureBaseline = getattr(baseline, feature_name)
        current_value = _feature_value(fingerprint, feature_name)
        candidate = _continuous_candidate(
            dimension, _FEATURE_LABELS[feature_name], baseline_feature, current_value, z_threshold, mad_floor
        )
        if candidate is not None:
            candidates.append(candidate)

    port_candidate = _novelty_candidate(
        AnomalyDimension.PORTS, "port", fingerprint.distinct_ports, baseline.historical_ports, novelty_scale
    )
    if port_candidate is not None:
        candidates.append(port_candidate)

    protocol_candidate = _novelty_candidate(
        AnomalyDimension.PROTOCOLS,
        "protocol",
        fingerprint.distinct_protocols,
        baseline.historical_protocols,
        novelty_scale,
    )
    if protocol_candidate is not None:
        candidates.append(protocol_candidate)

    return candidates


def detect_node_anomalies(
    baseline: NodeBehavioralBaseline,
    fingerprint: BehavioralFingerprint,
    z_threshold: float = 3.0,
    novelty_scale: float = 1.0,
    mad_floor: float = 1e-6,
) -> List[Anomaly]:
    """Detects deviations in `fingerprint` against `baseline`. Returns `[]`
    if the baseline is cold-start-insufficient. Every emitted `Anomaly` gets
    the provisional `AnomalyClass.TRANSIENT_ANOMALY` label -- a single
    observation cannot itself establish drift; use
    `detect_node_anomalies_with_drift` with a sequence for a real
    classification.
    """
    _check_fingerprint_matches_baseline(baseline, fingerprint)
    if not baseline.is_sufficient:
        return []

    candidates = _detect_candidates(baseline, fingerprint, z_threshold, novelty_scale, mad_floor)

    return [
        Anomaly(
            node_id=fingerprint.node_id,
            anomaly_id=f"{fingerprint.node_id}:{c.dimension.value}:{fingerprint.computed_at.isoformat()}",
            detected_at=fingerprint.computed_at,
            dimension=c.dimension,
            anomaly_class=AnomalyClass.TRANSIENT_ANOMALY,
            evidence=c.evidence,
            evidence_values=c.evidence_values,
            score=c.score,
        )
        for c in candidates
    ]


def detect_node_anomalies_with_drift(
    baseline: NodeBehavioralBaseline,
    new_fingerprints: List[BehavioralFingerprint],
    z_threshold: float = 3.0,
    novelty_scale: float = 1.0,
    drift_threshold_mads: float = 2.0,
    alpha: float = 0.05,
    mad_floor: float = 1e-6,
) -> List[Anomaly]:
    """Detects deviations against the LAST fingerprint in `new_fingerprints`
    (a caller-supplied, time-ordered sequence of the same node's newly
    observed fingerprints), then upgrades any continuous-feature anomaly's
    `anomaly_class` to a real transient-vs-drift classification via Phase
    39's `track_feature_drift` over the full sequence. Raises `ValueError`
    on empty `new_fingerprints`, or if any fingerprint's `node_id`/`window`
    doesn't match `baseline`'s.
    """
    if not new_fingerprints:
        raise ValueError("detect_node_anomalies_with_drift requires at least one new fingerprint")
    for fp in new_fingerprints:
        _check_fingerprint_matches_baseline(baseline, fp)

    if not baseline.is_sufficient:
        return []

    last = new_fingerprints[-1]
    anomalies = detect_node_anomalies(baseline, last, z_threshold, novelty_scale, mad_floor)

    upgraded: List[Anomaly] = []
    for anomaly in anomalies:
        feature_name = _DIMENSION_TO_FEATURE.get(anomaly.dimension)
        if feature_name is None:
            upgraded.append(anomaly)  # PORTS/PROTOCOLS novelty has no drift analogue
            continue
        observed_values = [_feature_value(fp, feature_name) for fp in new_fingerprints]
        drift_result = track_feature_drift(
            getattr(baseline, feature_name), feature_name, observed_values, alpha, drift_threshold_mads, mad_floor
        )
        upgraded.append(anomaly.model_copy(update={"anomaly_class": drift_result.anomaly_class}))

    return upgraded
