# Multi-Tenant Network Isolation (Phase 91)

Per-tenant captures and artifact storage with an access boundary at the API. Code: `backend/app/tenancy/`.

## Boundary
- `NETSCOPE_TENANCY_ENABLED=true` turns it on (default off: single global root, behavior unchanged).
- Every `/api/v1` route depends on `get_tenant_scope` (`tenancy/deps.py`, applied in `api/router.py`). The
  `X-Tenant-Key` header must match a registered tenant, else 401 (`tenant_access_denied`).
- A tenant's data lives under `<artifact_root>/tenants/<tenant_id>/` (captures, topology, snapshots, experiments)
  and its staged uploads under `.../inbox`. Routes receive that root instead of the global one, so a capture id
  from another tenant simply does not exist for the caller (404, same as a missing id - no existence leak).
- Tenant ids are `^[a-z0-9][a-z0-9_-]{1,62}$` and the resolved root is asserted to stay under `tenants/`.
- Keys are random (`secrets.token_urlsafe(32)`), returned once, stored only as SHA-256 in `_tenants/registry.json`.

## Tested directly (`backend/tests/test_tenant_isolation.py`)
Two tenants through the real API: B cannot read A's flows/topology (404), cannot ingest A's staged pcap (422),
A's directory tree hash is unchanged by B's requests, missing/wrong keys get 401 on every route tested.

## Limits (not claimed)
- Not full authn/authz: one static key per tenant, no roles, expiry, rotation or rate limits (Phase 92).
- Filesystem isolation in one process on one host: no OS/container separation, no quotas, so a noisy tenant can
  exhaust shared disk/CPU. The `_tenants` registry is not concurrency-safe under simultaneous tenant creation.
- Twins: no twin persistence path exists under the artifact root today (twins are built in memory by
  `backend/digital_twin`), so there is no twin storage to scope; twin isolation is by construction of the
  caller's own inputs only, not enforced here. Anomalies/behaviors/simulation/counterfactual routes are 501
  stubs; they require a valid key but hold no data.
- The `experiments` listing reads only the caller's tenant root; matrix runs written by scripts go to whatever
  root they are given.
