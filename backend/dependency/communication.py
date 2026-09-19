"""Communication relationship derivation (spec Phase 50, FR-1.25, RQ5).

`CommunicationRelationship` (`backend/app/models/dependency.py`, Phase 04) already declares its own
scope: "Observed communication between two nodes -- carries no dependency claim." This module is
the first real computation of it: pure aggregation over already-inferred topology edges, no new
inference, no strength/directionality/temporal-precedence scoring attached anywhere -- that is
structurally impossible here since `CommunicationRelationship` has no such fields, and is Phase
51/52-53's job once `CommunicationRelationship` exists for them to score.

Candidate pairs are exactly `discover_edges`'s own already-inferred topology edges
(`backend/nettrace/topology/edges.py`), per `docs/architecture/algorithm_selection.md` section 6's
committed design ("candidate pairs are pruned first by the (already-inferred) topology edges"),
not a fresh O(V^2) scan over every possible node pair.

Never imports `simulator.ground_truth` (spec §4; `scripts/check_ground_truth_boundary.py` would
reject it if it did).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List, Optional

from backend.app.models import CommunicationRelationship
from backend.nettrace.topology.discovery import discover_nodes
from backend.nettrace.topology.edges import _DEFAULT_PACKET_SCALE, _DEFAULT_SIGNAL_STRENGTH, discover_edges


def derive_communication_relationships(
    root: Path,
    capture_id: str,
    as_of: Optional[datetime] = None,
    edge_confidence_packet_scale: float = _DEFAULT_PACKET_SCALE,
    edge_confidence_signal_strength: float = _DEFAULT_SIGNAL_STRENGTH,
) -> List[CommunicationRelationship]:
    """Derives one `CommunicationRelationship` per already-inferred `Edge` (Phase 30-31) between a
    capture's nodes (Phase 29): `discover_nodes` then `discover_edges`, both reused unmodified, the
    same "combine, don't reinvent" pattern `build_topology_graph` (Phase 32) already uses.

    `persistence_seconds` is `edge.last_observed - edge.first_observed`, in seconds.
    `frequency` is `edge.observation_count / persistence_seconds` (observations/sec) -- except when
    `persistence_seconds` is exactly `0` (every contributing flow shares the same `first_seen` ==
    `last_seen` instant, e.g. a single zero-duration flow): a rate is not meaningful over a
    zero-length window, so this falls back to the raw `observation_count` rather than dividing by
    zero or fabricating an unbounded rate -- an honest, documented edge case, the same style as
    Phase 45's own "removals practically vacuous under normal usage" note, not silently assumed
    away.

    `as_of` (spec Phase 43, FR-1.20) is passed straight through to both `discover_nodes` and
    `discover_edges`, so a bounded query stays evidence-consistent the same way `build_topology_graph`
    already guarantees.

    Returns `[]` for a missing/empty capture -- `discover_nodes`/`discover_edges` already do, so
    this function does too, never an error.
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

    relationships: List[CommunicationRelationship] = []
    for edge in edges:
        persistence_seconds = (edge.last_observed - edge.first_observed).total_seconds()
        frequency = (
            edge.observation_count / persistence_seconds
            if persistence_seconds > 0
            else float(edge.observation_count)
        )
        relationships.append(
            CommunicationRelationship(
                source_node_id=edge.source_node_id,
                target_node_id=edge.target_node_id,
                frequency=frequency,
                persistence_seconds=persistence_seconds,
            )
        )
    return relationships
