"""/experiments. Backing implementation: spec Phase 68 (Complete Research Validation) for `GET /experiments`.

`POST /experiments` was a 501 stub through Phase 101: triggering matrix computation through a public HTTP endpoint is a riskier
concern than reading persisted results. Phase 102 revisits that: it now starts a whitelisted, per-tenant rate-limited, opt-in
(`enable_experiment_runs`) single-cell run (`backend/app/experiments_runner.py`) with an SSE progress stream. The detail and compare
endpoints read the persisted records only.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from backend.app import experiments_runner as runner
from backend.app.api.schemas import CAPTURE_ID_PATTERN, PageParams, PaginatedResponse, get_page_params
from backend.app.core.config import get_settings
from backend.app.tenancy.deps import TenantScope, get_tenant_scope
from backend.app.models import Experiment
from experiments.artifacts.io import read_experiment_run
from experiments.artifacts.paths import experiment_manifest_path, experiment_path

router = APIRouter(prefix="/experiments", tags=["experiments"])

METRIC_FIELDS = ("precision", "recall", "f1", "false_positive_rate", "false_negative_rate",
                 "detection_latency_seconds", "graph_similarity", "calibration_error")
JOB_ID_PATTERN = r"^[0-9a-f]{32}$"


class RunRequest(BaseModel):
    topology_level: str
    completeness: float = 1.0
    ablation: Optional[str] = None
    seed: int = 42


def _list_experiments(root) -> list[Experiment]:
    experiments_dir = root / "experiments"
    if not experiments_dir.is_dir():
        return []
    experiment_ids = sorted(p.name for p in experiments_dir.iterdir() if p.is_dir())
    experiments = []
    for experiment_id in experiment_ids:
        # Phase 75: one record per experiment_id -- its latest run (older runs stay on disk).
        if experiment_manifest_path(root, experiment_id).is_file() or experiment_path(root, experiment_id).is_file():
            experiments.append(read_experiment_run(root, experiment_id)[0])
    return experiments


def _tenant_key(scope: TenantScope) -> str:
    return scope.tenant_id or "global"


def _load(scope: TenantScope, experiment_id: str):
    try:
        return read_experiment_run(scope.root, experiment_id)
    except (ValueError, FileNotFoundError):
        raise HTTPException(status_code=404, detail=f"no experiment {experiment_id!r}")


@router.get("", response_model=PaginatedResponse[Experiment])
def list_experiments(page: PageParams = Depends(get_page_params), scope: TenantScope = Depends(get_tenant_scope)) -> PaginatedResponse[Experiment]:
    experiments = _list_experiments(scope.root)
    page_items = experiments[page.offset : page.offset + page.limit]
    return PaginatedResponse[Experiment](
        items=page_items, limit=page.limit, offset=page.offset, total=len(experiments)
    )


@router.post("", status_code=202)
def start_experiment_run(body: RunRequest, scope: TenantScope = Depends(get_tenant_scope)):
    settings = get_settings()
    if not settings.enable_experiment_runs:
        raise HTTPException(status_code=403, detail="live experiment runs are disabled (set NETSCOPE_ENABLE_EXPERIMENT_RUNS=true)")
    try:
        job = runner.start_run(scope.root, _tenant_key(scope), body.model_dump(), settings.experiment_runs_per_hour)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except runner.RunRejected as exc:
        return JSONResponse(status_code=exc.status, content={"detail": exc.message},
                            headers={"Retry-After": str(exc.retry_after)} if exc.retry_after else None)
    return {"job_id": job.job_id, "status": job.status}


@router.get("/compare")
def compare_experiments(a: str = Query(..., pattern=CAPTURE_ID_PATTERN), b: str = Query(..., pattern=CAPTURE_ID_PATTERN),
                        scope: TenantScope = Depends(get_tenant_scope)) -> Dict[str, Any]:
    """Metric deltas (b - a) per context, only where both stored records have a value."""
    _, ma = _load(scope, a)
    _, mb = _load(scope, b)
    by_a = {m.context.value: m for m in ma}
    rows: List[Dict[str, Any]] = []
    for m in sorted(mb, key=lambda m: m.context.value):
        ctx = m.context.value
        if ctx not in by_a:
            continue
        for f in METRIC_FIELDS:
            va, vb = getattr(by_a[ctx], f), getattr(m, f)
            if va is not None and vb is not None:
                rows.append({"context": ctx, "metric": f, "a": va, "b": vb, "delta": vb - va})
    return {"a": a, "b": b, "rows": rows}


@router.get("/jobs/{job_id}")
def get_run_job(job_id: str = Path(..., pattern=JOB_ID_PATTERN), scope: TenantScope = Depends(get_tenant_scope)):
    job = runner.get_job(job_id, _tenant_key(scope))
    if job is None:
        raise HTTPException(status_code=404, detail="no such job")
    return job.snapshot()


@router.get("/jobs/{job_id}/events")
def stream_run_events(job_id: str = Path(..., pattern=JOB_ID_PATTERN), last_event_id: Optional[str] = Header(default=None),
                      scope: TenantScope = Depends(get_tenant_scope)) -> StreamingResponse:
    job = runner.get_job(job_id, _tenant_key(scope))
    if job is None:
        raise HTTPException(status_code=404, detail="no such job")
    sent = int(last_event_id) + 1 if last_event_id and last_event_id.isdigit() else 0

    def gen():
        nonlocal sent
        beat = time.monotonic()
        deadline = beat + 1800
        while time.monotonic() < deadline:
            while sent < len(job.events):
                e = job.events[sent]
                yield f"id: {e['id']}\nevent: {e['event']}\ndata: {json.dumps(e['data'])}\n\n"
                sent += 1
            if job.status in ("done", "error") and sent >= len(job.events):
                return
            if time.monotonic() - beat >= 2 and job.started_at is not None:
                beat = time.monotonic()
                yield f"event: progress\ndata: {json.dumps({'job_id': job.job_id, 'elapsed_seconds': round(beat - job.started_at, 1)})}\n\n"
            time.sleep(0.2)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.get("/{experiment_id}")
def get_experiment(experiment_id: str = Path(..., pattern=CAPTURE_ID_PATTERN, max_length=200),
                   scope: TenantScope = Depends(get_tenant_scope)) -> Dict[str, Any]:
    """Experiment/setup/result/metrics exactly as stored. The record has no hypothesis field, so none is invented."""
    exp, metrics = _load(scope, experiment_id)
    return {
        "experiment": {"experiment_id": exp.experiment_id, "dataset_version": exp.dataset_version, "code_version": exp.code_version,
                       "random_seed": exp.random_seed, "timestamp": exp.timestamp.isoformat(), "environment": exp.environment},
        "hypothesis": None,
        "setup": {"configuration": exp.configuration, "parameters": exp.parameters},
        "result": exp.results,
        "metrics": [m.model_dump(mode="json") for m in metrics],
    }
