"""Credential registry (spec Phase 92): hashed bearer tokens with a role, optional tenant binding, expiry, revocation."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

Role = Literal["reader", "operator"]
ROLE_RANK = {"reader": 1, "operator": 2}


@dataclass(frozen=True)
class Principal:
    credential_id: str
    role: Role
    tenant_id: Optional[str]


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class CredentialStore:
    def __init__(self, artifact_root: Path) -> None:
        self._path = artifact_root / "_auth" / "credentials.json"

    def _load(self) -> dict[str, dict]:
        return json.loads(self._path.read_text(encoding="utf-8")) if self._path.is_file() else {}

    def _save(self, data: dict[str, dict]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

    def create(
        self,
        credential_id: str,
        role: Role,
        tenant_id: Optional[str] = None,
        expires_at: Optional[datetime] = None,
    ) -> str:
        """Register a credential and return its bearer token (shown once, stored only as SHA-256)."""
        if role not in ROLE_RANK:
            raise ValueError(f"unknown role {role!r}")
        data = self._load()
        if credential_id in data:
            raise ValueError(f"credential {credential_id!r} already exists")
        token = secrets.token_urlsafe(32)
        data[credential_id] = {
            "hash": _hash(token),
            "role": role,
            "tenant_id": tenant_id,
            "revoked": False,
            "expires_at": expires_at.isoformat() if expires_at else None,
        }
        self._save(data)
        return token

    def revoke(self, credential_id: str) -> None:
        data = self._load()
        data[credential_id]["revoked"] = True
        self._save(data)

    def authenticate(self, token: str, now: Optional[datetime] = None) -> Optional[Principal]:
        """The principal for a valid, unrevoked, unexpired token; else None."""
        digest, found = _hash(token), None
        for cid, rec in self._load().items():
            if hmac.compare_digest(rec["hash"], digest):
                found = (cid, rec)
        if found is None or found[1]["revoked"]:
            return None
        cid, rec = found
        if rec["expires_at"] and datetime.fromisoformat(rec["expires_at"]) <= (now or datetime.now(timezone.utc)):
            return None
        return Principal(cid, rec["role"], rec["tenant_id"])
