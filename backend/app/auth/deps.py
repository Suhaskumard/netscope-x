"""Authentication and authorization dependency (spec Phase 92), applied to every /api/v1 route.

`NETSCOPE_AUTH_ENABLED` off (default): every request is anonymous and allowed, exactly as before Phase 92.
On: `Authorization: Bearer <token>` must be a valid credential (else 401); safe methods (GET/HEAD/OPTIONS)
need role >= reader, all others role >= operator (else 403).
"""

from __future__ import annotations

from typing import Optional

from fastapi import Request

from backend.app.auth.store import ROLE_RANK, CredentialStore, Principal
from backend.app.core.config import get_settings

_SAFE = {"GET", "HEAD", "OPTIONS"}


class AuthenticationError(Exception):
    """Missing, malformed, unknown, revoked or expired credential. Maps to 401."""


class AuthorizationError(Exception):
    """Valid credential without the role the route needs. Maps to 403."""


def get_principal(request: Request) -> Optional[Principal]:
    settings = get_settings()
    if not settings.auth_enabled:
        return None
    scheme, _, token = (request.headers.get("authorization") or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AuthenticationError("a Bearer token is required")
    principal = CredentialStore(settings.artifact_root).authenticate(token.strip())
    if principal is None:
        raise AuthenticationError("invalid, revoked or expired credential")
    needed = "reader" if request.method in _SAFE else "operator"
    if ROLE_RANK[principal.role] < ROLE_RANK[needed]:
        raise AuthorizationError(f"role {principal.role!r} may not {request.method} this route (needs {needed!r})")
    return principal
