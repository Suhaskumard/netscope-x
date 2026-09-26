"""NETSCOPE-X FastAPI app.

Wired with: Phase 07 observability (request-ID middleware, structured
logging, per-request timing), Phase 08 configuration (settings-driven log
level), and Phase 09 API architecture (the versioned /api/v1 router with
all 12 required endpoint groups, plus consistent error handling). Every
domain route currently raises NotYetImplemented (backend/app/api/errors.py)
because the pipeline stages that will serve real data (Phase 21+) don't
exist yet -- the contracts are real and validated, the implementations
are not, and the two are never conflated.
"""

import logging as _logging
from pathlib import Path

from starlette.middleware.base import RequestResponseEndpoint

from fastapi import FastAPI, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from backend.app.api.errors import register_exception_handlers
from backend.app.api.router import api_router
from backend.app.core.config import get_settings
from backend.app.core.context import request_context
from backend.app.core.logging import configure_logging, get_logger
from backend.app.core.timing import Timer
from backend.app.storage.replicated import QuorumError, ReplicatedStore

settings = get_settings()
configure_logging(level=getattr(_logging, settings.log_level))
logger = get_logger(__name__)

app = FastAPI(title="NETSCOPE-X")
app.include_router(api_router)
register_exception_handlers(app)


@app.middleware("http")
async def observability_middleware(request: Request, call_next: RequestResponseEndpoint) -> Response:
    with request_context() as request_id:
        with Timer(f"{request.method} {request.url.path}", logger=logger) as timer:
            logger.info(f"request started: {request.method} {request.url.path}")
            response: Response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            f"request completed: {request.method} {request.url.path} -> {response.status_code}",
            extra={
                "extra_fields": {
                    "status_code": response.status_code,
                    "duration_ms": timer.duration_ms,
                }
            },
        )
        return response


def _store() -> "ReplicatedStore | None":
    s = get_settings()
    replicas = [Path(p.strip()) for p in s.replica_roots.split(",") if p.strip()]
    if not replicas:
        return None
    return ReplicatedStore(s.artifact_root, replicas, s.replica_min_writes, s.replication_commit_delay_seconds)


@app.on_event("startup")
def _repair_on_startup() -> None:
    store = _store()
    if store is not None:
        report = store.repair()
        logger.info(f"replication repair: {report}")


@app.middleware("http")
async def replication_middleware(request: Request, call_next: RequestResponseEndpoint) -> Response:
    """Phase 93: a 2xx from a write (or topology, which persists its graph on GET) is returned only after the
    request's files are on the required replicas; otherwise the client gets 503 instead of a false success."""
    response = await call_next(request)
    store = _store()
    root = getattr(request.state, "scope_root", None)
    writes = request.method != "GET" or request.url.path.endswith("/topology")
    if store is None or root is None or not writes or response.status_code >= 400:
        return response
    try:
        await run_in_threadpool(store.commit, root)
    except (QuorumError, OSError) as exc:
        logger.error(f"replication commit failed: {exc}")
        return JSONResponse(
            status_code=503,
            content={"error": "replication_unavailable", "detail": "Result not durably replicated; retry.",
                     "request_id": response.headers.get("X-Request-ID")},
        )
    return response


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
