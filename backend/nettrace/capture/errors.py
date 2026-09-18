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
