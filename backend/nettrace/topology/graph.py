"""Probabilistic topology graph assembly (spec Phase 32, FR-1.11).

Combines Phase 29's `discover_nodes` and Phase 30-31's `discover_edges`
into one complete `TopologyGraph` -- the first phase to actually populate
that Phase 04 data contract with real inferred data. Never imports
`simulator.ground_truth` (`scripts/check_ground_truth_boundary.py`
statically forbids it, spec §4's ground-truth rule); comparing this graph
against ground truth is a separate, evaluation-only concern living in
`experiments/metrics/topology_comparison.py`, never called from here or
from any `backend/` code path. See `docs/architecture/topology_reconstruction.md`.

`graph_id` is a caller-supplied parameter, not derived internally -- kept
pure and testable, same reasoning as `discover_edges` taking `nodes` as a
parameter rather than re-deriving it. `GET /topology`
(`backend/app/api/routes/topology.py`) is the caller that decides the
actual scheme (a constant `capture_id`, not a timestamp or content hash --
see that route's own docstring for the determinism justification).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from backend.app.models.topology import TopologyGraph
from backend.nettrace.topology.discovery import discover_nodes
from backend.nettrace.topology.edges import (
    _DEFAULT_PACKET_SCALE,
    _DEFAULT_SIGNAL_STRENGTH,
    discover_edges,
)


def build_topology_graph(
    root: Path,
    capture_id: str,
    graph_id: str,
    edge_confidence_packet_scale: float = _DEFAULT_PACKET_SCALE,
    edge_confidence_signal_strength: float = _DEFAULT_SIGNAL_STRENGTH,
    as_of: Optional[datetime] = None,
    min_edge_bidirectionality: float = 0.0,
) -> TopologyGraph:
    """Assembles the complete inferred `TopologyGraph` for a capture: every
    node `discover_nodes` finds, every edge `discover_edges` finds between
    them. Returns a graph with empty `nodes`/`edges` (never an error) if
    the capture has no normalized packets/flows yet.

    `as_of` (spec Phase 43, FR-1.20, "represent the network as a
    time-indexed graph G(t)"): when given, both node and edge discovery
    are bounded to evidence observed at or before `as_of`, so this
    function genuinely becomes G(t) rather than only ever reconstructing
    the whole capture's aggregate graph. `generated_at` is still "when
    this computation ran," not `as_of` -- `TopologyGraph` carries no
    "this represents time t" field of its own by design; giving a
    time-bounded graph a stable, versioned identity is `NetworkSnapshot`'s
    job (spec Phase 44), not this one's. `None` (default) reproduces the
    original, whole-capture behavior exactly.

    `min_edge_bidirectionality` (Phase 84 hardening, opt-in): edges need at least this much genuine two-way
    traffic, and nodes left with no edge are dropped (a spoofed source that never converses is not a node).
    `0.0` (default) reproduces the original behavior exactly.
    """
    nodes = discover_nodes(root, capture_id, as_of=as_of)
    edges = discover_edges(
        root,
        capture_id,
        nodes,
        edge_confidence_packet_scale,
        edge_confidence_signal_strength,
        as_of=as_of,
        min_bidirectionality=min_edge_bidirectionality,
    )
    if min_edge_bidirectionality > 0.0:
        connected = {e.source_node_id for e in edges} | {e.target_node_id for e in edges}
        nodes = [n for n in nodes if n.node_id in connected]
    return TopologyGraph(
        graph_id=graph_id,
        generated_at=datetime.now(timezone.utc),
        nodes=nodes,
        edges=edges,
    )
