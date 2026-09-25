"""The constants flagged "provisional, pending Phase 68" and their calibration search space (spec Phase 82).

`CalibrationConstants` defaults mirror `backend.app.core.config.Settings` (a test asserts they stay equal), so
`CalibrationConstants()` reproduces the pre-Phase-82 pipeline exactly.

Not calibratable against the matrix, stated rather than hidden: `path_engine._DEFAULT_LATENCY_COST_SCALE`
only enters an edge weight for a `LATENCY_INJECTION` scenario, and the matrix's PathForge/counterfactual
contexts only inject `NODE_FAILURE`, so no matrix metric can move with it (`test_constant_calibration.py`
checks the weight is unchanged). Out of scope: behavior windows and node_baseline's minimum-history count
(no ground truth to score them against), and the sequence-model floors (Phase 78).
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Dict, Tuple

from backend.app.models.metric import MetricContext
from experiments.calibration.bayes_opt import Dimension


@dataclass(frozen=True)
class CalibrationConstants:
    edge_confidence_packet_scale: float = 20.0
    edge_confidence_signal_strength: float = 0.3
    dependency_frequency_scale: float = 1.0
    dependency_persistence_scale: float = 60.0
    dependency_signal_strength: float = 0.3
    dependency_temporal_bucket_seconds: float = 10.0
    dependency_temporal_max_lag_buckets: int = 5
    causal_candidate_strength_threshold: float = 0.5

    def as_dict(self) -> Dict[str, float]:
        return {f.name: getattr(self, f.name) for f in fields(self)}


SPACE: Dict[str, Dimension] = {
    "edge_confidence_packet_scale": Dimension("edge_confidence_packet_scale", 1.0, 200.0, log=True),
    "edge_confidence_signal_strength": Dimension("edge_confidence_signal_strength", 0.05, 0.9),
    "dependency_frequency_scale": Dimension("dependency_frequency_scale", 0.1, 20.0, log=True),
    "dependency_persistence_scale": Dimension("dependency_persistence_scale", 5.0, 600.0, log=True),
    "dependency_signal_strength": Dimension("dependency_signal_strength", 0.05, 0.9),
    "dependency_temporal_bucket_seconds": Dimension("dependency_temporal_bucket_seconds", 2.0, 30.0, log=True),
    "dependency_temporal_max_lag_buckets": Dimension("dependency_temporal_max_lag_buckets", 1, 10, integer=True),
    "causal_candidate_strength_threshold": Dimension("causal_candidate_strength_threshold", 0.1, 0.9),
}


@dataclass(frozen=True)
class Group:
    """Constants tuned together against one stage objective. `guards` are the other stages' objectives, which
    must not regress beyond their own seed spread for the group's new values to be adopted."""

    name: str
    constants: Tuple[str, ...]
    objective: MetricContext
    guards: Tuple[MetricContext, ...]


# Run in this order; each group is tuned on top of the values adopted so far.
GROUPS: Tuple[Group, ...] = (
    Group("topology", ("edge_confidence_packet_scale", "edge_confidence_signal_strength"),
          MetricContext.TOPOLOGY_RECONSTRUCTION, (MetricContext.CAUSAL_ANALYSIS, MetricContext.TEMPORAL_ANALYSIS)),
    Group("temporal", ("dependency_temporal_bucket_seconds", "dependency_temporal_max_lag_buckets"),
          MetricContext.CAUSAL_ANALYSIS, (MetricContext.TOPOLOGY_RECONSTRUCTION, MetricContext.TEMPORAL_ANALYSIS)),
    Group("causal_strength",
          ("dependency_frequency_scale", "dependency_persistence_scale", "dependency_signal_strength",
           "causal_candidate_strength_threshold"),
          MetricContext.CAUSAL_ANALYSIS, (MetricContext.TOPOLOGY_RECONSTRUCTION, MetricContext.TEMPORAL_ANALYSIS)),
)
