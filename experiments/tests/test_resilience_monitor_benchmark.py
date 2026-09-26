"""Phase 89: controlled failure through sync daemon -> resilience monitor -> observable alert."""

from __future__ import annotations

from experiments import resilience_monitor_benchmark as B


def test_hub_failure_fires_observable_alert_then_resolves(tmp_path):
    row = B.run_case(tmp_path, "small", 42, "hub")
    assert row.healthy_alerts == 0
    assert row.expect_alert and row.fired and row.value_matches and row.in_jsonl and row.resolved
    assert row.latency_s is not None and row.latency_s < 30


def test_no_alert_when_independent_ratio_stays_above_threshold(tmp_path):
    row = B.run_case(tmp_path, "large", 42, "leaf")
    assert not row.expect_alert and not row.fired and row.healthy_alerts == 0 and row.in_jsonl


def test_sweep_cost_reports_scenarios(tmp_path):
    assert "scenarios" in B.sweep_cost(tmp_path, ("small",))
