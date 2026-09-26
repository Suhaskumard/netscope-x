"""Per-tenant filesystem layout (spec Phase 91): <artifact_root>/tenants/<tenant_id>/{captures,...,inbox}."""

from __future__ import annotations

from pathlib import Path

from backend.app.tenancy.ids import validate_tenant_id


def tenant_root(artifact_root: Path, tenant_id: str) -> Path:
    """The tenant's private artifact root; asserted to stay inside <artifact_root>/tenants."""
    validate_tenant_id(tenant_id)
    base = (artifact_root / "tenants").resolve()
    root = (base / tenant_id).resolve()
    if root.parent != base:
        raise ValueError("tenant root escapes the tenants directory")
    return root


def tenant_inbox(artifact_root: Path, tenant_id: str) -> Path:
    """Per-tenant upload staging dir, so a tenant can only ingest pcaps staged for it."""
    return tenant_root(artifact_root, tenant_id) / "inbox"
