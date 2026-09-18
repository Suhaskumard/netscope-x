# NETSCOPE-X — High-Fidelity Packet Capture

Phase 21 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 21 — HIGH-FIDELITY PACKET
CAPTURE"): "Implement: PCAP ingestion, controlled live capture. Do not capture outside authorized
environments." FR-1.1 (`docs/requirements/system_requirements.md`): "The system shall ingest PCAP
files and support controlled live capture, restricted to authorized lab interfaces." This is the
**first NETTRACE phase** — the first real pipeline/inference code, as opposed to the scaffolding
(Phases 0-10) and lab-building (Phases 11-20) that preceded it. Phase 22 (Packet Normalization)
consumes this phase's raw `captures/<capture_id>/raw.pcap` output into the already-existing
`Packet` model (`backend/app/models/packet.py`).

## Design: pure ingestion in `backend/`, lab-touching mechanics in `simulator/`

The FastAPI backend (`backend/app`, repo-root `docker-compose.yml`, Phase 06) runs in a completely
separate Docker Compose project from the network lab (`simulator/docker/docker-compose.yml`, Phases
11-13) — no shared network. A raw socket opened inside the backend container cannot see lab traffic
regardless of what capabilities it is granted, and rearchitecting deployment topology to fix that is
out of scope for a one-line spec phase. So, following the pattern established by every prior
"must touch the live lab" phase (11-20: Docker-touching mechanics live in `simulator/`; schema/pure
logic lives in `backend/`):

- **`backend/nettrace/capture/`** (new package, sibling to `backend/app/`, already anticipated by
  `docs/architecture/ground_truth.md`'s reference to a future `backend/nettrace/topology.py`) holds
  pure, host-agnostic PCAP logic:
  - `ingest.py` — `validate_pcap_bytes`/`validate_pcap_file` (Scapy `PcapReader`-based: rejects a
    bad magic number, a truncated file, and a zero-packet file) and `ingest_pcap`, which validates,
    copies the raw bytes to the canonical `captures/<capture_id>/raw.pcap` (`experiments/artifacts`,
    Phase 10), and writes a `CaptureManifest` alongside it via the plain `write_json` helper — not
    the hashed `write_ground_truth` pair, since a capture is not ground truth.
  - `models.py` — `CaptureManifest` (Pydantic; capture_id/source/original_filename or
    interface/packet_count/size_bytes/ingested_at).
  - `errors.py` — `InvalidPcapError`, `UnauthorizedInterfaceError`. Deliberately **stdlib-only, no
    Pydantic import** — see below.
  - `authorized_interfaces.py` — the live-capture interface allowlist. Also **stdlib-only**: reads
    `NETSCOPE_AUTHORIZED_CAPTURE_INTERFACES` (comma-separated) directly from the environment rather
    than through `backend.app.core.config.Settings`.
- **`simulator/capture/live.py`** holds the mechanics that must physically touch the live lab: a
  real Scapy `sniff()`/`wrpcap()` capture, run inside the lab's `client` container (granted
  `cap_add: [NET_RAW, NET_ADMIN]` in `simulator/docker/docker-compose.yml`, the same convention used
  to run Phase 14/15/19's traffic/protocol/replay generators inside the lab). It imports
  `backend.nettrace.capture.{authorized_interfaces,errors}` to share the exact same authorization
  check and error type as the API layer — and this only works because those two modules are
  stdlib-only: `client`'s alpine image only gets Scapy installed via pip, not the backend's full
  FastAPI/Pydantic stack. `models.py`'s `CaptureManifest` (Pydantic) is deliberately kept out of
  that import chain.
- `POST /capture` with `source=live_interface` validates the interface against the allowlist and
  returns 202 with a `note` describing the real, two-step, lab-side workflow — it does not pretend
  the backend performs the sniff synchronously. Actually running `simulator/capture/live.py` and
  then submitting the resulting pcap through `source=pcap_upload` is what performs a real controlled
  live capture end-to-end. This mirrors Phase 15's own honestly-documented scoping finding ("no
  single container reaches all six protocols") rather than hiding a real architectural constraint.

## `POST /capture` behavior

| `source` | Requires | Success (202) | Failure |
|---|---|---|---|
| `pcap_upload` | `pcap_filename` present in `Settings.upload_staging_dir` and a real, non-empty pcap | `capture_id`, `packet_count` | 422 `invalid_pcap` (missing file or fails Scapy validation); 422 `validation_error` (missing `pcap_filename`) |
| `live_interface` | `interface` in the authorized allowlist | `capture_id`, `note` describing the lab-side workflow | 403 `unauthorized_interface`; 422 `validation_error` (missing `interface`) |

## Authorized interfaces (spec §5 Safety Boundary)

Default: `eth0` — the interface name Docker assigns inside `client`, a single-homed, edge-network-
only container per Phase 12's segmentation (`simulator/docker/docker-compose.yml`). Overridable via
`NETSCOPE_AUTHORIZED_CAPTURE_INTERFACES` (comma-separated). No other lab container is granted
capture capability or listed in the allowlist — capture stays scoped to one authorized, documented
vantage point, not silently expanded to "anything the lab happens to expose."

## Known limitations

- `source=live_interface` does not perform a synchronous capture inside the API request — it
  authorizes and documents the workflow. The actual sniff is a separate, real, manually-triggered
  `simulator/capture/live.py` run inside the lab, then ingested via `source=pcap_upload`. This is a
  real architectural constraint (separate Docker Compose projects, no shared network), not a
  shortcut.
- The interface allowlist is duplicated as two stdlib-only modules importing from the same
  `backend.nettrace.capture` package rather than unified behind `Settings`, specifically so
  `simulator/capture/live.py` never needs Pydantic installed in its lab container. Both call sites
  resolve to the identical `is_authorized_interface` function — there is one source of truth, just
  reached without going through `backend.app.core.config`.
- Live-capture verification against the actual Docker lab was **not performed this phase**: this
  implementation session's environment has no Docker installation at all (`docker` is not on PATH,
  no Docker Desktop install found), unlike the environment Phases 11-20 were verified in. PCAP
  ingestion (`source=pcap_upload`) was verified for real (see below) without Docker, since it only
  needs a real pcap file on disk. The live-capture half (`simulator/capture/live.py` actually
  sniffing inside `client`, granted `cap_add: [NET_RAW, NET_ADMIN]`) still needs a real run against
  the live lab, in an environment where Docker is available, before this phase's live-capture path
  can be considered end-to-end verified the way Phases 11-20 were. This is reported honestly per the
  project's Rule 2/3, rather than fabricating a Docker run that did not happen.

## Verification actually performed this phase

- `pytest backend/tests/test_nettrace_capture.py` — pcap validation (real capture accepted; empty,
  garbage, and zero-packet files rejected with the correct `InvalidPcapError` message),
  `ingest_pcap` round-trip (canonical `raw.pcap` + `manifest.json` written, manifest round-trips
  through `read_json` byte-identical), interface-allowlist accept/reject.
- `pytest simulator/tests/test_capture.py` — an unauthorized `live_interface` request is rejected
  before any file is written and before Scapy's `sniff()` is ever reached.
- `pytest backend/tests/test_api.py` — the 11 still-unimplemented endpoint groups still return the
  structured 501 envelope (no regression); `/capture` real-behavior tests for both `source` values:
  a real pcap (built with Scapy's own `wrpcap`) staged and ingested end-to-end through the live
  FastAPI `TestClient`, a missing/invalid staged file rejected with 422 `invalid_pcap`, a missing
  `pcap_filename`/`interface` rejected with 422 `validation_error`, an authorized interface accepted
  with 202, and an unauthorized interface rejected with 403 `unauthorized_interface`.
- Full combined suite (`pytest backend/tests experiments/tests simulator/tests`) — 153/153 passed
  (up from 136/136 after Phase 20), no regression.
- `python -m scripts.validate_data_contracts` — 38/38 passed, no regression.
- `python scripts/check_ground_truth_boundary.py` — clean, zero violations (the new
  `backend/nettrace/` and `simulator/capture/` packages do not import `simulator.ground_truth`).
- **Real, manual end-to-end run** (no Docker needed for this half): started the real FastAPI app via
  `TestClient`, seeded a real pcap file (6 real Scapy-built TCP packets) into a real staging
  directory, and issued real HTTP requests: `pcap_upload` against the real seeded file (202,
  `packet_count: 6`, and the ingested `raw.pcap`/`manifest.json` confirmed present and byte-correct
  on disk), `pcap_upload` against a missing filename (422 `invalid_pcap`), `live_interface` for
  `eth0` (202 with the expected workflow note), and `live_interface` for `wlan0` (403
  `unauthorized_interface`).
- Docker-lab live-capture verification: **not performed this phase** — see "Known limitations."

## Status

PCAP ingestion (spec Phase 21's first bullet) is fully implemented and verified end-to-end for
real. Controlled live capture (spec Phase 21's second bullet) is implemented and unit-verified
(authorization pre-flight, no real socket for a rejected interface), and its real execution path is
specified and wired to reuse the same ingestion code — but the actual live-lab sniff has not yet
been run against a real Docker lab in this session and should be verified in an environment where
Docker is available before this phase is considered fully closed out the way Phases 11-20 were.
