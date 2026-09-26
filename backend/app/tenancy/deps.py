"""FastAPI dependency resolving the caller's tenant scope (spec Phase 91).

With `tenancy_enabled` off (the default) the scope is the single global root, exactly as before Phase 91.
With it on, the `X-Tenant-Key` header must name a registered tenant; every route then reads and writes only
under that tenant's root. This is a tenant boundary, not full authn/authz (Phase 92).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from fastapi import Header

from backend.app.core.config import get_settings
from backend.app.tenancy.paths import tenant_inbox, tenant_root
from backend.app.tenancy.store import TenantRegistry


class TenantAccessError(Exception):
    """Missing or unrecognized tenant key. Maps to 401."""


@dataclass(frozen=True)
class TenantScope:
    tenant_id: Optional[str]
    root: Path
    inbox: Path


def get_tenant_scope(x_tenant_key: Optional[str] = Header(default=None)) -> TenantScope:
    settings = get_settings()
    if not settings.tenancy_enabled:
        return TenantScope(None, settings.artifact_root, settings.upload_staging_dir)
    if not x_tenant_key:
        raise TenantAccessError("X-Tenant-Key header is required")
    tenant_id = TenantRegistry(settings.artifact_root).resolve_key(x_tenant_key)
    if tenant_id is None:
        raise TenantAccessError("unrecognized tenant key")
    return TenantScope(
        tenant_id,
        tenant_root(settings.artifact_root, tenant_id),
        tenant_inbox(settings.artifact_root, tenant_id),
    )
