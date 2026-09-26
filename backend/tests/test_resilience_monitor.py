"""Phase 89 resilience monitor tests (pure, no Docker)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from backend.app.models.failure import FailureScenario, FailureType
from backend.simulation.failure_injection import apply_failure_scenario
from backend.simulation.failure_propagation_pipeline import run_failure_propagation_pipeline
from backend.simulation.resilience_indicators import compute_resilience_indicators
from backend.simulation.resilience_monitor import (
    SWEEP_RULES, AlertRule, _breached, _cleared, ResilienceMonitor, ResilienceMonitorDaemon, jsonl_sink, state_indicators, sweep_scenarios,
)
from backend.tests.test_resilience_indicators import _bowtie_graph, _chain_graph, _diamond_graph


def _twin(graph):
    return SimpleNamespace(topology=graph, dependencies=[])


def _fail(graph, node_id):
    sc = FailureScenario(scenario_id="x", failure_type=FailureType.NODE_FAILURE, target_node_id=node_id)
    return apply_failure_scenario(graph, sc).graph


def test_state_indicators_equal_phase62_for_injected_failure():
    for graph, node in ((_bowtie_graph(), "M"), (_chain_graph(), "B"), (_diamond_graph(), "B")):
        sc = FailureScenario(scenario_id="s", failure_type=FailureType.NODE_FAILURE, target_node_id=node)
        direct = compute_resilience_indicators(graph, run_failure_propagation_pipeline(graph, sc, []))
        got = state_indicators(graph, apply_failure_scenario(graph, sc).graph)
        assert got["connectivity_ratio"] == pytest.approx(direct.connectivity_ratio)
        assert got["reachable_node_ratio"] == pytest.approx(direct.reachable_node_ratio)


def test_healthy_state_is_silent_and_first_reading_is_reference():
    m = ResilienceMonitor()
    assert m.evaluate(_twin(_bowtie_graph())) == [] and m.alerts == [] and m.last_state["connectivity_ratio"] == 1.0


def test_crossing_fires_once_stays_quiet_then_resolves():
    g = _bowtie_graph()
    m = ResilienceMonitor(g)
    m.evaluate(_twin(g))
    broken = _fail(g, "M")  # bowtie bridge: splits the graph
    fired = m.evaluate(_twin(broken))
    assert {(a.rule, a.kind) for a in fired} >= {("connectivity_low", "fired")}
    assert m.stats.fired == len(fired)
    assert m.evaluate(_twin(broken)) == []  # still breached: no repeat
    resolved = m.evaluate(_twin(g))
    assert {a.kind for a in resolved} == {"resolved"} and m.active == []


def test_hysteresis_keeps_alert_until_margin_cleared():
    g = _chain_graph()
    rule = AlertRule("c", "connectivity_ratio", "lt", 0.7, "critical", "state", clear_margin=0.2)
    m = ResilienceMonitor(g, [rule])
    assert [a.kind for a in m.evaluate(_twin(_fail(g, "B")))] == ["fired"]  # ratio 1/3
    assert _breached(rule, 0.69) and not _breached(rule, 0.7)
    assert not _cleared(rule, 0.8)  # above threshold but inside the margin: stays active
    assert _cleared(rule, 0.9)


def test_boolean_and_sweep_rules_and_scenario_set():
    g = _diamond_graph()
    scs = sweep_scenarios(g)
    assert len(scs) == len(g.nodes) + len(g.edges) and sweep_scenarios(g, 3) == scs[:3]
    m = ResilienceMonitor(g, SWEEP_RULES, sweep=True)
    m.evaluate(_twin(g))
    assert len(m.last_sweep) == len(scs) and m.stats.scenarios_evaluated == len(scs)
    # sweep values are the Phase 62 output
    sc = next(s for s in scs if s.scenario_id == "node:B")
    direct = compute_resilience_indicators(g, run_failure_propagation_pipeline(g, sc, []))
    assert m.last_sweep["node:B"] == direct
    for a in m.alerts:
        assert a.kind == "fired" and a.rule in {"spof_connectivity", "spof_no_alternate_path"}


def test_disappearing_scope_resolves_its_alert():
    g = _diamond_graph()
    m = ResilienceMonitor(g, [AlertRule("s", "connectivity_ratio", "lt", 0.99, "info", "sweep")], sweep=True)
    m.evaluate(_twin(g))
    assert m.active
    smaller = _chain_graph()  # different node/edge ids: old scenarios vanish
    out = m.evaluate(_twin(smaller))
    assert any(a.kind == "resolved" and a.value is None for a in out)


def test_jsonl_sink_and_callback(tmp_path):
    g = _bowtie_graph()
    seen = []
    path = tmp_path / "a" / "alerts.jsonl"
    m = ResilienceMonitor(g, sinks=[jsonl_sink(path), seen.append])
    m.evaluate(_twin(_fail(g, "M")))
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(rows) == len(seen) == len(m.alerts) > 0
    assert rows[0]["kind"] == "fired" and rows[0]["scope_id"] == "state" and rows[0]["value"] < 0.8


def test_bad_rule_rejected():
    with pytest.raises(ValueError):
        ResilienceMonitor(rules=[AlertRule("x", "connectivity_ratio", "eq")])


def test_daemon_evaluates_latest_skips_unchanged_and_keeps_going():
    g = _bowtie_graph()
    m = ResilienceMonitor(g)
    d = ResilienceMonitorDaemon(m)
    d.start()
    healthy, broken = _twin(g), _twin(_fail(g, "M"))
    d.notify(healthy)
    assert d.wait_idle()
    d.notify(healthy)  # same object: skipped
    d.notify(broken)
    assert d.wait_idle()
    d.stop()
    assert d.skipped_unchanged == 1 and m.stats.evaluations == 2 and d.errors == []
    assert any(a.kind == "fired" for a in m.alerts)


def test_daemon_survives_evaluation_error():
    m = ResilienceMonitor(_chain_graph())
    d = ResilienceMonitorDaemon(m)
    d.start()
    d.notify(SimpleNamespace())  # no .topology
    assert d.wait_idle()
    d.notify(_twin(_chain_graph()))
    assert d.wait_idle()
    d.stop()
    assert len(d.errors) == 1 and m.stats.evaluations == 1
