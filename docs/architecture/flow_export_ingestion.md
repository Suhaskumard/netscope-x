# NetFlow v5 / IPFIX Ingestion (Phase 95)

Alternate Phase 21 capture source. Code: `backend/nettrace/flowexport/` (`netflow_v5.py`, `ipfix.py`, `records.py`,
`exporter.py`), `ingest_flow_export` in `capture/ingest.py`, `capture/packets.py::ensure_packets`.

## How it works
- `POST /capture` with `source: "netflow_upload"`, `flow_filename` (bare name, in the caller's inbox) and
  `flow_format: "v5" | "ipfix"`. The file is a concatenation of export datagrams. It is decoded (rejected with 422 if empty,
  truncated, wrong version, missing template, variable-length fields), stored as `captures/<id>/flowexport.bin`, and each
  flow record is expanded into `packets` synthetic `Packet`s written to `packets.jsonl`. `GET /flows` and `GET /topology`
  call `ensure_packets` (pcap -> normalize, flow export -> already normalized) and then run the unchanged reconstruct ->
  topology code. Works with tenancy and auth (per-tenant inbox/root).
- Decoders: v5 (IPv4, 24-byte header, 48-byte records). IPFIX: template sets, reduced-size integers, unknown elements
  skipped by length, IPv4 + IPv6, options sets ignored. Expansion: timestamps spread evenly first..last, bytes split evenly,
  `tcp_flags` deliberately unset (a record has only the OR of flags).
- `exporter.py` is this project's own software exporter (pcap -> records: unidirectional five-tuples, 15 s inactive /
  1800 s active timeout, OR of TCP flags, IP-layer octets); CLI: `python -m scripts.pcap_to_flowexport in.pcap out.ipfix`.

## Verified
- `backend/tests/test_flow_export.py` (15 tests): v5 encode -> **Scapy's `NetflowHeader` decodes it to the same fields**;
  round trips (multi-datagram v5, IPv4+IPv6 IPFIX); a hand-built IPFIX message with an unknown element and 4-byte
  counters; malformed inputs rejected; PCAP-vs-export topology equality; API end to end incl. tenant isolation.
- `python -m scripts.run_flow_export_benchmark` (6 topologies x 2 seeds x {v5, IPFIX} x 2 traffic variants = 48 runs): the
  same real pcap through path A (pcap) and path B (export -> ingest) gives identical node sets, edge sets (F1 1.000) and
  flow five-tuple sets in 48/48, with equal packet counts.
  - `generated` traffic (one packet per flow record): confidence max diff <= 0.0002.
  - `persistent` traffic (long-lived connections with handshakes; 52-328 records aggregating 576-2880 packets): confidence
    identical for small/medium/multi_service; where handshake evidence matters the mean edge confidence falls
    (large 0.948 -> 0.926, multi_path 0.974 -> 0.963, dynamic 0.964 -> 0.948; per-edge max diff 0.033-0.036).

## Limits (not claimed)
- No vendor device or real NetFlow capture was available: the exporter and decoders are ours (v5 is cross-checked with
  Scapy's decoder; IPFIX only against our own encoder and a hand-built message). Real exporters differ (timeouts, byte
  counting, template refresh, options data, sampling).
- **sFlow and NetFlow v9 are not implemented.** No IPv6 in v5, no sampled-rate scaling, no enterprise elements.
- A flow record cannot carry per-packet flags, TLS or payload signals, so handshake/TCP-state evidence, TLS versions and
  ordering inside a flow are lost; confidence is therefore lower where those signals contributed (measured above).
  Timestamps are ms-granular and intra-flow packet spacing is synthetic (even), so timing-based analyses (temporal
  precedence, anomaly timing) are not equivalent to pcap.
- Bytes: exporter counts IP-layer octets, so `size_bytes` differs from pcap wire length by the Ethernet header.
