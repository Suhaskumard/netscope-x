"""Behavioral baseline: a normal-behavior model from historical observations
(spec Phase 38, FR-1.15).

Implements exactly the mechanism `docs/architecture/algorithm_selection.md`
§3 already selected for anomaly detection: "(a) Per-dimension statistical
baseline... using a robust (median/MAD-based, outlier-resistant) rather
than mean/std baseline to avoid the baseline itself being skewed by prior
anomalies," plus "explicit set-difference novelty checks (new
destination/port not in historical set)." The EWMA-based mechanism §3 also
names is tied specifically to distinguishing transient anomaly from
concept drift -- that decision logic is Phase 39's job (FR-1.16), not
built here. This module only maintains the baseline itself.

`build_node_baseline` is a pure function over a caller-supplied,
already-ordered `List[BehavioralFingerprint]` -- no historical-fingerprint
store exists anywhere in this repo yet (Phase 35's `fingerprints.jsonl` is
a single-capture snapshot, not a time series), and inventing one is out of
this phase's literal scope ("maintain a baseline," not "build a
fingerprint history store"). Matches every prior FLOWMIND function's
"pure function over caller-supplied data" convention.

Never imports `simulator.ground_truth` (spec §4;
`scripts/check_ground_truth_boundary.py` would reject it if it did).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import FrozenSet, List

from backend.app.models.behavior import BehavioralFingerprint, ObservationWindow


@dataclass(frozen=True)
class RobustFeatureBaseline:
    """A robust (median/MAD) baseline for one continuous feature. `mad`
    (median absolute deviation) is reported honestly, un-floored: it can
    legitimately be `0.0` when historical values are identical or there
    are too few of them -- a documented fact of the statistic, not a bug.
    Whether/how a future consumer floors it against division-by-zero (e.g.
    computing a z-score) is that consumer's own choice to make and
    document, not baked in here."""

    median: float
    mad: float


@dataclass(frozen=True)
class NodeBehavioralBaseline:
    """One node's normal-behavior model over a given observation window,
    built from its historical `BehavioralFingerprint`s (spec Phase 38)."""

    node_id: str
    window: ObservationWindow
    observation_count: int
    is_sufficient: bool

    distinct_destinations: RobustFeatureBaseline
    mean_flow_duration_seconds: RobustFeatureBaseline
    outbound_byte_ratio: RobustFeatureBaseline
    port_count: RobustFeatureBaseline
    total_byte_count: RobustFeatureBaseline

    historical_ports: FrozenSet[int]
    historical_protocols: FrozenSet[str]
    persistent_talker_frequency: float


def _robust_baseline(values: List[float]) -> RobustFeatureBaseline:
    median = statistics.median(values)
    mad = statistics.median(abs(v - median) for v in values)
    return RobustFeatureBaseline(median=median, mad=mad)


def build_node_baseline(
    fingerprint_history: List[BehavioralFingerprint],
    min_observations: int = 5,
) -> NodeBehavioralBaseline:
    """Builds `fingerprint_history`'s node's behavioral baseline. Raises
    `ValueError` on empty input (a baseline cannot be built from nothing,
    mirroring `fit_role_model`/`fit_temperature`'s stance on fitting from
    nothing), or if the history mixes more than one `node_id` or `window`
    (a baseline is inherently node+window scoped).

    `min_observations` sets the cold-start threshold `algorithm_selection.md`
    §3 flags qualitatively ("minimum baseline observation period") without
    giving a number -- 5 is a provisional, evidence-light default (below
    that, MAD is degenerate or wildly unstable), the same honesty standard
    applied to every other undocumented numeric constant in this project.
    """
    if not fingerprint_history:
        raise ValueError("build_node_baseline requires at least one historical fingerprint")

    node_ids = {fp.node_id for fp in fingerprint_history}
    if len(node_ids) > 1:
        raise ValueError(f"fingerprint_history must all share one node_id, got {node_ids}")

    windows = {fp.window for fp in fingerprint_history}
    if len(windows) > 1:
        raise ValueError(f"fingerprint_history must all share one observation window, got {windows}")

    observation_count = len(fingerprint_history)

    historical_ports: FrozenSet[int] = frozenset(
        port for fp in fingerprint_history for port in fp.distinct_ports
    )
    historical_protocols: FrozenSet[str] = frozenset(
        protocol for fp in fingerprint_history for protocol in fp.distinct_protocols
    )
    persistent_talker_frequency = sum(
        1 for fp in fingerprint_history if fp.is_persistent_talker
    ) / observation_count

    return NodeBehavioralBaseline(
        node_id=fingerprint_history[0].node_id,
        window=fingerprint_history[0].window,
        observation_count=observation_count,
        is_sufficient=observation_count >= min_observations,
        distinct_destinations=_robust_baseline(
            [float(fp.distinct_destinations) for fp in fingerprint_history]
        ),
        mean_flow_duration_seconds=_robust_baseline(
            [fp.mean_flow_duration_seconds for fp in fingerprint_history]
        ),
        outbound_byte_ratio=_robust_baseline([fp.outbound_byte_ratio for fp in fingerprint_history]),
        port_count=_robust_baseline([float(len(fp.distinct_ports)) for fp in fingerprint_history]),
        total_byte_count=_robust_baseline([float(fp.total_byte_count) for fp in fingerprint_history]),
        historical_ports=historical_ports,
        historical_protocols=historical_protocols,
        persistent_talker_frequency=persistent_talker_frequency,
    )


def build_anchored_baseline(
    fingerprint_history: List[BehavioralFingerprint],
    anchor_count: int = 5,
    min_observations: int = 5,
) -> NodeBehavioralBaseline:
    """Phase 84 hardening against slow baseline poisoning: builds the baseline from only the OLDEST
    `anchor_count` fingerprints, which a campaign that ramps behavior up during the history window has not yet
    reached. Trades adaptation for resistance -- a legitimate change that happened inside the anchored span is
    baked in, and an attacker who poisons from the very first observation defeats it. Opt-in; nothing calls it
    unless a caller chooses it over `build_node_baseline`."""
    return build_node_baseline(fingerprint_history[:anchor_count], min_observations=min_observations)
