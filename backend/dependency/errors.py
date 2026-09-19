"""Dependency-layer error types (spec Phase 56).

Mirrors `backend/nettrace/capture/errors.py`'s plain-`Exception`-subclass
convention.
"""

from __future__ import annotations


class DependencyNotFoundError(Exception):
    """Raised when a `dependency_id` doesn't match any dependency computed
    for the given `capture_id` -- e.g. GET /causal/{dependency_id} (spec
    Phase 56) for an id nothing ever produced, or a capture with no
    ingested data at all (which produces no dependencies either)."""
