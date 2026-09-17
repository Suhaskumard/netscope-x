"""Structured logging (spec Phase 07; NFR-5).

`configure_logging()` installs a JSON formatter and a filter that injects
the current request_id/experiment_id (backend.app.core.context) into every
log record. `get_logger(name)` is the standard entry point for module-level
logging -- every module logs via its own named logger, never the root
logger directly, so log output is always attributable to its source module.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any, Dict

from backend.app.core.context import get_experiment_id, get_request_id

_CONFIGURED = False


class ContextFilter(logging.Filter):
    """Injects the current request_id/experiment_id into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        record.experiment_id = get_experiment_id()
        return True


class JsonFormatter(logging.Formatter):
    """Renders each log record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None),
            "experiment_id": getattr(record, "experiment_id", None),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        extra_fields = getattr(record, "extra_fields", None)
        if extra_fields:
            payload.update(extra_fields)

        return json.dumps(payload, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    """Idempotent: safe to call multiple times (e.g. once per test), configures only once."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(ContextFilter())

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = [handler]

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Module-level logger. Callers should pass __name__."""
    configure_logging()
    return logging.getLogger(name)


def log_exception(logger: logging.Logger, message: str, **extra_fields: Any) -> None:
    """Structured error reporting (spec Phase 07 'error reporting').

    Must be called from within an `except` block so exc_info is available;
    the resulting record includes type, message, and full stack trace via
    JsonFormatter's `exception` field, never a bare unstructured traceback.
    """
    logger.error(message, exc_info=True, extra={"extra_fields": extra_fields})
