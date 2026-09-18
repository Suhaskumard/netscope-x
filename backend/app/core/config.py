"""Environment configuration and secret handling (spec Phase 08).

Settings are read from process environment variables prefixed `NETSCOPE_`
and, if present, a `.env.{environment}` or `.env` file. No real secret has
a production-safe default baked into source control -- `Settings` refuses
to validate with `environment="production"` while `secret_key` still holds
the documented insecure placeholder (see `_INSECURE_DEFAULT_SECRET`).
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]

# Documented, intentionally-insecure placeholder. Committing this value is
# safe precisely because it is refused outside development/test (see the
# model_validator below) -- it can never function as a real production secret.
_INSECURE_DEFAULT_SECRET = "dev-insecure-placeholder-change-me"

Environment = Literal["development", "test", "production"]


def _env_file_for(environment: str) -> Optional[Path]:
    """Prefer a per-environment file (.env.test, .env.production, ...); fall back to .env."""
    candidate = REPO_ROOT / f".env.{environment}"
    if candidate.exists():
        return candidate
    default = REPO_ROOT / ".env"
    return default if default.exists() else None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NETSCOPE_", extra="ignore")

    environment: Environment = "development"
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = Field(default=8000, ge=1, le=65535)
    secret_key: SecretStr = SecretStr(_INSECURE_DEFAULT_SECRET)

    # Phase 21 -- packet capture (spec §5 Safety Boundary; FR-1.1).
    artifact_root: Path = Field(
        default=REPO_ROOT / "experiments_data",
        description="Root for experiments/artifacts.paths-shaped output (captures/, ground_truth/, ...).",
    )
    upload_staging_dir: Path = Field(
        default=REPO_ROOT / "experiments_data" / "inbox",
        description="Where an already-uploaded pcap_filename (POST /capture, source=pcap_upload) is read from.",
    )
    # Note: the authorized live-capture interface allowlist is NOT a Settings
    # field -- it lives in backend.nettrace.capture.authorized_interfaces
    # (stdlib-only, reads NETSCOPE_AUTHORIZED_CAPTURE_INTERFACES directly),
    # so simulator/capture/live.py can share the exact same check without
    # needing Pydantic installed inside its lab container.

    # Phase 25 -- UDP session modeling (ties to NFR-4).
    udp_session_idle_timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        description=(
            "Idle-timeout splitting a UDP five-tuple's packets into separate "
            "timing-window sessions (spec FR-1.5)."
        ),
    )

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, v: str) -> str:
        level = getattr(logging, v.upper(), None)
        if not isinstance(level, int):
            raise ValueError(f"invalid log_level: {v!r}")
        return v.upper()

    @model_validator(mode="after")
    def _no_placeholder_secret_in_production(self) -> "Settings":
        if self.environment == "production" and self.secret_key.get_secret_value() == _INSECURE_DEFAULT_SECRET:
            raise ValueError(
                "NETSCOPE_SECRET_KEY must be set to a real value when NETSCOPE_ENVIRONMENT=production"
            )
        return self


@lru_cache
def get_settings(environment_override: Optional[str] = None) -> Settings:
    """Cached settings accessor. Tests should call get_settings.cache_clear() between cases."""
    environment = environment_override or os.environ.get("NETSCOPE_ENVIRONMENT", "development")
    env_file = _env_file_for(environment)
    if env_file is not None:
        return Settings(_env_file=env_file)  # type: ignore[call-arg]
    return Settings()
