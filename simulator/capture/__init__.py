"""Real, lab-side live packet capture (spec Phase 21).

Anything that must physically touch the live Docker lab's network
namespace -- opening a raw socket on an authorized interface -- lives here,
following the same convention as `simulator/traffic/` (Phase 14/15) and
`simulator/ground_truth/` (Phase 16): the backend's FastAPI process
(`backend/app`) runs in a separate Docker Compose project with no shared
network to the lab, so it cannot itself sniff lab traffic regardless of
capabilities granted to it. `simulator/capture/live.py` runs inside an
authorized lab container instead, producing a real pcap that is then
ingested through `backend.nettrace.capture.ingest.ingest_pcap` -- the same
code path used for `POST /capture` with `source=pcap_upload`.
"""
