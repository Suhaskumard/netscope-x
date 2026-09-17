"""Request-scoped and experiment-scoped observability context.

Serves NFR-5 (docs/requirements/system_requirements.md) and spec Phase 07's
"request IDs" / "experiment IDs" requirement. Using contextvars means any
log call anywhere in the current request's call stack automatically picks
up the current request_id / experiment_id -- callers never have to thread
an id through every function signature.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Iterator, Optional

request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
experiment_id_var: ContextVar[Optional[str]] = ContextVar("experiment_id", default=None)


def new_request_id() -> str:
    return uuid.uuid4().hex


def get_request_id() -> Optional[str]:
    return request_id_var.get()


def get_experiment_id() -> Optional[str]:
    return experiment_id_var.get()


@contextmanager
def request_context(request_id: Optional[str] = None) -> Iterator[str]:
    """Bind a request_id for the duration of the `with` block, restoring the prior value after."""
    rid = request_id or new_request_id()
    token: Token = request_id_var.set(rid)
    try:
        yield rid
    finally:
        request_id_var.reset(token)


@contextmanager
def experiment_context(experiment_id: str) -> Iterator[str]:
    """Bind an experiment_id for the duration of the `with` block (spec §20 reproducibility)."""
    token: Token = experiment_id_var.set(experiment_id)
    try:
        yield experiment_id
    finally:
        experiment_id_var.reset(token)
