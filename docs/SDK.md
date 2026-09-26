# NETSCOPE-X Client SDKs (Phase 96)

Python (`sdk/python/netscope_client`, stdlib only) and JavaScript (`sdk/javascript`, ESM, zero dependencies, Node >= 18 or a
browser with `fetch`) wrappers over the versioned REST API (`/api/v1`, `docs/API.md`). Responses are the server's JSON,
unmodified (plain dicts / objects). Both pin the `/api/v1` prefix.

```python
from netscope_client import NetscopeClient
c = NetscopeClient("http://localhost:8000", token=None, tenant_key=None)
cid = c.upload_pcap("capture.pcap")["capture_id"]        # file must already be in the server's staging dir
flows = c.flows(cid); topo = c.topology(cid); deps = c.dependencies(cid)
for f in c.paginate("flows", cid): ...
```
```js
import { NetscopeClient } from "netscope-client";
const c = new NetscopeClient("http://localhost:8000", { token, tenantKey });
const { capture_id } = await c.uploadPcap("capture.pcap");
for await (const f of c.paginate("flows", capture_id)) { /* ... */ }
```

Methods (JS names are camelCase): `capture` / `upload_pcap` / `upload_netflow`, `flows`, `topology`, `dependencies`, `causal`,
`history`, `experiments`, `metrics`, `anomalies`, `behavior`, `simulate`, `counterfactual`, `create_experiment`, `paginate`.
Auth: `token` sends `Authorization: Bearer`; `tenant_key` sends `X-Tenant-Key` (ignored by the server when the credential
names the tenant).

## Errors
Every non-2xx reply becomes an exception carrying `error`, `detail`, `request_id` (the server's `ErrorResponse`):
422 `ValidationError`, 401 `AuthenticationError`, 403 `AuthorizationError`, 404 `NotFoundError`, 501 `NotImplementedOnServer`
(anomalies, behaviors, simulation, counterfactual and POST experiments validate input but are not wired server-side; the SDK
exposes them and surfaces the 501 rather than hiding it), anything else `ServerError`.
Reads (GET) are retried on connection errors and 502/503/504 with exponential backoff (default 2 retries); writes are never retried.

## Verified against a real server (`python -m scripts.run_sdk_e2e`, `backend/tests/test_sdk.py`)
A real uvicorn subprocess, real sockets, a real scapy pcap; no TestClient or mock transport. 28/28 checks:
- Open mode: capture, flows, topology, dependencies, causal, history, experiments, metrics through the Python SDK equal raw
  `httpx` requests to the same server (topology/causal compared ignoring the per-request `generated_at`/`computed_at` stamps);
  flow count equals `reconstruct_flows` on the artifacts the server wrote; `paginate` yields every flow; 404/422/501 and a
  missing dependency map to the right exception with `error` and `request_id` populated.
- The JavaScript SDK, run under `node`, produces the same flows/dependencies/topology as the Python SDK and the same error
  classes/statuses.
- Auth + tenancy on: no/bad token -> 401; reader POST -> 403; reader GET allowed; a second tenant cannot read the first
  tenant's capture (404) through either SDK; a missing token is rejected in JS.

## Limits
Blocking Python client only (no async), no typed models (dicts), not published to PyPI/npm, the JS package is exercised on
Node only (not in a browser), no file upload (the API takes a filename already in the server's staging directory), and the
SDK does not negotiate API versions beyond pinning `/api/v1`.
