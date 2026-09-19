"""Dependency strength estimation (spec Phase 51, FR-1.26; extended Phase 52, FR-1.27).

FR-1.26 names five signals: frequency, persistence, directionality, temporal relationships, and
traffic characteristics. All five are now real, as of Phase 52 -- Phase 51 originally left
temporal relationships (`DependencyEdge.temporal_precedence_score`) at its schema default `0.0`,
citing `docs/architecture/algorithm_selection.md` section 6's own "spec Phase 52" tag; this module
now calls Phase 52's `estimate_temporal_precedence` (`backend/dependency/temporal_precedence.py`)
and folds its result into both `temporal_precedence_score` and the combined `strength` score.

The five signals all reuse already-built evidence rather than re-deriving it:
- Frequency, persistence: Phase 50's `derive_communication_relationships`
  (`backend/dependency/communication.py`), unmodified.
- Directionality: Phase 30-31's `_bidirectionality(forward_byte_ratio)` (`edges.py`), which measures
  "genuine two-way traffic" (1.0 = balanced) -- the inverse of `DependencyEdge.directionality_score`
  ("1.0 = fully one-way", per its own docstring), so `directionality_score = 1 -
  _bidirectionality(mean_ratio)`.
- Traffic characteristics: `Edge.confidence` (Phase 31) is already a real, evidence-backed
  combination of exactly this signal family (TCP handshake completion, protocol fingerprinting, TLS
  negotiation, five-tuple persistence, bidirectionality) -- reused directly rather than re-derived
  under a new name.
- Temporal relationships (Phase 52): time-lagged cross-correlation of each node's overall
  flow-activity time series, via `estimate_temporal_precedence`.

Combination mirrors Phase 31's `_confidence` noisy-OR formula shape exactly: one primary saturating
term (frequency) at full weight, four secondary signals (persistence, directionality, traffic
characteristics, temporal precedence) each scaled by one shared, uniformly-applied strength
constant -- uniform because no empirical basis yet justifies weighting one signal above another
(that is Phase 68's job).

Known, honest limitation (documented in `docs/architecture/algorithm_selection.md` section 6, not
hidden): a high-frequency, persistent, one-directional but coincidental communication pattern (e.g.
a health-check poller) can still score a falsely high strength -- the expected failure mode RQ5's
Phase 68 evaluation is designed to measure, not eliminate by construction.

Never imports `simulator.ground_truth` (spec §4; `scripts/check_ground_truth_boundary.py` would
reject it if it did).
"""

from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from backend.app.models import DependencyEdge, Flow
from backend.dependency.communication import derive_communication_relationships
from backend.dependency.temporal_precedence import (
    _DEFAULT_BUCKET_SECONDS,
    _DEFAULT_MAX_LAG_BUCKETS,
    estimate_temporal_precedence,
)
from backend.app.models.topology import Node
from backend.nettrace.topology.discovery import discover_nodes
from backend.nettrace.topology.edges import (
    _DEFAULT_PACKET_SCALE,
    _DEFAULT_SIGNAL_STRENGTH,
    _bidirectionality,
    bucket_flows_by_node_pair,
    discover_edges,
)
from experiments.artifacts.io import read_jsonl
from experiments.artifacts.paths import flows_path

_DEFAULT_FREQUENCY_SCALE = 1.0  # mirrors Settings.dependency_frequency_scale's own default
_DEFAULT_PERSISTENCE_SCALE = 60.0  # mirrors Settings.dependency_persistence_scale's own default
_DEFAULT_DEPENDENCY_SIGNAL_STRENGTH = 0.3  # mirrors Settings.dependency_signal_strength's own default


def estimate_dependency_strength(
    root: Path,
    capture_id: str,
    as_of: Optional[datetime] = None,
    edge_confidence_packet_scale: float = _DEFAULT_PACKET_SCALE,
    edge_confidence_signal_strength: float = _DEFAULT_SIGNAL_STRENGTH,
    dependency_frequency_scale: float = _DEFAULT_FREQUENCY_SCALE,
    dependency_persistence_scale: float = _DEFAULT_PERSISTENCE_SCALE,
    dependency_signal_strength: float = _DEFAULT_DEPENDENCY_SIGNAL_STRENGTH,
    dependency_temporal_bucket_seconds: float = _DEFAULT_BUCKET_SECONDS,
    dependency_temporal_max_lag_buckets: int = _DEFAULT_MAX_LAG_BUCKETS,
) -> List[DependencyEdge]:
    """Estimates one `DependencyEdge` per already-inferred `Edge`/`CommunicationRelationship` pair
    between a capture's nodes. `discover_nodes`, `discover_edges`,
    `derive_communication_relationships`, and `bucket_flows_by_node_pair` are all called over the
    identical `(root, capture_id, as_of, edge_confidence_packet_scale,
    edge_confidence_signal_strength)` inputs, so `edges[i]` and `relationships[i]` refer to the same
    node pair in the same order -- both are deterministic functions of the same underlying
    `discover_edges` aggregation, an invariant relied on here rather than re-matched by a separate
    lookup.

    `temporal_precedence_score` (Phase 52) is now genuinely computed via
    `estimate_temporal_precedence` over each pair's own source/target `Node` and the capture's full
    flow list (read once here, reused across every pair -- not re-read per pair).

    Returns `[]` for a missing/empty capture -- every input already does, so this does too, never an
    error.
    """
    nodes = discover_nodes(root, capture_id, as_of=as_of)
    edges = discover_edges(
        root,
        capture_id,
        nodes,
        edge_confidence_packet_scale,
        edge_confidence_signal_strength,
        as_of=as_of,
    )
    relationships = derive_communication_relationships(
        root,
        capture_id,
        as_of,
        edge_confidence_packet_scale,
        edge_confidence_signal_strength,
    )
    buckets = bucket_flows_by_node_pair(root, capture_id, nodes, as_of=as_of)

    flows_file = flows_path(root, capture_id)
    flows: List[Flow] = read_jsonl(flows_file, Flow) if flows_file.is_file() else []
    if as_of is not None:
        flows = [f for f in flows if f.first_seen <= as_of]
    nodes_by_id: Dict[str, Node] = {node.node_id: node for node in nodes}

    dependencies: List[DependencyEdge] = []
    for index, (edge, relationship) in enumerate(zip(edges, relationships)):
        bucket_flows = buckets[(edge.source_node_id, edge.target_node_id)]
        mean_ratio = sum(f.features.forward_byte_ratio for f in bucket_flows) / len(bucket_flows)
        directionality_score = 1 - _bidirectionality(mean_ratio)

        temporal_precedence_score = estimate_temporal_precedence(
            flows,
            nodes_by_id[edge.source_node_id],
            nodes_by_id[edge.target_node_id],
            bucket_seconds=dependency_temporal_bucket_seconds,
            max_lag_buckets=dependency_temporal_max_lag_buckets,
        )

        p_frequency = 1 - math.exp(-relationship.frequency / dependency_frequency_scale)
        p_persistence = 1 - math.exp(-relationship.persistence_seconds / dependency_persistence_scale)

        s = dependency_signal_strength
        survival = 1 - p_frequency
        survival *= 1 - s * p_persistence
        survival *= 1 - s * directionality_score
        survival *= 1 - s * edge.confidence
        survival *= 1 - s * temporal_precedence_score
        strength = 1 - survival

        dependencies.append(
            DependencyEdge(
                dependency_id=f"{capture_id}:dependency:{index}",
                source_node_id=edge.source_node_id,
                target_node_id=edge.target_node_id,
                strength=strength,
                frequency=relationship.frequency,
                persistence_seconds=relationship.persistence_seconds,
                directionality_score=directionality_score,
                temporal_precedence_score=temporal_precedence_score,
            )
        )
    return dependencies
