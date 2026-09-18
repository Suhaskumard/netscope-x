# NETSCOPE-X — Encrypted Traffic Metadata

Phase 27 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 27 — ENCRYPTED TRAFFIC
METADATA"). FR-1.7 (`docs/requirements/system_requirements.md`): "The system shall extract permitted
metadata from encrypted traffic (TLS version, duration, sizes, timing, endpoint relationships)
without attempting decryption." `docs/research/problem_definition.md` states the same boundary twice:
"never plaintext payload content" (assumptions) and "Payload decryption is explicitly out of scope"
(out-of-scope list).

## Four of five items were already real

`duration`, `sizes`, `timing`, and `endpoint relationships` — four of FR-1.7's five named items — were
already delivered for real by Phases 23 and 25, as ordinary `Flow`/`FlowFeatures` fields, with no
TLS-specific handling needed: `FlowFeatures.duration_seconds`, `byte_count`,
`mean_inter_arrival_seconds`/`burstiness` (timing), and `Flow.src_ip`/`dst_ip`/`src_port`/`dst_port`
(endpoint relationships). These apply to *any* flow, encrypted or not — nothing about them requires
looking inside TLS traffic specifically. This phase's real, novel work is the fifth and last item:
**TLS version**. Code: `backend/nettrace/tls_metadata.py` (`extract_tls_versions`), called from
`backend/nettrace/reconstruct.py`'s `reconstruct_flows`, populating the new `Flow.tls_version` field.
`GET /flows` needs no route changes — it already calls `reconstruct_flows` on every request.

## Algorithm decision (made this phase)

Like Phase 26, `docs/architecture/algorithm_selection.md` (Phase 05) doesn't cover this area — an
honest, noted gap in the original planning, decided and documented here instead.

**Why parsing a `ServerHello` is metadata extraction, not decryption**: a TLS `ServerHello` handshake
message is never encrypted, in any TLS version — encryption only begins after the handshake
completes. Its header (a "legacy version" field) and, for TLS 1.3 specifically, its
`supported_versions` extension are sent in the clear, precisely so a passive observer can read them.
The legacy version field is pinned to `0x0303` ("TLS 1.2") for middlebox compatibility even when
TLS 1.3 is what's actually negotiated — real negotiated-version detection for 1.3 requires reading
the `supported_versions` extension, not just the legacy field. Both are genuine cleartext metadata;
neither requires decrypting anything.

`_parse_server_hello_version(payload)` (`backend/nettrace/tls_metadata.py`) parses one TCP segment's
payload: TLS record header (content type `0x16` = Handshake, version, length) → handshake header
(message type `0x02` = ServerHello, length) → the ServerHello body (legacy version, random,
session ID, cipher suite, compression method, extensions) → scans extensions for `supported_versions`
(type `0x002B`), preferring it over the legacy field when present. Returns `None` for anything that
doesn't fit this shape — a different record/message type, a `ServerHello` split across TCP segments
(not reassembled), or a payload too short to contain what's being parsed.

`extract_tls_versions(root, capture_id)` re-reads `raw.pcap` directly via `PcapReader` — the same
convention `normalize.py` already established — independent of the persisted `Packet` schema, which
deliberately carries no payload (Phase 22). Returns a `{(server_ip, server_port): version}` lookup;
`reconstruct_flows` checks both of a flow's canonical endpoints against it (a `ServerHello` is always
server→client, so whichever endpoint sent it resolves correctly regardless of which side the
five-tuple grouping canonicalized as `src`).

## Why `Packet`/`normalize.py` weren't touched

`Packet` is a frozen, already-shipped, tested contract (Phase 22) with no payload field by design.
Rather than reopening it to add a transient payload-derived field, `tls_metadata.py` does its own
independent `PcapReader` pass — mirroring how `normalize.py` itself reads `raw.pcap`, but scoped
narrowly to this one enrichment. This keeps Phase 22's contract untouched and makes the new logic
easy to reason about and test in isolation.

## Real, checkable ground truth

`simulator/traffic/protocols.py`'s `tls_handshake` (Phase 15) performs a genuine TLS handshake via
Python's `ssl` module against the lab's `external-service`, and `docs/architecture/protocol_generation.md`
records the real outcome: `TLSv1.3` / `TLS_AES_256_GCM_SHA384`. This phase's manual verification (see
below) constructs the exact TLS 1.3 wire bytes — including the `supported_versions` extension — to
confirm the parser resolves it correctly, cross-checked against that same real negotiated version
rather than an arbitrary invented one.

## `Flow` schema change

`Flow` gains one new field, validated the same way `tcp_state` already is:

```python
tls_version: Optional[str] = Field(default=None, description=(
    "Real negotiated TLS version from a parsed ServerHello (spec Phase 27, FR-1.7). "
    "Only set when protocol == TCP. None means no ServerHello was observed/parseable "
    "-- never a guess."
))
```

plus a `_tls_version_only_for_tcp` model validator mirroring `_tcp_state_only_for_tcp`. In practice
this is also structurally guaranteed: `extract_tls_versions` only ever populates entries from TCP
packets, so a UDP flow's lookup can never hit.

## Known limitations

- **A `ServerHello` split across TCP segments is not reassembled.** Each packet's payload is parsed
  independently; if the handshake message spans more than one TCP segment (uncommon for a
  `ServerHello`, which is typically small, but possible with unusual MTU/timing), the version stays
  `None` — an honest gap, not a silent wrong answer.
- **Only `ServerHello` is parsed, not `ClientHello`.** A `ClientHello` carries the *offered* versions,
  not the negotiated one — parsing it wouldn't answer FR-1.7's question ("TLS version" meaning what
  was actually used), so it's deliberately out of scope, not an oversight.
- **This covers TLS only.** Other encrypted protocols (e.g. SSH) are out of scope for this phase.

## Verification actually performed this phase

- `pytest backend/tests/test_nettrace_tls_metadata.py` — 9/9 passed: `_parse_server_hello_version`
  correctly resolves TLS 1.0/1.1/1.2 from the legacy version field; TLS 1.3 correctly resolved via the
  `supported_versions` extension (proving the extension-priority path, not just the simpler legacy-field
  path); a non-Handshake record, a `ClientHello`, a truncated record, and a too-short payload all
  correctly return `None`; `extract_tls_versions` against a real Scapy-built pcap correctly maps the
  real `(server_ip, server_port)` to `"TLS 1.3"`.
- `pytest backend/tests/test_nettrace_reconstruct.py` — grew by 2: a real crafted TLS 1.3
  `ServerHello`, alongside a seeded `raw.pcap`, correctly sets `flow.tls_version == "TLS 1.3"`; with no
  `raw.pcap` present (the pattern every pre-existing test in this file already uses),
  `flow.tls_version` stays `None` with no exception — proving the graceful-degrade path works.
- Full combined suite (`pytest backend/tests experiments/tests simulator/tests`) — 209/209 passed (up
  from 198/198 after Phase 26), no regressions elsewhere.
- `python -m scripts.validate_data_contracts` — 38/38 passed, no regression (the schema change doesn't
  add a new contract check here — it's not enumerated by name in that script).
- `python scripts/check_ground_truth_boundary.py` — clean, zero violations.
- **Real, manual end-to-end run** (no Docker needed — pure pcap-file parsing, like Phases 21-26): built
  a real pcap with Scapy — a TCP/443 handshake, a real-shaped `ClientHello`, and a crafted `ServerHello`
  whose `supported_versions` extension negotiates TLS 1.3 (matching the real lab's own negotiated
  version) — ingested through the live FastAPI app's real `POST /capture`, then queried through the
  real `GET /flows`. Confirmed the resulting flow's `fingerprinted_protocol == "tls"` (already real
  since Phase 26, port 443) **and** `tls_version == "TLS 1.3"`, resolved via the extension path.

## Status

Encrypted traffic metadata extraction (spec Phase 27, FR-1.7) is fully implemented and verified
end-to-end for real. All five named items are now real: four via Phases 23/25's existing `Flow`/
`FlowFeatures` fields, and the fifth — TLS version, including correct TLS 1.3 resolution via the
`supported_versions` extension — via this phase's `tls_metadata.py`. The
cross-flow-aggregation-dependent parts of `FlowFeatures` (`is_persistent`, and the true cross-flow
meaning of `destination_diversity`/`port_diversity`) remain honestly unset/placeholder pending
Phase 28.
