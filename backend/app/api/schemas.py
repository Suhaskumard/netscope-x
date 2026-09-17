"""Cross-cutting API schemas (spec Phase 09; API DESIGN PRINCIPLES).

Every endpoint in backend/app/api/routes/ uses these for pagination and
error responses, so the whole API has exactly one pagination shape and
exactly one error shape -- never a bespoke format per endpoint.
"""

from __future__ import annotations

from typing import Generic, List, Optional, TypeVar

from fastapi import Query
from pydantic import BaseModel, Field

T = TypeVar("T")


class ErrorResponse(BaseModel):
    """The one error shape every 4xx/5xx response in this API uses.

    `detail` must never contain a raw exception message or stack trace for
    unhandled (5xx) errors -- see backend/app/api/errors.py. `request_id`
    lets a client correlate a failed response with server-side structured
    logs (spec Phase 07).
    """

    error: str = Field(..., description="Short, stable machine-readable error code.")
    detail: str = Field(..., description="Human-readable explanation, safe to show a client.")
    request_id: Optional[str] = Field(default=None)


class PageParams(BaseModel):
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


def get_page_params(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> PageParams:
    return PageParams(limit=limit, offset=offset)


class PaginatedResponse(BaseModel, Generic[T]):
    items: List[T]
    limit: int
    offset: int
    total: int
