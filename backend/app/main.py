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

from starlette.middleware.base import RequestResponseEndpoint

from fastapi import FastAPI, Request, Response

from backend.app.api.errors import register_exception_handlers
from backend.app.api.router import api_router
from backend.app.core.config import get_settings
from backend.app.core.context import request_context
from backend.app.core.logging import configure_logging, get_logger
from backend.app.core.timing import Timer

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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
