"""Authorized live-capture interface allowlist (spec §5 Safety Boundary:
"packet capture... must occur only inside a controlled laboratory
environment"; FR-1.1: "restricted to authorized lab interfaces").

Deliberately stdlib-only (no Pydantic/Settings dependency): this module is
imported both by the backend API (`backend/app/api/routes/capture.py`) and
by `simulator/capture/live.py`, which runs inside a bare-Python lab
container that only has Scapy installed. Configuration still follows the
project's `NETSCOPE_`-prefixed convention (spec Phase 08), just read
directly from the environment rather than through `backend.app.core.config`.

The default, `eth0`, is the interface name Docker assigns inside the
`client` container of `simulator/docker/docker-compose.yml` (a
single-homed, edge-network-only container per Phase 12's segmentation) --
confirmed by running `ip addr` inside a live `client` container. A
live-capture request for any interface outside this set is rejected before
anything is sniffed.
"""

from __future__ import annotations

import os

_ENV_VAR = "NETSCOPE_AUTHORIZED_CAPTURE_INTERFACES"
_DEFAULT_INTERFACES = ("eth0",)


def authorized_interfaces() -> frozenset[str]:
    raw = os.environ.get(_ENV_VAR)
    if not raw:
        return frozenset(_DEFAULT_INTERFACES)
    return frozenset(name.strip() for name in raw.split(",") if name.strip())


def is_authorized_interface(interface: str) -> bool:
    return interface in authorized_interfaces()
