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

    # Phase 30 -- edge confidence scoring (ties to NFR-4, FR-1.10's "not-arbitrary" intent).
    edge_confidence_packet_scale: float = Field(
        default=20.0,
        gt=0,
        description=(
            "Saturation scale for edge confidence = 1 - exp(-total_packet_count / scale); "
            "at total_packet_count == scale, confidence is ~0.63, approaching but never "
            "reaching 1.0 as more packets are observed between a node pair (spec FR-1.10). "
            "A provisional default pending real calibration (spec Phase 31/68), not a "
            "claimed-accurate value."
        ),
    )

    # Phase 31 -- multi-signal edge confidence (ties to NFR-4, FR-1.10's "not-arbitrary" intent).
    edge_confidence_signal_strength: float = Field(
        default=0.3,
        gt=0,
        lt=1,
        description=(
            "Noisy-OR evidence strength applied uniformly to each corroborating edge "
            "signal (TCP handshake completion, protocol fingerprinting, TLS negotiation, "
            "five-tuple persistence, bidirectionality) on top of the packet-volume term "
            "(spec Phase 31, FR-1.10). Uniform because no empirical basis yet justifies "
            "weighting one signal above another -- that is Phase 32/68's job, not invented "
            "here. A provisional default pending real calibration, not a claimed-accurate "
            "value."
        ),
    )

    # Phase 51 -- dependency strength estimation (ties to NFR-4, FR-1.26).
    dependency_frequency_scale: float = Field(
        default=1.0,
        gt=0,
        description=(
            "Saturation scale for dependency strength's frequency term = "
            "1 - exp(-frequency / scale); at frequency == scale, the term is ~0.63, "
            "approaching but never reaching 1.0 as communication frequency grows (spec "
            "FR-1.26). A provisional default pending real calibration (spec Phase 68), not "
            "a claimed-accurate value."
        ),
    )
    dependency_persistence_scale: float = Field(
        default=60.0,
        gt=0,
        description=(
            "Saturation scale (seconds) for dependency strength's persistence term = "
            "1 - exp(-persistence_seconds / scale) (spec FR-1.26). A provisional default "
            "pending real calibration (spec Phase 68), not a claimed-accurate value."
        ),
    )
    dependency_signal_strength: float = Field(
        default=0.3,
        gt=0,
        lt=1,
        description=(
            "Noisy-OR evidence strength applied uniformly to dependency strength's "
            "secondary signals (persistence, directionality, traffic characteristics) on "
            "top of the frequency term (spec Phase 51, FR-1.26). Uniform for the same "
            "reason `edge_confidence_signal_strength` is: no empirical basis yet justifies "
            "weighting one signal above another -- that is Phase 68's job, not invented "
            "here. A provisional default pending real calibration, not a claimed-accurate "
            "value."
        ),
    )

    # Phase 52 -- temporal precedence analysis (ties to NFR-4, FR-1.27).
    dependency_temporal_bucket_seconds: float = Field(
        default=10.0,
        gt=0,
        description=(
            "Fixed time-bucket width for time-lagged cross-correlation of per-node flow "
            "activity (spec Phase 52, FR-1.27), mirroring Phase 34's short-window default. "
            "A provisional default pending real calibration (spec Phase 68), not a "
            "claimed-accurate value."
        ),
    )
    dependency_temporal_max_lag_buckets: int = Field(
        default=5,
        ge=1,
        description=(
            "Bounded number of positive lag offsets searched for the best time-lagged "
            "cross-correlation (spec Phase 52, FR-1.27; algorithm_selection.md section 6's "
            "own complexity note: 'a bounded set of lag offsets'). A provisional default "
            "pending real calibration (spec Phase 68), not a claimed-accurate value."
        ),
    )

    # Phase 34 -- multi-window behavior modeling (ties to NFR-4, FR-1.12).
    behavior_window_short_seconds: float = Field(
        default=10.0,
        gt=0,
        description=(
            "Trailing-window length for 'short' behavioral observation (spec Phase 34, "
            "ObservationWindow.SHORT), anchored on a node's own latest observed flow "
            "activity, not calendar time. Matches this lab's own real, exercised capture "
            "duration (simulator/capture/live.py's default `--duration`), not an arbitrary "
            "guess."
        ),
    )
    behavior_window_medium_seconds: float = Field(
        default=60.0,
        gt=0,
        description=(
            "Trailing-window length for 'medium' behavioral observation (spec Phase 34, "
            "ObservationWindow.MEDIUM). Matches the scale simulator/tests/test_patterns.py "
            "already needs for burst/periodic traffic patterns to complete multiple cycles."
        ),
    )
    behavior_window_long_seconds: float = Field(
        default=300.0,
        gt=0,
        description=(
            "Trailing-window length for 'long' behavioral observation (spec Phase 34, "
            "ObservationWindow.LONG). Unlike short/medium, this has no direct supporting "
            "evidence in this repo's own captures/tests (all of which run under a minute) -- "
            "an explicit extrapolation, provisional pending real multi-minute lab data, not "
            "a claimed-accurate value."
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

    @model_validator(mode="after")
    def _behavior_windows_strictly_nested(self) -> "Settings":
        if not (
            self.behavior_window_short_seconds
            < self.behavior_window_medium_seconds
            < self.behavior_window_long_seconds
        ):
            raise ValueError(
                "behavior_window_{short,medium,long}_seconds must be strictly increasing -- "
                "Phase 34's nested-window design (long superset of medium superset of short) "
                "depends on this ordering"
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
