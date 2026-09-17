"""Phase 06 placeholder FastAPI app, now wired with the Phase 07
observability framework: request-ID middleware, structured logging, and
per-request timing. The actual API surface (/capture, /flows, /topology,
...) is designed and built in Phase 09 -- this file will be replaced, not
extended in place, when that phase starts.
"""

from starlette.middleware.base import RequestResponseEndpoint

from fastapi import FastAPI, Request, Response

from backend.app.core.context import request_context
from backend.app.core.logging import configure_logging, get_logger
from backend.app.core.timing import Timer

configure_logging()
logger = get_logger(__name__)

app = FastAPI(title="NETSCOPE-X (Phase 06 placeholder)")


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
