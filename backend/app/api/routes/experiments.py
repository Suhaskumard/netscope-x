"""GET/POST /experiments. Backing implementation: spec Phase 67-68 (Automatic Experiment
Generator, Complete Research Validation)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.app.api.errors import NotYetImplemented
from backend.app.api.schemas import PageParams, PaginatedResponse, get_page_params
from backend.app.models import Experiment

router = APIRouter(prefix="/experiments", tags=["experiments"])


@router.get("", response_model=PaginatedResponse[Experiment])
def list_experiments(page: PageParams = Depends(get_page_params)) -> PaginatedResponse[Experiment]:
    raise NotYetImplemented("experiment runner (spec Phase 67-68)")


@router.post("", response_model=Experiment, status_code=202)
def create_experiment(experiment: Experiment) -> Experiment:
    raise NotYetImplemented("experiment runner (spec Phase 67-68)")
