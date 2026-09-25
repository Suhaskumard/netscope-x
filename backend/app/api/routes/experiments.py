"""GET/POST /experiments. Backing implementation: spec Phase 68 (Complete Research
Validation) for `GET /experiments`; `POST /experiments` stays a 501 stub -- triggering
arbitrary matrix computation synchronously through a public HTTP endpoint is a different,
riskier concern than reading back already-persisted results, the same reasoning that has
kept `POST /simulation`/`POST /counterfactual` unwired even after their engines were built
(Phase 59-66)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.app.api.errors import NotYetImplemented
from backend.app.api.schemas import PageParams, PaginatedResponse, get_page_params
from backend.app.core.config import get_settings
from backend.app.models import Experiment
from experiments.artifacts.io import read_experiment_run
from experiments.artifacts.paths import experiment_manifest_path, experiment_path

router = APIRouter(prefix="/experiments", tags=["experiments"])


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


@router.get("", response_model=PaginatedResponse[Experiment])
def list_experiments(page: PageParams = Depends(get_page_params)) -> PaginatedResponse[Experiment]:
    settings = get_settings()
    experiments = _list_experiments(settings.artifact_root)
    page_items = experiments[page.offset : page.offset + page.limit]
    return PaginatedResponse[Experiment](
        items=page_items, limit=page.limit, offset=page.offset, total=len(experiments)
    )


@router.post("", response_model=Experiment, status_code=202)
def create_experiment(experiment: Experiment) -> Experiment:
    raise NotYetImplemented("live experiment triggering via API (spec Phase 68+)")
