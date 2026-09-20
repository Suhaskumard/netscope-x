"""GET /metrics. Backing implementation: spec Phase 68 (Complete Research Validation) --
every returned MetricResult traces to a real experiment_id (spec §21, no fake metrics):
each is read back from a real `Experiment`'s own `metrics.jsonl`, written only by
`experiments/matrix_runner.py::persist_cell` after that experiment actually ran."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from backend.app.api.schemas import PageParams, PaginatedResponse, get_page_params
from backend.app.core.config import get_settings
from backend.app.models import MetricContext, MetricResult
from experiments.artifacts.io import read_jsonl
from experiments.artifacts.paths import metrics_path

router = APIRouter(prefix="/metrics", tags=["metrics"])


def _list_metrics(root, context: Optional[MetricContext]) -> list[MetricResult]:
    experiments_dir = root / "experiments"
    if not experiments_dir.is_dir():
        return []
    metrics: list[MetricResult] = []
    for experiment_id in sorted(p.name for p in experiments_dir.iterdir() if p.is_dir()):
        path = metrics_path(root, experiment_id)
        if not path.is_file():
            continue
        for metric in read_jsonl(path, MetricResult):
            if context is None or metric.context == context:
                metrics.append(metric)
    return metrics


@router.get("", response_model=PaginatedResponse[MetricResult])
def list_metrics(
    context: Optional[MetricContext] = Query(default=None),
    page: PageParams = Depends(get_page_params),
) -> PaginatedResponse[MetricResult]:
    settings = get_settings()
    metrics = _list_metrics(settings.artifact_root, context)
    page_items = metrics[page.offset : page.offset + page.limit]
    return PaginatedResponse[MetricResult](
        items=page_items, limit=page.limit, offset=page.offset, total=len(metrics)
    )
