"""Phase 102: live experiment runs (whitelisted, rate limited, opt-in) and the Lab's detail/compare endpoints."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from backend.app import experiments_runner as runner
from backend.app.core.config import get_settings
from backend.app.main import app
from experiments.artifacts.io import read_experiment_run

client = TestClient(app)
BODY = {"topology_level": "small", "completeness": 1.0, "ablation": None, "seed": 7}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("NETSCOPE_ARTIFACT_ROOT", str(tmp_path / "art"))
    monkeypatch.setenv("NETSCOPE_ENABLE_EXPERIMENT_RUNS", "true")
    get_settings.cache_clear()
    runner.reset()
    yield tmp_path / "art"
    runner.reset()
    get_settings.cache_clear()


def _wait(job_id):
    for _ in range(600):
        s = client.get(f"/api/v1/experiments/jobs/{job_id}").json()
        if s["status"] in ("done", "error"):
            return s
        time.sleep(0.5)
    raise AssertionError("job did not finish")


def test_disabled_by_default(env, monkeypatch):
    monkeypatch.setenv("NETSCOPE_ENABLE_EXPERIMENT_RUNS", "false")
    get_settings.cache_clear()
    assert client.post("/api/v1/experiments", json=BODY).status_code == 403


def test_run_streams_persists_and_is_readable(env):
    r = client.post("/api/v1/experiments", json=BODY)
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    busy = client.post("/api/v1/experiments", json={**BODY, "seed": 8})
    assert busy.status_code == 429 and busy.headers["Retry-After"]
    with client.stream("GET", f"/api/v1/experiments/jobs/{job_id}/events") as s:
        text = "".join(s.iter_text())
    kinds = [l[7:] for l in text.splitlines() if l.startswith("event: ")]
    assert kinds[0] == "queued" and kinds[-1] == "done" and "started" in kinds
    snap = _wait(job_id)
    assert snap["status"] == "done"
    eid = snap["experiment_id"]
    exp, metrics = read_experiment_run(env, eid)  # persisted by the real runner
    assert eid in [e["experiment_id"] for e in client.get("/api/v1/experiments").json()["items"]]
    d = client.get(f"/api/v1/experiments/{eid}").json()
    assert d["hypothesis"] is None and d["setup"]["configuration"] == exp.configuration
    assert d["result"] == exp.results and len(d["metrics"]) == len(metrics) > 0


def test_compare_deltas_match_stored_metrics(env):
    ids = []
    for seed in (1, 2):
        j = runner.start_run(env, "global", {**BODY, "seed": seed}, 5, run_in_thread=False)
        assert j.status == "done"
        ids.append(j.experiment_id)
    c = client.get("/api/v1/experiments/compare", params={"a": ids[0], "b": ids[1]}).json()
    ma = {m.context.value: m for m in read_experiment_run(env, ids[0])[1]}
    mb = {m.context.value: m for m in read_experiment_run(env, ids[1])[1]}
    assert c["rows"]
    for row in c["rows"]:
        va, vb = getattr(ma[row["context"]], row["metric"]), getattr(mb[row["context"]], row["metric"])
        assert (row["a"], row["b"]) == (va, vb) and row["delta"] == vb - va


def test_rate_limit_validation_and_ids(env):
    runner.start_run(env, "global", BODY, 1, run_in_thread=False)
    with pytest.raises(runner.RunRejected) as e:
        runner.start_run(env, "global", {**BODY, "seed": 4}, 1, run_in_thread=False)
    assert e.value.status == 429 and e.value.retry_after
    runner.reset()
    for bad in ({"topology_level": "nope"}, {"completeness": 0.3}, {"ablation": "x"}, {"seed": 100000}):
        assert client.post("/api/v1/experiments", json={**BODY, **bad}).status_code == 422
    assert client.get("/api/v1/experiments/missing-id").status_code == 404
    assert client.get("/api/v1/experiments/bad.id").status_code == 422
    assert client.get("/api/v1/experiments/jobs/" + "0" * 32).status_code == 404


def test_jobs_are_tenant_scoped(env):
    j = runner.start_run(env, "tenant-a", BODY, 5, run_in_thread=False)
    assert runner.get_job(j.job_id, "tenant-a") is j and runner.get_job(j.job_id, "tenant-b") is None
