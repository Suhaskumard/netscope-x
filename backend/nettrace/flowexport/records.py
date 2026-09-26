"""Flow records, the shared decoded form of NetFlow v5 / IPFIX (spec Phase 95), and record -> Packet expansion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List

from backend.app.models.packet import Packet, PacketDirection, TransportProtocol


class FlowExportError(ValueError):
    """A flow-export datagram/stream that is truncated, malformed, unsupported or of the wrong version."""


@dataclass(frozen=True)
class FlowRecord:
    src_ip: str
    dst_ip: str
    src_port: int
    dst_port: int
    protocol: int  # IANA protocol number
    packets: int
    octets: int
    start: float  # epoch seconds
    end: float
    tcp_flags: int = 0  # OR of all TCP flags seen (8 bits)


_PROTO = {6: TransportProtocol.TCP, 17: TransportProtocol.UDP, 1: TransportProtocol.ICMP, 58: TransportProtocol.ICMP}


def records_to_packets(records: List[FlowRecord], capture_id: str) -> List[Packet]:
    """Expand each record into `packets` synthetic Packets so the unchanged Phase 22+ pipeline can consume it.

    Timestamps are spread evenly between the record's first and last time; the byte count is split evenly with
    the remainder on the last packet. `tcp_flags` is left unset: a record carries only the OR of all flags, so
    per-packet flags (and therefore handshake evidence) are not fabricated. Direction stays UNKNOWN, as in Phase 22.
    """
    staged = []
    for rec in records:
        n = max(rec.packets, 1)
        proto = _PROTO.get(rec.protocol, TransportProtocol.OTHER)
        has_ports = proto in (TransportProtocol.TCP, TransportProtocol.UDP)
        base, extra = divmod(rec.octets, n)
        for i in range(n):
            t = rec.start if n == 1 else rec.start + (rec.end - rec.start) * i / (n - 1)
            size = base + (extra if i == n - 1 else 0)
            staged.append((t, rec, proto, has_ports, size))
    staged.sort(key=lambda s: s[0])
    out: List[Packet] = []
    for index, (t, rec, proto, has_ports, size) in enumerate(staged):
        out.append(
            Packet(
                packet_id=f"{capture_id}:{index}",
                capture_id=capture_id,
                timestamp=datetime.fromtimestamp(t, tz=timezone.utc),
                src_ip=rec.src_ip,
                dst_ip=rec.dst_ip,
                src_port=rec.src_port if has_ports else None,
                dst_port=rec.dst_port if has_ports else None,
                protocol=proto,
                size_bytes=size,
                direction=PacketDirection.UNKNOWN,
                tcp_flags=None,
            )
        )
    return out


def total_packets(records: List[FlowRecord]) -> int:
    return sum(r.packets for r in records)

