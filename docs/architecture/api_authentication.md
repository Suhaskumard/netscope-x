# API Authentication and Authorization (Phase 92)

Code: `backend/app/auth/`. Off by default (`NETSCOPE_AUTH_ENABLED`); when off, behavior is exactly pre-Phase-92.

## Rules (when enabled)
- `Authorization: Bearer <token>` on every `/api/v1` route (`get_principal` is a router-level dependency, so a new
  route cannot forget it). Missing/malformed/unknown/revoked/expired -> 401 with `WWW-Authenticate: Bearer`.
- Roles: `reader` (GET/HEAD/OPTIONS), `operator` (everything). Insufficient role -> 403.
- Credentials live in `<artifact_root>/_auth/credentials.json`: id, SHA-256 of the random token (shown once), role,
  optional tenant binding, expiry, revoked flag.
- With tenancy on (Phase 91), the credential's `tenant_id` selects the tenant root; `X-Tenant-Key` is ignored and a
  credential with no tenant is refused (401).
- `/health`, `/docs`, `/redoc`, `/openapi.json` are outside `/api/v1` and stay public (liveness / API description).

## Verified (`backend/tests/test_auth.py`, 32 tests)
Routes are enumerated from the live app (not hand-listed): every route rejects 5 kinds of bad credentials with 401;
every write route gives a reader 403; operators and readers pass auth on their routes; revoked/expired tokens 401;
a full capture -> flows -> topology -> experiments -> 404 -> 501 sequence gives identical statuses and bodies with
auth on (operator token) vs off (only wall-clock `generated_at` and `request_id` are excluded).

## Limits (not claimed)
- Static bearer tokens: no login flow, OAuth/JWT, rotation endpoint, rate limiting/lockout or audit log; no HTTPS
  enforcement (deploy behind TLS). Credentials are managed in code/scripts, not via API.
- Only two roles. Credential file is not safe under concurrent writes.
- Token lookup reads the credential file per request (fine at this scale, not optimized).
