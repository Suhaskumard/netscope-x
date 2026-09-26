# High-Availability Deployment (Phase 93)

Code: `backend/app/storage/replicated.py`, replication middleware in `backend/app/main.py`. Off unless
`NETSCOPE_REPLICA_ROOTS` is set.

## Design
- Every artifact write is atomic (`atomic_write_bytes`: temp + fsync + `os.replace`) in `experiments/artifacts/io.py`
  and `capture/ingest.py`; a killed process never leaves a partial file.
- After a write request (non-GET, or `/topology` which persists its graph), and before returning 2xx, the request's
  tenant root is committed to every replica: data files first, then manifests/`.sha256` markers, each copied
  atomically and hashed; `_replication/hashes.json` in each root records the sha256 of each committed file.
  Fewer than `NETSCOPE_REPLICA_MIN_WRITES` (default: all) replicas reached -> HTTP 503, never a false success.
- Startup runs `repair()`: fills missing copies, overwrites copies that disagree with their recorded hash from the
  newest good copy, and reports files with no good copy (`unrecoverable`).
- Replicated deployment: instance A writes root A and mirrors to B; instance B the reverse (`docker-compose.ha.yml`).
  Each instance alone holds every acknowledged artifact.
- Experiments: the hash-protected manifest is written last and is the commit point; a `v<N>/` directory without a
  manifest entry (interrupted run) is an orphan and is removed when that version is retried.

## Verified (real processes, `backend/tests/test_ha_failover.py`, 3/3 runs)
Two uvicorn instances; A is hard-killed after the first of two files of an in-flight capture reached B. Result: the
killed request was never acknowledged; B still serves every acknowledged capture byte-identically; B holds only a
byte-identical prefix of the in-flight capture (no temp or truncated file); B accepts new writes; restarting A repairs
both roots to identical content and the interrupted capture becomes complete and servable. 9 unit tests cover replication,
corruption/missing-file repair, quorum failure, ordering and atomic-write interruption.

## Limits (not claimed)
- Not consensus: assumes one writer per file. Concurrent writers to the same path last-write-wins; topology rewrites
  (same capture, new `generated_at`) on two instances can leave differing copies until repair picks the newer.
- A file interrupted mid-commit stays on the peer without its manifest until the writer restarts (or another
  repair runs); unacknowledged partial *sets* (data without manifest) are possible, partial *files* are not.
- Derived files written by GET routes other than `/topology` (flows/packets jsonl) are not replicated (regenerable).
- Reads are not hash-verified per request; corruption is found by `verify()`/startup `repair()`. `read_path` exists but
  is not wired into routes. Replicas only protect against host loss if they live on separate hosts/volumes.
- Auth/tenant registry files (`_auth`, `_tenants`) live under the artifact root but are written outside requests, so
  they are replicated only on the next commit of the whole root / startup repair.
- The compose file and nginx proxy were not run here; the proxy is itself a single point of failure.
