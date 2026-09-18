"""Phase 19 traffic replay engine tests.

Pure, no Docker/network required -- proves that `load_recording` derives a
deterministic replay schedule from a recorded JSON-Lines log, for both the
Phase 14 pattern-log shape and the Phase 15 protocol-log shape.
"""

from __future__ import annotations

import json

import pytest

from simulator.traffic.replay import ReplayEvent, load_recording

PATTERN_LOG_LINES = [
    {
        "pattern": "burst",
        "seed": 7,
        "sequence": 0,
        "group_id": 0,
        "retry_of": None,
        "scheduled_offset_seconds": 0.0,
        "sent_at": "2026-01-01T00:00:00.000000+00:00",
        "target": "http://gateway/",
        "status_code": 200,
        "error": None,
        "latency_ms": 4.2,
    },
    {
        "pattern": "burst",
        "seed": 7,
        "sequence": 1,
        "group_id": 0,
        "retry_of": None,
        "scheduled_offset_seconds": 0.1,
        "sent_at": "2026-01-01T00:00:00.250000+00:00",
        "target": "http://gateway/",
        "status_code": 200,
        "error": None,
        "latency_ms": 3.1,
    },
    {
        "pattern": "burst",
        "seed": 7,
        "sequence": 2,
        "group_id": 1,
        "retry_of": None,
        "scheduled_offset_seconds": 3.0,
        "sent_at": "2026-01-01T00:00:03.400000+00:00",
        "target": "http://gateway/",
        "status_code": 500,
        "error": None,
        "latency_ms": 9.9,
    },
]

PROTOCOL_LOG_LINES = [
    {
        "protocol": "dns",
        "host": "dns",
        "port": 53,
        "sequence": 0,
        "sent_at": "2026-01-01T00:00:00.000000+00:00",
        "ok": True,
        "rcode": 0,
        "latency_ms": 1.5,
    },
    {
        "protocol": "dns",
        "host": "dns",
        "port": 53,
        "sequence": 1,
        "sent_at": "2026-01-01T00:00:01.000000+00:00",
        "ok": True,
        "rcode": 0,
        "latency_ms": 1.7,
    },
]


def _write_jsonl(tmp_path, name, records):
    path = tmp_path / name
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record))
            f.write("\n")
    return path


def test_pattern_log_offsets_derived_from_sent_at(tmp_path) -> None:
    path = _write_jsonl(tmp_path, "pattern.jsonl", PATTERN_LOG_LINES)
    events = load_recording(path)
    assert [round(e.offset_seconds, 6) for e in events] == [0.0, 0.25, 3.4]
    assert all(e.kind == "http" for e in events)
    assert [e.params["target"] for e in events] == ["http://gateway/"] * 3
    assert [e.sequence for e in events] == [0, 1, 2]


def test_protocol_log_offsets_derived_from_sent_at(tmp_path) -> None:
    path = _write_jsonl(tmp_path, "protocol.jsonl", PROTOCOL_LOG_LINES)
    events = load_recording(path)
    assert [round(e.offset_seconds, 6) for e in events] == [0.0, 1.0]
    assert all(e.kind == "protocol" for e in events)
    assert [e.params["protocol"] for e in events] == ["dns", "dns"]
    assert [e.params["host"] for e in events] == ["dns", "dns"]
    assert [e.params["port"] for e in events] == [53, 53]


def test_loading_same_recording_twice_is_identical(tmp_path) -> None:
    path = _write_jsonl(tmp_path, "pattern.jsonl", PATTERN_LOG_LINES)
    a = load_recording(path)
    b = load_recording(path)
    assert a == b


def test_first_event_offset_is_zero(tmp_path) -> None:
    path = _write_jsonl(tmp_path, "pattern.jsonl", PATTERN_LOG_LINES)
    events = load_recording(path)
    assert events[0].offset_seconds == 0.0


def test_malformed_json_line_raises_with_line_number(tmp_path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text('{"sequence": 0, "sent_at": "2026-01-01T00:00:00+00:00", "pattern": "x", "target": "y"}\nnot json\n')
    with pytest.raises(ValueError, match=r":2:"):
        load_recording(path)


def test_record_missing_sent_at_raises(tmp_path) -> None:
    path = tmp_path / "missing.jsonl"
    path.write_text(json.dumps({"sequence": 0, "pattern": "x", "target": "y"}) + "\n")
    with pytest.raises(ValueError, match="sent_at"):
        load_recording(path)


def test_unrecognized_record_shape_raises(tmp_path) -> None:
    path = tmp_path / "unknown.jsonl"
    path.write_text(json.dumps({"sequence": 0, "sent_at": "2026-01-01T00:00:00+00:00", "mystery": True}) + "\n")
    with pytest.raises(ValueError, match="neither a recognizable"):
        load_recording(path)


def test_unknown_protocol_raises(tmp_path) -> None:
    path = tmp_path / "badprotocol.jsonl"
    path.write_text(
        json.dumps(
            {"sequence": 0, "sent_at": "2026-01-01T00:00:00+00:00", "protocol": "carrier-pigeon", "host": "x"}
        )
        + "\n"
    )
    with pytest.raises(ValueError, match="unknown protocol"):
        load_recording(path)


def test_empty_lines_are_skipped(tmp_path) -> None:
    path = tmp_path / "spaced.jsonl"
    content = "\n".join(json.dumps(r) for r in PATTERN_LOG_LINES)
    path.write_text(content + "\n\n")
    events = load_recording(path)
    assert len(events) == 3


def test_replay_event_is_frozen_and_comparable() -> None:
    a = ReplayEvent(offset_seconds=0.0, sequence=0, kind="http", params={"target": "x"})
    b = ReplayEvent(offset_seconds=0.0, sequence=0, kind="http", params={"target": "x"})
    assert a == b
    with pytest.raises(Exception):
        a.offset_seconds = 1.0  # type: ignore[misc]
