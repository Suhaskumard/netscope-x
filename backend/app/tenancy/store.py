"""Tenant registry (spec Phase 91): tenant ids and SHA-256-hashed API keys, never the keys themselves."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from pathlib import Path
from typing import Optional

from backend.app.tenancy.ids import validate_tenant_id
from backend.app.tenancy.paths import tenant_inbox


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


class TenantRegistry:
    def __init__(self, artifact_root: Path) -> None:
        self._artifact_root = artifact_root
        self._path = artifact_root / "_tenants" / "registry.json"

    def _load(self) -> dict[str, str]:
        if not self._path.is_file():
            return {}
        return json.loads(self._path.read_text(encoding="utf-8"))

    def create_tenant(self, tenant_id: str) -> str:
        """Register a tenant, create its directories, and return its API key (shown once)."""
        validate_tenant_id(tenant_id)
        tenants = self._load()
        if tenant_id in tenants:
            raise ValueError(f"tenant {tenant_id!r} already exists")
        key = secrets.token_urlsafe(32)
        tenants[tenant_id] = _hash(key)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(tenants, indent=2, sort_keys=True), encoding="utf-8")
        tenant_inbox(self._artifact_root, tenant_id).mkdir(parents=True, exist_ok=True)
        return key

    def resolve_key(self, key: str) -> Optional[str]:
        """Tenant id owning `key`, or None. Compares against every entry in constant time per entry."""
        digest = _hash(key)
        match: Optional[str] = None
        for tenant_id, stored in self._load().items():
            if hmac.compare_digest(stored, digest):
                match = tenant_id
        return match
