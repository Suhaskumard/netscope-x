"""Phase 99: Shapley attribution of the dependency-strength noisy-OR."""

from __future__ import annotations

import itertools
import random

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import get_settings
from backend.app.main import app
from backend.dependency.attribution import attribute_strength, shapley, signal_terms
from backend.dependency.strength import combine_dependency_strength

client = TestClient(app)


def _random_args(rng: random.Random):
    return (rng.choice([0, rng.random() * 5, 50.0]), rng.choice([0, rng.random() * 300]),
            rng.random(), rng.choice([0, rng.random(), 1.0]), rng.choice([0, rng.random()]))


def test_contributions_sum_to_strength_for_random_and_saturating_inputs() -> None:
    rng = random.Random(1)
    for _ in range(300):
        a = attribute_strength(*_random_args(rng))
        assert abs(a.sum_of_contributions - a.strength) < 1e-12 and abs(a.residual) < 1e-12
        assert abs(a.strength_from_terms - a.strength) < 1e-12
        assert all(s.contribution >= -1e-15 for s in a.signals)


def test_matches_combine_dependency_strength_and_zero_signal_contributes_zero() -> None:
    a = attribute_strength(0.7, 30.0, 0.9, 0.6, 0.0)
    assert a.strength == combine_dependency_strength(0.7, 30.0, 0.9, 0.6, 0.0)
    temporal = next(s for s in a.signals if s.signal == "temporal_precedence")
    assert temporal.contribution == 0 and temporal.term == 0 and temporal.without == pytest.approx(a.strength)


def test_shapley_equals_average_over_all_orderings() -> None:
    terms = signal_terms(1.3, 20.0, 0.8, 0.5, 0.4)
    contrib = [0.0] * 5
    perms = list(itertools.permutations(range(5)))
    for perm in perms:
        survival = 1.0
        for i in perm:
            new = survival * (1 - terms[i])
            contrib[i] += survival - new  # marginal gain of adding i
            survival = new
    brute = [c / len(perms) for c in contrib]
    assert shapley(terms) == pytest.approx(brute, abs=1e-12)


def test_drop_one_matches_recomputation() -> None:
    a = attribute_strength(0.7, 30.0, 0.9, 0.6, 0.3)
    persistence = next(s for s in a.signals if s.signal == "persistence")
    assert persistence.without == pytest.approx(combine_dependency_strength(0.7, 0.0, 0.9, 0.6, 0.3))


@pytest.fixture()
def seeded(tmp_path, monkeypatch):
    from scripts.seed_attribution_demo import seed

    monkeypatch.setenv("NETSCOPE_ARTIFACT_ROOT", str(tmp_path / "art"))
    monkeypatch.setenv("NETSCOPE_UPLOAD_STAGING_DIR", str(tmp_path / "inbox"))
    get_settings.cache_clear()
    yield seed(tmp_path / "art")
    get_settings.cache_clear()


def test_route_numbers_equal_stored_strength_and_real_edge_confidence(seeded) -> None:
    from backend.nettrace.topology.discovery import discover_nodes
    from backend.nettrace.topology.edges import discover_edges

    cid = seeded["capture_id"]
    deps = client.get("/api/v1/dependencies", params={"capture_id": cid, "limit": 500}).json()["items"]
    assert len(deps) >= 3
    root = get_settings().artifact_root
    edges = discover_edges(root, cid, discover_nodes(root, cid))
    saw_temporal = False
    for i, d in enumerate(deps):
        body = client.get(f"/api/v1/causal/{d['dependency_id']}/attribution", params={"capture_id": cid}).json()
        assert body["stored_strength"] == d["strength"] and abs(body["strength"] - d["strength"]) < 1e-12
        assert abs(body["sum_of_contributions"] - d["strength"]) < 1e-12 and abs(body["residual"]) < 1e-12
        traffic = next(s for s in body["signals"] if s["signal"] == "traffic_characteristics")
        assert traffic["raw"] == pytest.approx(edges[i].confidence, abs=1e-12)
        assert body["report"]["confidence"] == pytest.approx(d["strength"])
        saw_temporal |= next(s for s in body["signals"] if s["signal"] == "temporal_precedence")["raw"] > 0
    assert saw_temporal, "seed capture should contain a dependency with temporal precedence > 0"


def test_route_404_and_tenant_isolation(tmp_path, monkeypatch) -> None:
    from backend.app.tenancy.paths import tenant_root
    from backend.app.tenancy.store import TenantRegistry
    from scripts.seed_attribution_demo import seed

    root = tmp_path / "art"
    monkeypatch.setenv("NETSCOPE_ARTIFACT_ROOT", str(root))
    monkeypatch.setenv("NETSCOPE_UPLOAD_STAGING_DIR", str(tmp_path / "inbox"))
    monkeypatch.setenv("NETSCOPE_TENANCY_ENABLED", "true")
    get_settings.cache_clear()
    reg = TenantRegistry(root)
    ka, kb = reg.create_tenant("acme"), reg.create_tenant("globex")
    cid = seed(tenant_root(root, "acme"))["capture_id"]
    dep = f"{cid}:dependency:0"
    p = {"capture_id": cid}
    assert client.get(f"/api/v1/causal/{dep}/attribution", params=p, headers={"X-Tenant-Key": ka}).status_code == 200
    assert client.get(f"/api/v1/causal/{dep}/attribution", params=p, headers={"X-Tenant-Key": kb}).status_code == 404
    assert client.get("/api/v1/causal/nope/attribution", params=p, headers={"X-Tenant-Key": ka}).json()["error"] == "dependency_not_found"
    get_settings.cache_clear()
