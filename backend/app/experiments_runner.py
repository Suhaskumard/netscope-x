"""In-process job manager for live experiment runs (spec addendum Phase 102).

Safety scope of `POST /experiments`: only a whitelisted single matrix cell (topology level, completeness level, ablation and a
small seed range, all from `experiments.matrix_runner`) can be run; one job at a time process-wide; a per-tenant sliding-hour rate
limit; disabled unless `enable_experiment_runs`. The run itself is the real `run_and_persist_cell`, so what the Lab shows for it is
the same persisted record a batch run would produce.

Progress is coarse and honest: `run_and_persist_cell` is one blocking call with no internal hooks, so events are queued / started /
done|error, and the SSE stream adds elapsed-time heartbeats while it runs. Per-process state: not shared between workers.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Deque, Dict, List, Optional

from experiments.matrix_runner import ABLATIONS, OBSERVATION_COMPLETENESS_LEVELS, TOPOLOGY_LEVELS, run_and_persist_cell

MAX_JOBS = 50
SEED_MAX = 999


class RunRejected(Exception):
    def __init__(self, status: int, message: str, retry_after: Optional[int] = None) -> None:
        super().__init__(message)
        self.status, self.message, self.retry_after = status, message, retry_after


@dataclass
class Job:
    job_id: str
    tenant_key: str
    request: Dict
    status: str = "queued"  # queued | running | done | error
    experiment_id: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[float] = None
    events: List[Dict] = field(default_factory=list)

    def emit(self, kind: str, **data) -> None:
        self.events.append({"id": len(self.events), "event": kind, "data": {"job_id": self.job_id, "status": self.status, **data}})

    def snapshot(self) -> Dict:
        return {"job_id": self.job_id, "status": self.status, "request": self.request, "experiment_id": self.experiment_id,
                "error": self.error, "events": len(self.events)}


_lock = threading.Lock()
_jobs: Dict[str, Job] = {}
_starts: Dict[str, Deque[float]] = defaultdict(deque)


def reset() -> None:
    with _lock:
        _jobs.clear()
        _starts.clear()


def validate_request(topology_level: str, completeness: float, ablation: Optional[str], seed: int) -> None:
    if topology_level not in TOPOLOGY_LEVELS:
        raise ValueError(f"topology_level must be one of {sorted(TOPOLOGY_LEVELS)}")
    if completeness not in OBSERVATION_COMPLETENESS_LEVELS:
        raise ValueError(f"completeness must be one of {OBSERVATION_COMPLETENESS_LEVELS}")
    if ablation is not None and ablation not in ABLATIONS:
        raise ValueError(f"ablation must be null or one of {list(ABLATIONS)}")
    if not 0 <= seed <= SEED_MAX:
        raise ValueError(f"seed must be in 0..{SEED_MAX}")


def _work(job: Job, root: Path) -> None:
    job.status, job.started_at = "running", time.monotonic()
    job.emit("started")
    try:
        r = job.request
        cell = run_and_persist_cell(root, r["topology_level"], r["completeness"], seed=r["seed"], ablation=r["ablation"])
        job.experiment_id = cell.experiment.experiment_id
        job.status = "done"
        job.emit("done", experiment_id=job.experiment_id, run_version=cell.experiment.configuration.get("run_version"))
    except Exception as exc:  # reported to the client as a message; details are not leaked
        job.status, job.error = "error", type(exc).__name__
        job.emit("error", error=job.error)


def start_run(root: Path, tenant_key: str, request: Dict, per_hour: int, run_in_thread: bool = True) -> Job:
    validate_request(request["topology_level"], request["completeness"], request["ablation"], request["seed"])
    now = time.monotonic()
    with _lock:
        if any(j.status in ("queued", "running") for j in _jobs.values()):
            raise RunRejected(429, "an experiment run is already in progress", retry_after=5)
        window = _starts[tenant_key]
        while window and now - window[0] > 3600:
            window.popleft()
        if len(window) >= per_hour:
            raise RunRejected(429, f"run limit of {per_hour} per hour reached", retry_after=int(3600 - (now - window[0])) + 1)
        window.append(now)
        job = Job(job_id=uuid.uuid4().hex, tenant_key=tenant_key, request=dict(request))
        job.emit("queued")
        _jobs[job.job_id] = job
        while len(_jobs) > MAX_JOBS:
            oldest = next((k for k, j in _jobs.items() if j.status in ("done", "error")), None)
            if oldest is None:
                break
            del _jobs[oldest]
    if run_in_thread:
        threading.Thread(target=_work, args=(job, root), daemon=True).start()
    else:
        _work(job, root)
    return job


def get_job(job_id: str, tenant_key: str) -> Optional[Job]:
    job = _jobs.get(job_id)
    return job if job is not None and job.tenant_key == tenant_key else None
