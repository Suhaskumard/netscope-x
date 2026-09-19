"""Graph Difference Engine (spec Phase 45, FR-1.21's second half: "compute
structural diffs between [snapshots] (node/edge additions/removals,
attribute changes)").

The first real use of `backend/app/models/snapshot.py`'s `GraphChangeEvent`
(Phase 04) -- its `change_type` enum (`NODE_ADDED`/`NODE_REMOVED`/
`EDGE_ADDED`/`EDGE_REMOVED`/`ATTRIBUTE_CHANGED`) is the master spec's own
bullet list verbatim.

Relies on a property of Phase 43/44's own construction, not assumed but
verified directly by this phase's own tests: `Node.node_id`/`Edge.edge_id`
are deterministic index-based ids, assigned by sorting on `first_observed`
(nodes) / `(first_observed, source_node_id, target_node_id)` (edges).
Because `as_of` filtering (Phase 43) only ever *adds* more evidence as
`as_of` increases -- a strict superset relationship -- an already-included
node/edge's `first_observed` never changes as later evidence is added, so
its relative order (and therefore its id) is preserved exactly at any
later `as_of` for the same `capture_id`. Two snapshots of the same capture
can therefore be diffed by plain `node_id`/`edge_id` set comparison -- no
separate "same real-world entity" matching problem to solve, unlike Phase
32's ground-truth comparison (which had to match via IP sets because the
two sides' id schemes were independently generated).

A pure computation over two already-persisted snapshots -- no new
persistence, no API wiring (mirrors Phase 41's `format_anomaly_report` and
Phase 42's `evaluate_anomaly_detection`). Never imports
`simulator.ground_truth` (spec §4).
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from backend.app.models.snapshot import ChangeType, GraphChangeEvent, NetworkSnapshot
from backend.app.models.topology import Edge, Node
from backend.archaeology.snapshots import read_snapshot_graph

# Edge attributes worth reporting as ATTRIBUTE_CHANGED. Deliberately edges
# only -- a Node's only non-identity field is last_observed, which
# trivially advances every time any later traffic occurs at all; reporting
# that as a "change" would be pure noise with no topological significance,
# so node attribute changes are never produced (documented scope-out, the
# same pattern as Phase 40 explicitly never producing TOPOLOGY).


def _node_event(
    change_type: ChangeType, from_id: str, to_snapshot: NetworkSnapshot, node: Node, note: str
) -> GraphChangeEvent:
    return GraphChangeEvent(
        event_id=f"{to_snapshot.snapshot_id}:{change_type.value}:{node.node_id}",
        from_snapshot_id=from_id,
        to_snapshot_id=to_snapshot.snapshot_id,
        occurred_at=to_snapshot.captured_at,
        change_type=change_type,
        affected_node_id=node.node_id,
        evidence=[
            f"node {node.node_id} ({', '.join(str(ip) for ip in node.ip_addresses)}) {note}"
        ],
    )


def _edge_event(
    change_type: ChangeType, from_id: str, to_snapshot: NetworkSnapshot, edge: Edge, note: str
) -> GraphChangeEvent:
    return GraphChangeEvent(
        event_id=f"{to_snapshot.snapshot_id}:{change_type.value}:{edge.edge_id}",
        from_snapshot_id=from_id,
        to_snapshot_id=to_snapshot.snapshot_id,
        occurred_at=to_snapshot.captured_at,
        change_type=change_type,
        affected_edge_id=edge.edge_id,
        evidence=[f"edge {edge.edge_id} ({edge.source_node_id}<->{edge.target_node_id}) {note}"],
    )


def _edge_attribute_events(
    from_id: str, to_snapshot: NetworkSnapshot, before: Edge, after: Edge
) -> List[GraphChangeEvent]:
    events: List[GraphChangeEvent] = []

    if before.confidence != after.confidence:
        events.append(
            GraphChangeEvent(
                event_id=f"{to_snapshot.snapshot_id}:attribute_changed:{after.edge_id}:confidence",
                from_snapshot_id=from_id,
                to_snapshot_id=to_snapshot.snapshot_id,
                occurred_at=to_snapshot.captured_at,
                change_type=ChangeType.ATTRIBUTE_CHANGED,
                affected_edge_id=after.edge_id,
                attribute_name="confidence",
                previous_value=f"{before.confidence:.3f}",
                new_value=f"{after.confidence:.3f}",
                evidence=[
                    f"edge {after.edge_id} confidence changed from {before.confidence:.3f} to "
                    f"{after.confidence:.3f} (observation_count {before.observation_count} -> "
                    f"{after.observation_count})"
                ],
            )
        )

    if before.protocols != after.protocols:
        events.append(
            GraphChangeEvent(
                event_id=f"{to_snapshot.snapshot_id}:attribute_changed:{after.edge_id}:protocols",
                from_snapshot_id=from_id,
                to_snapshot_id=to_snapshot.snapshot_id,
                occurred_at=to_snapshot.captured_at,
                change_type=ChangeType.ATTRIBUTE_CHANGED,
                affected_edge_id=after.edge_id,
                attribute_name="protocols",
                previous_value=",".join(before.protocols),
                new_value=",".join(after.protocols),
                evidence=[
                    f"edge {after.edge_id} protocols changed from "
                    f"[{','.join(before.protocols)}] to [{','.join(after.protocols)}]"
                ],
            )
        )

    return events


def _sort_key(event: GraphChangeEvent) -> tuple:
    target_id = event.affected_node_id or event.affected_edge_id or ""
    return (event.change_type.value, target_id, event.attribute_name or "")


def diff_snapshots(
    root: Path,
    capture_id: str,
    from_snapshot: NetworkSnapshot,
    to_snapshot: NetworkSnapshot,
) -> List[GraphChangeEvent]:
    """Computes every structural/attribute difference between the graphs
    `from_snapshot` and `to_snapshot` reference (both read back via Phase
    44's `read_snapshot_graph`).

    Typical usage passes `from_snapshot` as the chronologically earlier
    snapshot and `to_snapshot` as the later one, in which case additions
    reflect genuine growth. Nothing prevents the reverse -- comparing
    `from`=later against `to`=earlier simply flips which side looks
    "added" vs. "removed"; not an error, and tested directly to confirm
    the mechanism is genuinely symmetric.

    Returns `[]` if the two graphs are identical. Deterministically
    ordered by `(change_type, target_id, attribute_name)`.
    """
    from_graph = read_snapshot_graph(root, capture_id, from_snapshot)
    to_graph = read_snapshot_graph(root, capture_id, to_snapshot)
    from_id = from_snapshot.snapshot_id

    from_nodes: Dict[str, Node] = {n.node_id: n for n in from_graph.nodes}
    to_nodes: Dict[str, Node] = {n.node_id: n for n in to_graph.nodes}
    from_edges: Dict[str, Edge] = {e.edge_id: e for e in from_graph.edges}
    to_edges: Dict[str, Edge] = {e.edge_id: e for e in to_graph.edges}

    events: List[GraphChangeEvent] = []

    for node_id in to_nodes.keys() - from_nodes.keys():
        events.append(
            _node_event(
                ChangeType.NODE_ADDED,
                from_id,
                to_snapshot,
                to_nodes[node_id],
                "not present as of the earlier snapshot",
            )
        )
    for node_id in from_nodes.keys() - to_nodes.keys():
        events.append(
            _node_event(
                ChangeType.NODE_REMOVED,
                from_id,
                to_snapshot,
                from_nodes[node_id],
                "was present in the earlier snapshot but not in the later one",
            )
        )

    for edge_id in to_edges.keys() - from_edges.keys():
        events.append(
            _edge_event(
                ChangeType.EDGE_ADDED,
                from_id,
                to_snapshot,
                to_edges[edge_id],
                "not present as of the earlier snapshot",
            )
        )
    for edge_id in from_edges.keys() - to_edges.keys():
        events.append(
            _edge_event(
                ChangeType.EDGE_REMOVED,
                from_id,
                to_snapshot,
                from_edges[edge_id],
                "was present in the earlier snapshot but not in the later one",
            )
        )

    for edge_id in to_edges.keys() & from_edges.keys():
        events.extend(
            _edge_attribute_events(from_id, to_snapshot, from_edges[edge_id], to_edges[edge_id])
        )

    return sorted(events, key=_sort_key)
