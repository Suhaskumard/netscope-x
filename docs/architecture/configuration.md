# NETSCOPE-X — Configuration and Secrets

Phase 08 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 08 — CONFIGURATION AND
SECRETS"). Implements `.env.example`, environment configuration, validation, secret handling, and
development/test/prod configuration. Code: `backend/app/core/config.py`. Verified by
`backend/tests/test_config.py` (9 tests, all passing).

## Design

`Settings` (`pydantic_settings.BaseSettings`) reads every variable with an `NETSCOPE_` prefix, so
arbitrary unrelated environment variables already present on a developer's machine can never
accidentally feed into the app's configuration. Fields:

| Field | Type | Default | Validation |
|---|---|---|---|
| `environment` | `Literal["development","test","production"]` | `"development"` | Pydantic literal enforcement |
| `log_level` | `str` | `"INFO"` | Must be a real `logging` level name (`_validate_log_level`) |
| `api_host` | `str` | `"0.0.0.0"` | — |
| `api_port` | `int` | `8000` | `1 <= port <= 65535` |
| `secret_key` | `SecretStr` | insecure placeholder | Never rendered in `repr()`/`str()`; see below |

### Environment-specific configuration (dev/test/prod)

`get_settings()` reads `NETSCOPE_ENVIRONMENT` (or an explicit override) and looks for
`.env.{environment}` first, falling back to a plain `.env`. This session's repo has:
- `.env.example` — committed template with safe placeholder values, documenting every variable for a
  developer to copy to `.env`.
- `.env.test` — committed (safe: no secrets, just quieter logging and a distinct port for test runs),
  actually loaded and exercised by `test_env_test_file_is_picked_up_for_test_environment`.
- `.env` / `.env.production` — gitignored; never committed, per spec's explicit "no secrets in source
  control" rule.

### Secret handling

`secret_key` is a `pydantic.SecretStr`, not a plain `str` — Pydantic guarantees it never appears in
plain text when the model is printed, logged, or otherwise serialized by accident (verified by
`test_secret_never_appears_in_repr_or_str`). Beyond just typing it as a secret, a `model_validator`
actively **refuses to construct** a `Settings` object where `environment == "production"` and
`secret_key` still holds the documented insecure placeholder value — this makes "forgot to set a real
production secret" a hard startup failure, not a silent security gap (verified by
`test_production_rejects_placeholder_secret` / `test_production_accepts_real_secret`).

## Verification performed this phase

- `pip install` picked up the new `pydantic-settings==2.6.1` pin cleanly (no conflicts with the
  existing pinned stack).
- `pytest backend/tests/test_config.py` — 9/9 passed: defaults load; invalid `log_level`/`api_port`
  rejected; env-var overrides honored; production placeholder-secret rejection and real-secret
  acceptance; secret never leaks via `repr`/`str`; `.env.test` actually loaded for the test
  environment.
- `pytest backend/tests` (full suite, 22 tests) — all passed, no regression from Phases 06/07.
- Confirmed via `ls -la .env*` that only `.env.example` and `.env.test` exist in the working tree —
  no real `.env` was ever created or committed during this phase.
- `backend/app/main.py` now derives its logging level from `get_settings()` instead of a hardcoded
  constant — a real integration point, not just an unused standalone module.

## Known limitations

- Only one secret field (`secret_key`) exists so far, since no feature yet needs one (no auth, no
  external API keys). The pattern (SecretStr + production-guard validator) is established and ready to
  extend when a real secret-consuming feature arrives, rather than speculatively adding fields for
  secrets nothing uses yet.
- `.env.production` is documented as the expected filename for production configuration but no such
  file exists (correctly — it would contain a real secret and must never be committed). Deploying to a
  real production environment will require that file (or equivalent env-var injection) to be created
  out-of-band, outside version control.

## Status

This document, together with `backend/app/core/config.py`, `.env.example`, `.env.test`, and
`backend/tests/test_config.py`, satisfies Phase 08.
