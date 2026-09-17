"""Shared metric-result data contract.

Serves FR-1.39-1.40 and the Phase 68 evaluation matrix (topology, role
inference, anomaly detection, temporal, causal, PathForge, counterfactual).
One shared schema so every evaluation context reports results the same way.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class MetricContext(str, Enum):
    TOPOLOGY_RECONSTRUCTION = "topology_reconstruction"
    ROLE_INFERENCE = "role_inference"
    ANOMALY_DETECTION = "anomaly_detection"
    TEMPORAL_ANALYSIS = "temporal_analysis"
    CAUSAL_ANALYSIS = "causal_analysis"
    PATHFORGE = "pathforge"
    COUNTERFACTUAL = "counterfactual"


class MetricResult(BaseModel):
    """A single evaluation metric produced by an actual experiment run.

    `experiment_id` is required: a metric with no experiment behind it is,
    by spec Rule 2 / §21, not a legitimate metric.
    """

    metric_id: str
    experiment_id: str
    context: MetricContext
    computed_at: datetime

    precision: Optional[float] = Field(default=None, ge=0, le=1)
    recall: Optional[float] = Field(default=None, ge=0, le=1)
    f1: Optional[float] = Field(default=None, ge=0, le=1)
    false_positive_rate: Optional[float] = Field(default=None, ge=0, le=1)
    false_negative_rate: Optional[float] = Field(default=None, ge=0, le=1)
    detection_latency_seconds: Optional[float] = Field(default=None, ge=0)
    graph_similarity: Optional[float] = Field(default=None, ge=0, le=1)
    calibration_error: Optional[float] = Field(default=None, ge=0)
