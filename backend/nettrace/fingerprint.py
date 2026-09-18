"""Protocol fingerprinting (spec Phase 26, FR-1.6).

Pure, host-agnostic logic. `Packet` carries no application-layer payload --
metadata-only, per `docs/architecture/algorithm_selection.md`'s rejection
of full protocol-stack reassembly -- so this cannot be deep packet
inspection. It is a small, explicit (transport, well-known port) ->
protocol-name table, matched against a flow's own canonical ports.
Anything not in the table stays honestly `None`: FR-1.6 requires the
system not claim coverage it cannot support, so a name is only ever
returned for a protocol this module has a documented rule for. Scoped to
the protocols `simulator/traffic/protocols.py` (Phase 15) generates real
traffic for, so every entry is independently, end-to-end verifiable
against known ground truth. See
`docs/architecture/protocol_fingerprinting.md`.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

from backend.app.models.packet import TransportProtocol

_WELL_KNOWN_PORTS: Dict[Tuple[TransportProtocol, int], str] = {
    (TransportProtocol.TCP, 80): "http",
    (TransportProtocol.TCP, 443): "tls",
    (TransportProtocol.TCP, 5432): "postgresql",
    (TransportProtocol.TCP, 6379): "redis",
    (TransportProtocol.UDP, 53): "dns",
}


def fingerprint_protocol(
    protocol: TransportProtocol,
    src_port: Optional[int],
    dst_port: Optional[int],
) -> Optional[str]:
    """Looks up `dst_port` first (the server side in the common
    client-initiates-to-server-port case), falling back to `src_port` (in
    case the canonical orientation put the well-known port there instead --
    e.g. the server happened to be the first-observed packet's sender).
    Returns `None`, never a guess, when neither port is in the table.
    """
    for port in (dst_port, src_port):
        if port is not None:
            name = _WELL_KNOWN_PORTS.get((protocol, port))
            if name is not None:
                return name
    return None
