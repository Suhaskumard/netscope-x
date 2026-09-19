"""Phase 48 change attribution unit tests (pure, no Docker)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.app.models.snapshot import ChangeType, GraphChangeEvent
from backend.archaeology.attribution import (
    CAUSAL_DISCLAIMER,
    format_change_attribution,
    format_timeline_attribution,
)

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _event(
    change_type: ChangeType = ChangeType.NODE_ADDED,
    affected_node_id=None,
    affected_edge_id=None,
    attribute_name=None,
    previous_value=None,
    new_value=None,
    evidence=("node n1 (10.0.0.1) not present as of the earlier snapshot",),
    affected_flow_ids=(),
) -> GraphChangeEvent:
    return GraphChangeEvent(
        event_id="ev1",
        from_snapshot_id="s1",
        to_snapshot_id="s2",
        occurred_at=BASE,
        change_type=change_type,
        affected_node_id=affected_node_id,
        affected_edge_id=affected_edge_id,
        attribute_name=attribute_name,
        previous_value=previous_value,
        new_value=new_value,
        evidence=list(evidence),
        affected_flow_ids=list(affected_flow_ids),
    )


def test_format_includes_change_type_and_timestamp() -> None:
    event = _event(affected_node_id="n1")

    report = format_change_attribution(event)

    assert "node_added" in report
    assert "ev1" in report
    assert BASE.isoformat() in report


def test_format_includes_affected_node() -> None:
    event = _event(affected_node_id="n1")

    report = format_change_attribution(event)

    assert "Affected node: n1" in report


def test_format_includes_affected_edge_and_attribute() -> None:
    event = _event(
        change_type=ChangeType.ATTRIBUTE_CHANGED,
        affected_edge_id="e1",
        attribute_name="confidence",
        previous_value="0.500",
        new_value="0.800",
        evidence=("edge e1 confidence changed from 0.500 to 0.800",),
    )

    report = format_change_attribution(event)

    assert "Affected edge: e1" in report
    assert "Attribute: confidence: 0.500 -> 0.800" in report


def test_format_includes_observation_evidence() -> None:
    event = _event(affected_node_id="n1", evidence=("evidence line one", "evidence line two"))

    report = format_change_attribution(event)

    assert "evidence line one" in report
    assert "evidence line two" in report


def test_format_lists_affected_flow_ids_when_present() -> None:
    event = _event(affected_node_id="n1", affected_flow_ids=("cap-1:flow:0", "cap-1:flow:1"))

    report = format_change_attribution(event)

    assert "Affected flows: cap-1:flow:0, cap-1:flow:1" in report


def test_format_honestly_states_no_flows_when_absent() -> None:
    event = _event(affected_node_id="n1", affected_flow_ids=())

    report = format_change_attribution(event)

    assert "Affected flows: none directly attributable" in report
    assert "cap-1:flow" not in report


def test_format_always_includes_causal_disclaimer() -> None:
    for change_type, kwargs in [
        (ChangeType.NODE_ADDED, {"affected_node_id": "n1"}),
        (ChangeType.NODE_REMOVED, {"affected_node_id": "n1"}),
        (ChangeType.EDGE_ADDED, {"affected_edge_id": "e1"}),
        (ChangeType.EDGE_REMOVED, {"affected_edge_id": "e1"}),
        (
            ChangeType.ATTRIBUTE_CHANGED,
            {"affected_edge_id": "e1", "attribute_name": "confidence"},
        ),
    ]:
        event = _event(change_type=change_type, **kwargs)
        report = format_change_attribution(event)
        assert CAUSAL_DISCLAIMER in report


def test_format_timeline_attribution_joins_multiple_events_in_order() -> None:
    first = _event(affected_node_id="n1")
    second = GraphChangeEvent(
        event_id="ev2",
        from_snapshot_id="s2",
        to_snapshot_id="s3",
        occurred_at=BASE + timedelta(seconds=100),
        change_type=ChangeType.NODE_ADDED,
        affected_node_id="n2",
        evidence=["node n2 (10.0.0.2) not present as of the earlier snapshot"],
    )

    report = format_timeline_attribution([first, second])

    assert report.index("ev1") < report.index("ev2")
    assert report.count(CAUSAL_DISCLAIMER) == 2


def test_format_timeline_attribution_empty_list_returns_empty_string() -> None:
    assert format_timeline_attribution([]) == ""
