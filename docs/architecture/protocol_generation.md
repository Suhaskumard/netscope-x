# NETSCOPE-X — Protocol Workload Generator

Phase 15 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 15 — PROTOCOL WORKLOAD
GENERATOR"): "Generate realistic TCP, UDP, DNS, HTTP, TLS metadata, database, cache traffic." Code:
`simulator/traffic/protocols.py` + `generate_protocol.py`. Verified by `simulator/tests/test_protocols.py`
(8 pure unit tests) and a real run against the live Phase 11-14 lab covering all 6 protocols.

## Design: real wire-level exchanges, stdlib only

Where Phase 14 varied *temporal* shape (all as HTTP GETs), Phase 15 varies *protocol*. Every sender in
`protocols.py` performs a genuine wire-level exchange — no protocol is faked or labeled without a real
exchange backing it:

| Required protocol | Sender | Real mechanism |
|---|---|---|
| HTTP | `http_get` | Real HTTP GET via `urllib` (same as Phase 14). |
| Generic TCP | `tcp_raw_connect` | A bare TCP connect/close with no higher-layer protocol — represents traffic that isn't (yet) classified as a named application protocol. |
| UDP + DNS | `dns_query` / `build_dns_query` / `parse_dns_response` | Hand-built RFC 1035 wire-format query sent over a raw UDP socket; response header parsed for a matching transaction ID and rcode. No `dnspython` dependency. |
| Cache | `redis_ping` | Raw RESP-protocol `PING\r\n` over TCP, checking for a real `+PONG` reply. No redis client library. |
| Database | `postgres_ssl_request` / `build_postgres_ssl_request` | A real Postgres wire-protocol `SSLRequest` message (the well-known 8-byte `length=8, code=80877103` handshake initiator), reading the server's real single-byte `S`/`N` reply. No database driver or authentication needed. |
| TLS metadata | `tls_handshake` | A real TLS handshake via stdlib `ssl`, reporting the actually negotiated `tls_version`/`cipher` — metadata only, consistent with `docs/research/problem_definition.md`'s "encrypted traffic metadata only, never decrypt" stance. |

`build_dns_query`/`parse_dns_response` and `build_postgres_ssl_request` are pure functions (no
sockets), split out specifically so their wire-format correctness is unit-testable without Docker or a
live target.

## Key finding: protocol reachability is topology-dependent

Because of Phase 12's network segmentation, **no single lab container can reach every protocol's
target**:
- `dns` lives only on `edge` → reachable from `client`/`gateway`.
- `redis`/`database` live only on `data` → reachable from `api-1`/`api-2`/`worker`.
- `external-service` lives only on `external` → reachable from `api-1`/`api-2`.

This is treated as a realistic finding worth documenting, not a limitation to engineer around: it
mirrors how protocol usage is genuinely topology-dependent in real networks, which is directly
relevant to what NETSCOPE-X's future inference pipeline (Phase 26+, protocol fingerprinting) will have
to contend with. The generator is therefore run from two different containers depending on which
protocols it needs to reach: `client` (HTTP/DNS/generic-TCP, all via `gateway`/`dns` on `edge`) and
`api-1` (cache/database/TLS, via `redis`/`database`/`external-service`, since `api-1` is the only role
already spanning `app`+`data`+`external`).

## TLS-capable target

`external-service` (Phase 11) gained a second `nginx` server block on port 443, using a self-signed
certificate generated at container startup (`openssl req -x509 ...`, 1-day validity) —
`simulator/docker/external/nginx.conf`, wired via a `docker-compose.yml` command change. This is
explicitly a lab-only, insecure-by-design certificate (verification disabled client-side via
`ssl.CERT_NONE` in `tls_handshake`, documented in its docstring as never a production pattern).

## Verification actually performed this phase

- `pytest simulator/tests/test_protocols.py` — 8/8 passed: DNS query header counts and flags correct;
  QNAME encoded as real length-prefixed labels (`\x07example\x03lab\x00`); transaction IDs vary across
  calls; response parsing correctly identifies success, txid mismatch, and nonzero rcode cases;
  too-short responses rejected; the Postgres `SSLRequest` magic number independently verified against
  its documented decomposition (`1234 << 16 | 5679 == 80877103`) and the built message's exact byte
  layout confirmed.
- **Real integration run** against the live lab, all 6 protocols:
  - HTTP (`client`→`gateway`): 3/3 requests, all `status_code: 200`.
  - DNS (`client`→`dns`): 3/3 queries, all `rcode: 0`, `answer_count: 1`, `txid_matched: true` — a
    real, correctly-answered DNS resolution over UDP.
  - Generic TCP (`client`→`gateway:80`): 3/3 successful bare connects, sub-5ms latency.
  - Cache (`api-1`→`redis:6379`): 3/3, `raw_response: "+PONG"` — a real Redis protocol reply.
  - Database (`api-1`→`database:5432`): 3/3, `response_byte: "N"` — the real Postgres server
    genuinely replying that SSL is not enabled on this instance (honestly reported, not assumed "S").
  - TLS (`api-1`→`external-service:443`): 3/3, `tls_version: "TLSv1.3"`,
    `cipher: "TLS_AES_256_GCM_SHA384"` — a real negotiated handshake against the self-signed cert.
- Lab torn down (`docker compose ... down`) after verification.

## Known limitations

- The database sender deliberately stops at the `SSLRequest` handshake step (no authentication, no
  query execution) — sufficient to prove genuine wire-level Postgres protocol interaction without
  needing a database driver dependency or real credentials; a full authenticated session is not this
  phase's job.
- `tcp_raw_connect`'s target (`gateway:80`) happens to also speak HTTP; the sender itself never issues
  an HTTP request, so the *traffic generated* is genuinely just a TCP handshake — but a real network
  observer would still see it land on a port that also serves HTTP, which is realistic (many services
  share a port across protocol-classification attempts) rather than an artificial category.
- DNS's `example.lab` record only resolves because of the static entry from Phase 11's
  `dnsmasq.conf`; this is intentional (keeps the test independent of outbound internet DNS), not a
  simulation of arbitrary real-world domain resolution.
- No protocol diversity has been added to the temporal-pattern generator from Phase 14 yet (patterns
  and protocols remain two separate generators); combining "protocol X at temporal pattern Y" is not
  required by the spec at this phase and is not implemented.

## Status

This document, together with `simulator/traffic/{protocols,generate_protocol}.py` and
`simulator/tests/test_protocols.py`, satisfies Phase 15: all 6 required protocol categories are
generated with real wire-level exchanges, verified by both pure unit tests and a real run against the
live multi-tier lab.
