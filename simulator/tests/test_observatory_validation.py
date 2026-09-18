"""Phase 20 observatory-validation tests.

Pure, no Docker required -- covers the three pure decision/parsing helpers
scripts/validate_observatory.py reduces each Docker-touching check to,
matching the pure/no-Docker testing convention already used throughout this
project (e.g. simulator/ground_truth/generate.py's builders).
"""

from __future__ import annotations

from scripts.validate_observatory import (
    _evaluate_reachability_payload,
    _parse_upstream_header,
    _summarize_protocol_attempt,
)


def test_reachability_payload_all_true() -> None:
    payload = {"service": "api-1", "redis_reachable": True, "database_reachable": True, "external_reachable": True}
    ok, failed = _evaluate_reachability_payload(payload)
    assert ok is True
    assert failed == []


def test_reachability_payload_one_false() -> None:
    payload = {"service": "api-1", "redis_reachable": True, "database_reachable": False, "external_reachable": True}
    ok, failed = _evaluate_reachability_payload(payload)
    assert ok is False
    assert failed == ["database_reachable"]


def test_reachability_payload_all_false() -> None:
    payload = {"redis_reachable": False, "database_reachable": False, "external_reachable": False}
    ok, failed = _evaluate_reachability_payload(payload)
    assert ok is False
    assert failed == ["redis_reachable", "database_reachable", "external_reachable"]


def test_reachability_payload_missing_field_counts_as_failed() -> None:
    ok, failed = _evaluate_reachability_payload({"redis_reachable": True})
    assert ok is False
    assert failed == ["database_reachable", "external_reachable"]


def test_parse_upstream_header_present() -> None:
    raw = "HTTP/1.1 200 OK\r\nServer: nginx\r\nX-Gateway-Upstream: 172.18.0.6:80\r\nContent-Length: 2\r\n"
    assert _parse_upstream_header(raw) == "172.18.0.6:80"


def test_parse_upstream_header_case_insensitive() -> None:
    raw = "HTTP/1.1 200 OK\r\nx-gateway-upstream: 172.18.0.5:80\r\n"
    assert _parse_upstream_header(raw) == "172.18.0.5:80"


def test_parse_upstream_header_absent() -> None:
    raw = "HTTP/1.1 200 OK\r\nServer: nginx\r\nContent-Length: 2\r\n"
    assert _parse_upstream_header(raw) is None


def test_parse_upstream_header_malformed_empty_string() -> None:
    assert _parse_upstream_header("") is None


def test_summarize_protocol_attempt_ok_true() -> None:
    assert _summarize_protocol_attempt({"ok": True, "latency_ms": 1.2}) is True


def test_summarize_protocol_attempt_ok_false() -> None:
    assert _summarize_protocol_attempt({"ok": False, "error": "timed out"}) is False


def test_summarize_protocol_attempt_status_code_200() -> None:
    assert _summarize_protocol_attempt({"status_code": 200, "error": None}) is True


def test_summarize_protocol_attempt_status_code_500() -> None:
    assert _summarize_protocol_attempt({"status_code": 500, "error": None}) is False


def test_summarize_protocol_attempt_rcode_zero() -> None:
    assert _summarize_protocol_attempt({"rcode": 0}) is True


def test_summarize_protocol_attempt_rcode_nonzero() -> None:
    assert _summarize_protocol_attempt({"rcode": 3}) is False


def test_summarize_protocol_attempt_explicit_error_overrides() -> None:
    assert _summarize_protocol_attempt({"ok": True, "error": "connection reset"}) is False


def test_summarize_protocol_attempt_missing_fields_is_failure() -> None:
    assert _summarize_protocol_attempt({}) is False
