"""Consistent error handling (spec Phase 09; API DESIGN PRINCIPLES:
"avoid leaking internal exceptions", "return consistent errors").

Five cases, all rendered through the same ErrorResponse envelope:
1. NotYetImplemented -- a real, validated endpoint whose backing pipeline
   stage doesn't exist yet (spec Phase 21+). Maps to 501.
2. RequestValidationError -- FastAPI/Pydantic input validation failure.
   Maps to 422, but re-rendered in ErrorResponse shape instead of
   FastAPI's default {"detail": [...]} format, so callers see one error
   shape regardless of failure type.
3. InvalidPcapError (spec Phase 21) -- a pcap_upload capture request whose
   file does not parse as a real, non-empty pcap. Maps to 422.
4. UnauthorizedInterfaceError (spec Phase 21) -- a live_interface capture
   request targeting an interface outside the authorized allowlist (spec
   §5 Safety Boundary). Maps to 403.
5. Any other unhandled Exception -- logged with full detail via the
   observability framework (Phase 07), but the client only ever sees a
   generic message plus request_id, never the raw exception text.
"""

from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend.app.api.schemas import ErrorResponse
from backend.app.core.context import get_request_id
from backend.app.core.logging import get_logger, log_exception
from backend.nettrace.capture.errors import InvalidPcapError, UnauthorizedInterfaceError

logger = get_logger(__name__)


class NotYetImplemented(Exception):
    """Raised by a route whose contract is defined but whose implementation
    (a pipeline stage from Phase 21+) does not exist yet."""

    def __init__(self, feature: str) -> None:
        self.feature = feature
        super().__init__(f"{feature} is not implemented yet")


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(NotYetImplemented)
    async def _not_yet_implemented_handler(request: Request, exc: NotYetImplemented) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            content=ErrorResponse(
                error="not_implemented",
                detail=f"{exc.feature} is not implemented yet.",
                request_id=get_request_id(),
            ).model_dump(),
        )

    @app.exception_handler(InvalidPcapError)
    async def _invalid_pcap_handler(request: Request, exc: InvalidPcapError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=ErrorResponse(
                error="invalid_pcap",
                detail=str(exc),
                request_id=get_request_id(),
            ).model_dump(),
        )

    @app.exception_handler(UnauthorizedInterfaceError)
    async def _unauthorized_interface_handler(request: Request, exc: UnauthorizedInterfaceError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content=ErrorResponse(
                error="unauthorized_interface",
                detail=str(exc),
                request_id=get_request_id(),
            ).model_dump(),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=ErrorResponse(
                error="validation_error",
                detail="Request validation failed. See server logs for field-level detail.",
                request_id=get_request_id(),
            ).model_dump(),
        )

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        log_exception(logger, "unhandled exception", path=str(request.url.path))
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=ErrorResponse(
                error="internal_error",
                detail="An internal error occurred. Reference request_id when reporting this.",
                request_id=get_request_id(),
            ).model_dump(),
        )
