"""Phase 101: every ranked "removing X would have prevented Y" must match a really executed, independently re-run counterfactual."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import backend.nlq.rootcause as rc
from backend.app.core.config import get_settings
from backend.app.main import app
from backend.app.models.failure import FailureScenario, FailureType
from backend.app.models.simulation import CounterfactualAction, CounterfactualScenario
from backend.nettrace.topology.graph import build_topology_graph
from backend.simulation.counterfactual_engine import execute_counterfactual_scenario
from backend.simulation.failure_propagation_pipeline import run_failure_propagation_pipeline

client = TestClient(app)


@pytest.fixture()
def real(tmp_path, monkeypatch):
    from scripts.seed_attribution_demo import seed

    monkeypatch.setenv("NETSCOPE_ARTIFACT_ROOT", str(tmp_path / "art"))
    monkeypatch.setenv("NETSCOPE_UPLOAD_STAGING_DIR", str(tmp_path / "inbox"))
    get_settings.cache_clear()
    cid = seed(tmp_path / "art", "small")["capture_id"]
    graph = build_topology_graph(tmp_path / "art", cid, graph_id=cid)
    yield dict(cid=cid, graph=graph)
    get_settings.cache_clear()


def _hub(graph):
    """Node whose failure cuts off the most nodes (independent search)."""
    def cut(n):
        f = FailureScenario(scenario_id="x", failure_type=FailureType.NODE_FAILURE, target_node_id=n)
        return len(run_failure_propagation_pipeline(graph, f, []).newly_unreachable_node_ids)
    return max((n.node_id for n in graph.nodes), key=lambda n: (cut(n), n))


def test_every_item_is_a_real_executed_counterfactual(real, monkeypatch):
    g = real["graph"]
    executed = []
    orig = rc.execute_counterfactual_scenario
    monkeypatch.setattr(rc, "execute_counterfactual_scenario", lambda gr, sc: (executed.append(sc.scenario_id), orig(gr, sc))[1])
    failed = _hub(g)
    out = rc.rank_root_causes(g, failed)
    assert out["ranking"] and sorted(executed) == sorted(r["scenario_id"] for r in out["ranking"])
    failure = FailureScenario(scenario_id="f", failure_type=FailureType.NODE_FAILURE, target_node_id=failed)
    y = set(run_failure_propagation_pipeline(g, failure, []).newly_unreachable_node_ids)
    assert set(out["impacted_node_ids"]) == y
    for item in out["ranking"]:
        cf = CounterfactualScenario(
            scenario_id="ind", action=CounterfactualAction(item["action"]), baseline_graph_id=g.graph_id, isolated_graph_id="ind-iso",
            target_node_id=item["candidate"] if item["action"] == "REMOVE_NODE" else None,
            target_edge_id=item["candidate"] if item["action"] == "REMOVE_EDGE" else None, created_at=datetime.now(timezone.utc))
        ex = execute_counterfactual_scenario(g, cf)
        still = set(run_failure_propagation_pipeline(ex.graph, failure, []).newly_unreachable_node_ids)
        want = sorted(n for n in y if n in {x.node_id for x in ex.graph.nodes} and n not in still)
        assert item["prevented_node_ids"] == want
        assert item["score"] == (len(want) / len(y) if y else 0.0)
        assert set(item["prevented_node_ids"]) <= y and item["candidate"] not in item["prevented_node_ids"]


def test_ranking_sorted_deterministic_and_input_not_mutated(real):
    g, failed = real["graph"], _hub(real["graph"])
    before = (len(g.nodes), len(g.edges))
    a, b = rc.rank_root_causes(g, failed), rc.rank_root_causes(g, failed)
    assert [r["candidate"] for r in a["ranking"]] == [r["candidate"] for r in b["ranking"]]
    scores = [r["score"] for r in a["ranking"]]
    assert scores == sorted(scores, reverse=True) and [r["rank"] for r in a["ranking"]] == list(range(1, len(scores) + 1))
    assert (len(g.nodes), len(g.edges)) == before and a["caveat"]
    for r in a["ranking"]:
        assert ("would have prevented" in r["explanation"]) == bool(r["prevented_node_ids"])


def test_unknown_node_and_max_candidates(real):
    with pytest.raises(ValueError):
        rc.rank_root_causes(real["graph"], "nope")
    assert len(rc.rank_root_causes(real["graph"], _hub(real["graph"]), max_candidates=2)["ranking"]) == 2


def test_route(real):
    failed = _hub(real["graph"])
    r = client.post("/api/v1/investigation/root-cause", json={"capture_id": real["cid"], "failed_node_id": failed})
    assert r.status_code == 200 and r.json()["ranking"]
    assert client.post("/api/v1/investigation/root-cause", json={"capture_id": real["cid"], "failed_node_id": "nope"}).status_code == 404
    assert client.post("/api/v1/investigation/root-cause", json={"capture_id": "../x", "failed_node_id": failed}).status_code == 422
