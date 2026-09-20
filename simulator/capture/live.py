"""Controlled live capture execution + CLI (spec Phase 21, FR-1.1).

Sniffs real traffic on an authorized interface inside the live lab and
writes it to a real pcap file via Scapy. Never targets an interface outside
`backend.nettrace.capture.authorized_interfaces` (spec §5 Safety Boundary:
"packet capture... must occur only inside a controlled laboratory
environment"). This module is the "controlled live capture" half of Phase
21; PCAP validation/ingestion is `backend/nettrace/capture/ingest.py`, which
this module's output is meant to be fed into afterward.

Run (from inside the lab's `client` container, which was granted
`cap_add: [NET_RAW, NET_ADMIN]` in `simulator/docker/docker-compose.yml`
specifically for this):
    docker compose -f simulator/docker/docker-compose.yml exec client \\
        python3 -m simulator.capture.live --interface eth0 \\
        --duration 10 --out /tmp/live_capture.pcap
"""

from __future__ import annotations

import argparse
from pathlib import Path

from backend.nettrace.capture.authorized_interfaces import is_authorized_interface
from backend.nettrace.capture.errors import InterfaceUnavailableError, UnauthorizedInterfaceError


def capture(interface: str, duration_seconds: float, out_path: Path, packet_count: int = 0) -> int:
    """Sniffs real traffic on `interface` for `duration_seconds` (or until
    `packet_count` packets are seen, if nonzero) and writes it to `out_path`
    as a real pcap. Returns the number of packets captured.

    Raises UnauthorizedInterfaceError before touching the network if
    `interface` is not in the authorized allowlist, or InterfaceUnavailableError
    if the interface is authorized but the OS cannot open it (spec REL-12).
    """
    if not is_authorized_interface(interface):
        raise UnauthorizedInterfaceError(
            f"{interface!r} is not an authorized capture interface (spec §5 Safety Boundary)"
        )

    from scapy.all import wrpcap
    from scapy.sendrecv import sniff

    try:
        packets = sniff(iface=interface, timeout=duration_seconds, count=packet_count or 0)
    except OSError as exc:
        raise InterfaceUnavailableError(
            f"authorized interface {interface!r} could not be opened for capture: {exc}"
        ) from exc
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wrpcap(str(out_path), packets)
    return len(packets)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interface", required=True, help="Authorized lab interface, e.g. eth0.")
    parser.add_argument("--duration", type=float, default=10.0, help="Capture window in seconds.")
    parser.add_argument("--count", type=int, default=0, help="Stop early after this many packets (0 = no limit).")
    parser.add_argument("--out", required=True, type=Path, help="Output pcap path.")
    args = parser.parse_args()

    n = capture(args.interface, args.duration, args.out, packet_count=args.count)
    print(f"captured {n} packets on {args.interface!r} -> {args.out}")


if __name__ == "__main__":
    main()
