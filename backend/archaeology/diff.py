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

Extended by Phase 48 (Change Attribution, FR-1.23) to populate
`GraphChangeEvent.affected_flow_ids` -- see
`docs/architecture/change_attribution.md` for the full design. Flows are
matched against a node/edge's IP set(s), filtered to
`flow.first_seen <= to_snapshot.captured_at` -- the same `as_of` bound
Phase 43/44 already use (a snapshot's `captured_at` doubles as its `as_of`),
so attribution stays evidence-consistent with what the later snapshot
actually saw.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from backend.app.models.flow import Flow
from backend.app.models.snapshot import ChangeType, GraphChangeEvent, NetworkSnapshot
from backend.app.models.topology import Edge, Node
from backend.archaeology.snapshots import read_snapshot_graph
from experiments.artifacts.io import read_jsonl
from experiments.artifacts.paths import flows_path

# Edge attributes worth reporting as ATTRIBUTE_CHANGED. Deliberately edges
# only -- a Node's only non-identity field is last_observed, which
# trivially advances every time any later traffic occurs at all; reporting
# that as a "change" would be pure noise with no topological significance,
# so node attribute changes are never produced (documented scope-out, the
# same pattern as Phase 40 explicitly never producing TOPOLOGY).


def _flows_as_of(root: Path, capture_id: str, as_of) -> List[Flow]:
    path = flows_path(root, capture_id)
    if not path.is_file():
        return []
    flows = read_jsonl(path, Flow)
    return [f for f in flows if f.first_seen <= as_of]


def _flow_ids_for_node(flows: List[Flow], node: Node) -> List[str]:
    node_ips = {str(ip) for ip in node.ip_addresses}
    return sorted({f.flow_id for f in flows if str(f.src_ip) in node_ips or str(f.dst_ip) in node_ips})


def _flow_ids_for_edge(flows: List[Flow], node_a: Node, node_b: Node) -> List[str]:
    a_ips = {str(ip) for ip in node_a.ip_addresses}
    b_ips = {str(ip) for ip in node_b.ip_addresses}
    return sorted(
        {
            f.flow_id
            for f in flows
            if (str(f.src_ip) in a_ips and str(f.dst_ip) in b_ips)
            or (str(f.src_ip) in b_ips and str(f.dst_ip) in a_ips)
        }
    )


def _node_event(
    change_type: ChangeType,
    from_id: str,
    to_snapshot: NetworkSnapshot,
    node: Node,
    note: str,
    flow_ids: List[str],
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
        affected_flow_ids=flow_ids,
    )


def _edge_event(
    change_type: ChangeType,
    from_id: str,
    to_snapshot: NetworkSnapshot,
    edge: Edge,
    note: str,
    flow_ids: List[str],
) -> GraphChangeEvent:
    return GraphChangeEvent(
        event_id=f"{to_snapshot.snapshot_id}:{change_type.value}:{edge.edge_id}",
        from_snapshot_id=from_id,
        to_snapshot_id=to_snapshot.snapshot_id,
        occurred_at=to_snapshot.captured_at,
        change_type=change_type,
        affected_edge_id=edge.edge_id,
        evidence=[f"edge {edge.edge_id} ({edge.source_node_id}<->{edge.target_node_id}) {note}"],
        affected_flow_ids=flow_ids,
    )


def _edge_attribute_events(
    from_id: str,
    to_snapshot: NetworkSnapshot,
    before: Edge,
    after: Edge,
    flow_ids: List[str],
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
                affected_flow_ids=flow_ids,
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
                affected_flow_ids=flow_ids,
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

    # Phase 48 (FR-1.23): flow evidence attributable to each change, bounded
    # by the same as_of the later snapshot itself used (captured_at).
    flows = _flows_as_of(root, capture_id, to_snapshot.captured_at)

    events: List[GraphChangeEvent] = []

    for node_id in to_nodes.keys() - from_nodes.keys():
        node = to_nodes[node_id]
        events.append(
            _node_event(
                ChangeType.NODE_ADDED,
                from_id,
                to_snapshot,
                node,
                "not present as of the earlier snapshot",
                _flow_ids_for_node(flows, node),
            )
        )
    for node_id in from_nodes.keys() - to_nodes.keys():
        node = from_nodes[node_id]
        events.append(
            _node_event(
                ChangeType.NODE_REMOVED,
                from_id,
                to_snapshot,
                node,
                "was present in the earlier snapshot but not in the later one",
                _flow_ids_for_node(flows, node),
            )
        )

    for edge_id in to_edges.keys() - from_edges.keys():
        edge = to_edges[edge_id]
        events.append(
            _edge_event(
                ChangeType.EDGE_ADDED,
                from_id,
                to_snapshot,
                edge,
                "not present as of the earlier snapshot",
                _flow_ids_for_edge(flows, to_nodes[edge.source_node_id], to_nodes[edge.target_node_id]),
            )
        )
    for edge_id in from_edges.keys() - to_edges.keys():
        edge = from_edges[edge_id]
        events.append(
            _edge_event(
                ChangeType.EDGE_REMOVED,
                from_id,
                to_snapshot,
                edge,
                "was present in the earlier snapshot but not in the later one",
                _flow_ids_for_edge(
                    flows, from_nodes[edge.source_node_id], from_nodes[edge.target_node_id]
                ),
            )
        )

    for edge_id in to_edges.keys() & from_edges.keys():
        after = to_edges[edge_id]
        flow_ids = _flow_ids_for_edge(flows, to_nodes[after.source_node_id], to_nodes[after.target_node_id])
        events.extend(
            _edge_attribute_events(from_id, to_snapshot, from_edges[edge_id], after, flow_ids)
        )

    return sorted(events, key=_sort_key)
