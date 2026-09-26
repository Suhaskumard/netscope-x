"""FastAPI dependency resolving the caller's tenant scope (spec Phase 91).

With `tenancy_enabled` off (the default) the scope is the single global root, exactly as before Phase 91.
With it on, the `X-Tenant-Key` header must name a registered tenant; every route then reads and writes only
under that tenant's root. With auth enabled (Phase 92) the credential names the tenant instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from fastapi import Depends, Header, Request

from backend.app.auth.deps import get_principal
from backend.app.auth.store import Principal

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


def get_tenant_scope(
    request: Request,
    x_tenant_key: Optional[str] = Header(default=None),
    principal: Optional[Principal] = Depends(get_principal),
) -> TenantScope:
    settings = get_settings()
    if not settings.tenancy_enabled:
        request.state.scope_root = settings.artifact_root
        return TenantScope(None, settings.artifact_root, settings.upload_staging_dir)
    if principal is not None:  # Phase 92: the credential names the tenant; X-Tenant-Key is ignored
        tenant_id = principal.tenant_id
        if tenant_id is None:
            raise TenantAccessError("credential is not bound to a tenant")
    elif not x_tenant_key:
        raise TenantAccessError("X-Tenant-Key header is required")
    else:
        tenant_id = TenantRegistry(settings.artifact_root).resolve_key(x_tenant_key)
    if tenant_id is None:
        raise TenantAccessError("unrecognized tenant key")
    request.state.scope_root = tenant_root(settings.artifact_root, tenant_id)
    return TenantScope(
        tenant_id,
        tenant_root(settings.artifact_root, tenant_id),
        tenant_inbox(settings.artifact_root, tenant_id),
    )
