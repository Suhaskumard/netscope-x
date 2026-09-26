"""NETSCOPE-X Python client (spec Phase 96). Stdlib only; pins the /api/v1 REST surface."""

from netscope_client.client import (
    API_PREFIX,
    AuthenticationError,
    AuthorizationError,
    NetscopeClient,
    NetscopeError,
    NotFoundError,
    NotImplementedOnServer,
    ServerError,
    ValidationError,
)

__all__ = [
    "API_PREFIX", "NetscopeClient", "NetscopeError", "ValidationError", "AuthenticationError",
    "AuthorizationError", "NotFoundError", "NotImplementedOnServer", "ServerError",
]
