"""Phase 21 controlled live capture unit tests.

Pure, no Docker/live sniffing required -- proves the interface-authorization
pre-flight check refuses to touch the network for an unauthorized interface,
without ever reaching Scapy's real `sniff()` call. A real, torn-down-after
live capture against the actual lab is performed manually (see
docs/architecture/packet_capture.md) since it requires a live Docker lab
and raw-socket capability, matching the precedent set by
`simulator/tests/test_observatory_validation.py`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.nettrace.capture.errors import UnauthorizedInterfaceError
from simulator.capture.live import capture


def test_capture_rejects_unauthorized_interface_without_sniffing(tmp_path: Path) -> None:
    out_path = tmp_path / "out.pcap"
    with pytest.raises(UnauthorizedInterfaceError):
        capture("wlan0", duration_seconds=1.0, out_path=out_path)
    # No file should ever be written -- authorization is checked before the
    # `from scapy.sendrecv import sniff` import/call, so a real socket is
    # never opened for a rejected interface.
    assert not out_path.exists()


def test_capture_rejects_arbitrary_unauthorized_interface_name(tmp_path: Path) -> None:
    with pytest.raises(UnauthorizedInterfaceError):
        capture("not-a-real-interface", duration_seconds=0.1, out_path=tmp_path / "unreached.pcap")
