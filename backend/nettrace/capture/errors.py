"""Capture error types (spec Phase 21).

Deliberately dependency-free (stdlib only, no pydantic) so that
`simulator/capture/live.py` -- which runs inside a bare-Python lab
container that only has Scapy installed, not the backend's full FastAPI/
Pydantic stack -- can import these without pulling in dependencies that
aren't present there. `backend.nettrace.capture.models.CaptureManifest`
(a Pydantic model, used only backend-side) is kept in a separate module
for exactly this reason.
"""

from __future__ import annotations


class InvalidPcapError(Exception):
    """Raised when a file that is supposed to be a PCAP does not parse as one:
    missing/wrong magic number, truncated, or containing zero packets."""


class UnauthorizedInterfaceError(Exception):
    """Raised when a live-capture request targets an interface outside the
    authorized allowlist (spec §5 Safety Boundary) -- refused before any
    socket is opened, by both `POST /capture` and `simulator/capture/live.py`."""


class CaptureNotFoundError(Exception):
    """Raised when a capture_id has no ingested raw.pcap yet -- e.g. GET
    /flows (spec Phase 23) for a capture_id nothing was ever POSTed to
    /capture for."""


class InterfaceUnavailableError(Exception):
    """Raised when an authorized interface passes the allowlist check (spec
    §5) but the OS itself cannot open it for capture -- e.g. the interface
    does not exist inside the lab container, or was brought down mid-capture
    (spec §15 REL-12: "Unavailable network interfaces during a live-capture
    request" must fail gracefully, not crash with a raw OSError)."""
