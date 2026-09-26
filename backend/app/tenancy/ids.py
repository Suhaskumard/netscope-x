"""Tenant id validation (spec Phase 91). Ids become directory names, so the pattern forbids anything path-like."""

from __future__ import annotations

import re

_TENANT_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{1,62}$")


def validate_tenant_id(tenant_id: str) -> str:
    if not isinstance(tenant_id, str) or not _TENANT_ID.fullmatch(tenant_id):
        raise ValueError("tenant_id must match ^[a-z0-9][a-z0-9_-]{1,62}$")
    return tenant_id
