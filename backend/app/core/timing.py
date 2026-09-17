"""Performance timing (spec Phase 07; feeds PERF-1..7 measurements).

`Timer` and `@timed` both emit one structured log line per measured
operation (module, operation name, duration_ms) via the same JSON
formatter as the rest of the observability framework -- timing data is
never printed ad hoc, so it can be grepped/aggregated consistently.
"""

from __future__ import annotations

import functools
import logging
import time
from types import TracebackType
from typing import Any, Callable, Optional, Type, TypeVar

from backend.app.core.logging import get_logger

F = TypeVar("F", bound=Callable[..., Any])

_logger = get_logger(__name__)


class Timer:
    """Context manager measuring wall-clock duration of the enclosed block.

    Usage:
        with Timer("flow_reconstruction", logger=my_logger) as t:
            ...
        # t.duration_ms is available after the block exits
    """

    def __init__(self, operation: str, logger: Optional[logging.Logger] = None) -> None:
        self.operation = operation
        self.logger = logger or _logger
        self.duration_ms: Optional[float] = None
        self._start: float = 0.0

    def __enter__(self) -> "Timer":
        self._start = time.perf_counter()
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        self.duration_ms = (time.perf_counter() - self._start) * 1000.0
        self.logger.info(
            f"{self.operation} completed",
            extra={"extra_fields": {"operation": self.operation, "duration_ms": self.duration_ms}},
        )


def timed(operation: Optional[str] = None) -> Callable[[F], F]:
    """Decorator form of Timer, for timing an entire function call."""

    def decorator(func: F) -> F:
        op_name = operation or func.__qualname__

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with Timer(op_name, logger=get_logger(func.__module__)):
                return func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator
