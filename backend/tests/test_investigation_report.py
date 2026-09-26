"""Phase 100: cited investigation reports; every claim must trace to a real value (scripted LLM, no key, no network)."""

from __future__ import annotations

import itertools
import math
import re

import pytest
from fastapi.testclient import TestClient

from backend.app.api.routes.investigation import get_optional_llm
from backend.app.core.config import get_settings
from backend.app.main import app
from backend.app.models.failure import FailureScenario, FailureType
from backend.dependency.causal_candidates import generate_causal_candidates
from backend.dependency.causal_evidence import build_dependency_evidence_report
from backend.dependency.strength import estimate_dependency_strength
from backend.nettrace.topology.discovery import discover_nodes
from backend.nettrace.topology.edges import discover_edges
from backend.nettrace.topology.graph import build_topology_graph
from backend.nlq.explain import verify_explanation
from backend.nlq.llm import LLMUnavailableError, ScriptedLLM
from backend.nlq.report import build_report_facts, generate_report
from backend.simulation.failure_propagation_pipeline import run_failure_propagation_pipeline
from backend.simulation.resilience_indicators import compute_resilience_indicators

client = TestClient(app)


@pytest.fixture()
def real(tmp_path, monkeypatch):
    from scripts.seed_attribution_demo import seed

    monkeypatch.setenv("NETSCOPE_ARTIFACT_ROOT", str(tmp_path / "art"))
    monkeypatch.setenv("NETSCOPE_UPLOAD_STAGING_DIR", str(tmp_path / "inbox"))
    get_settings.cache_clear()
    cid = seed(tmp_path / "art", "small")["capture_id"]
    root = tmp_path / "art"
    st = get_settings()
    graph = build_topology_graph(root, cid, graph_id=cid)
    deps = estimate_dependency_strength(root, cid)
    edges = discover_edges(root, cid, discover_nodes(root, cid))
    cands = generate_causal_candidates(deps, strength_threshold=st.causal_candidate_strength_threshold)
    yield dict(cid=cid, root=root, st=st, graph=graph, deps=deps, edges=edges, cands=cands)
    get_settings.cache_clear()


def _known(graph, dep):
    return sorted({n.node_id for n in graph.nodes} | {e.edge_id for e in graph.edges}
                  | {str(ip) for n in graph.nodes for ip in n.ip_addresses} | {dep.dependency_id}, key=len, reverse=True)


def _report(real, i=0, node=None, llm=None):
    d = real["deps"][i]
    cand = next((c for c in real["cands"] if c.dependency_id == d.dependency_id), None)
    return generate_report(real["graph"], d, real["edges"][i].confidence, cand, node, real["st"], llm, real["cands"])


def _independent_shapley(t):
    gains = [0.0] * 5
    perms = list(itertools.permutations(range(5)))
    for perm in perms:
        cur = 1.0
        for i in perm:
            nxt = cur * (1 - t[i])
            gains[i] += cur - nxt
            cur = nxt
    return [g / len(perms) for g in gains]


def _recompute(real, i, node, source):
    """The value `source` points at, computed WITHOUT report.py."""
    d, st = real["deps"][i], real["st"]
    cand = next((c for c in real["cands"] if c.dependency_id == d.dependency_id), None)
    rep = build_dependency_evidence_report(d, cand)
    if source == "dependency.strength":
        return d.strength
    if source == "evidence_report.relationship":
        return rep.relationship
    m = re.match(r"evidence_report\.(evidence|counter_evidence|limitations)\[(\d+)\]", source)
    if m:
        return getattr(rep, m.group(1))[int(m.group(2))]
    m = re.match(r"attribution\.signals\[(\w+)\]\.contribution", source)
    if m:
        s = st.dependency_signal_strength
        t = [1 - math.exp(-d.frequency / st.dependency_frequency_scale),
             s * (1 - math.exp(-d.persistence_seconds / st.dependency_persistence_scale)),
             s * d.directionality_score, s * real["edges"][i].confidence, s * d.temporal_precedence_score]
        order = ["frequency", "persistence", "directionality", "traffic_characteristics", "temporal_precedence"]
        return _independent_shapley(t)[order.index(m.group(1))]
    sc = FailureScenario(scenario_id="x", failure_type=FailureType.NODE_FAILURE, target_node_id=node)
    res = run_failure_propagation_pipeline(real["graph"], sc, real["cands"])
    if source == "resilience.connectivity_ratio":
        return compute_resilience_indicators(real["graph"], res).connectivity_ratio
    if source == "pipeline.newly_unreachable_node_ids":
        return sorted(res.newly_unreachable_node_ids)
    if source == "pipeline.route_changes":
        return [len(res.route_changes), len([r for r in res.route_changes if r.changed])]
    m = re.match(r"pipeline\.service_impacts\[(.+)\]", source)
    if m:
        return next(x for x in res.service_impacts if x.node_id == m.group(1)).reason
    m = re.match(r"pipeline\.propagation_impacts\[(.+)\]", source)
    if m:
        return next(x for x in res.propagation_impacts if x.affected_node_id == m.group(1)).order.value
    raise AssertionError(f"unmapped source {source}")


def _busiest(real):
    g = real["graph"]
    return max(g.nodes, key=lambda n: sum(n.node_id in (e.source_node_id, e.target_node_id) for e in g.edges)).node_id


@pytest.mark.parametrize("with_node", [False, True])
def test_every_citation_traces_to_an_independently_recomputed_real_value(real, with_node) -> None:
    node = _busiest(real) if with_node else None
    out = _report(real, 0, node)
    assert out["source"] == "template" and out["citations"]
    for c in out["citations"]:
        assert c["source"], c
        want = _recompute(real, 0, node, c["source"])
        if isinstance(want, float):
            assert c["value"] == pytest.approx(want, abs=1e-12), c
            assert f"{want:.4f}" in c["text"] or f"{want:.3f}" in c["text"]
        else:
            assert c["value"] == want, c
            if isinstance(want, str):  # verbatim report text: same words, only sentence punctuation normalized
                assert re.sub(r"\W+", " ", want).strip() in re.sub(r"\W+", " ", c["text"]), c
            elif want and isinstance(want[0], str):
                assert all(n in c["text"] for n in want), c
    assert ("Impact" in out["markdown"]) == with_node


def test_template_report_is_itself_fully_cited_and_passes_the_verifier(real) -> None:
    node = _busiest(real)
    d = real["deps"][0]
    facts, _, _ = build_report_facts(real["graph"], d, real["edges"][0].confidence, None, node, real["st"], real["cands"])
    prose = "\n".join(l[2:] for l in _report(real, 0, node)["markdown"].splitlines() if l.startswith("- "))
    assert verify_explanation(prose, facts, _known(real["graph"], d)) == []
    assert all(f.source for f in facts) and len({f.fact_id for f in facts}) == len(facts)


def test_faithful_draft_is_accepted_and_limitations_are_appended_by_code(real) -> None:
    d = real["deps"][0]
    facts, _, _ = build_report_facts(real["graph"], d, real["edges"][0].confidence, None, None, real["st"], real["cands"])
    pick = [f for f in facts if f.kind in ("finding", "signal")][:3]
    draft = "## Finding\n" + " ".join(f"{f.text} [{f.fact_id}]" for f in pick)
    out = _report(real, 0, None, ScriptedLLM(text=draft))
    assert out["source"] == "llm" and out["violations"] == []
    for f in facts:
        if f.kind == "limitation":
            assert f.text in out["markdown"]  # the model cannot drop them
    assert "correlational" in out["markdown"]


@pytest.mark.parametrize("bad", [
    "The strength is 0.1234. [F1]",  # invented number
    "Node 6.6.6.6 is the culprit. [F1]",  # invented identifier
    "This proves the dependency. Nothing else matters.",  # uncited
    "All good. [F999]",  # unknown fact id
    "The source caused the target to fail. [F1]",  # causal claim without propagation evidence
    "There are two signals. [F3]",  # number word
])
def test_unfaithful_drafts_fall_back_to_the_template(real, bad) -> None:
    out = _report(real, 0, None, ScriptedLLM(text=bad))
    assert out["source"] == "template" and out["violations"] and bad not in out["markdown"]
    assert "## Limitations" in out["markdown"] and "correlational" in out["markdown"]


def test_llm_failure_gives_the_template_not_an_error(real) -> None:
    out = _report(real, 0, None, ScriptedLLM(text=LLMUnavailableError("down")))
    assert out["source"] == "template" and out["violations"][0].startswith("llm_error")


def test_route_returns_report_404_and_isolates_tenants(real, tmp_path) -> None:
    cid, d0 = real["cid"], real["deps"][0].dependency_id
    body = {"capture_id": cid, "dependency_id": d0}
    r = client.post("/api/v1/investigation/report", json=body)
    assert r.status_code == 200 and r.json()["source"] == "template" and r.json()["citations"]
    node = _busiest(real)
    withn = client.post("/api/v1/investigation/report", json={**body, "failed_node_id": node}).json()
    assert "Impact" in withn["markdown"]
    assert client.post("/api/v1/investigation/report", json={**body, "dependency_id": "nope"}).json()["error"] == "dependency_not_found"
    assert client.post("/api/v1/investigation/report", json={**body, "failed_node_id": "GHOST"}).status_code == 404
    app.dependency_overrides[get_optional_llm] = lambda: ScriptedLLM(text="Invented 42. [F1]")
    try:
        assert client.post("/api/v1/investigation/report", json=body).json()["source"] == "template"
    finally:
        app.dependency_overrides.clear()
    assert client.post("/api/v1/investigation/report", json={**body, "capture_id": "../x"}).status_code == 422
