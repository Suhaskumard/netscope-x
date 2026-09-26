"""NetFlow v5 codec (spec Phase 95). IPv4 only, fixed 24-byte header + 48-byte records, <= 30 records per datagram."""

from __future__ import annotations

import ipaddress
import struct
from typing import List

from backend.nettrace.flowexport.records import FlowExportError, FlowRecord

_HEADER = struct.Struct("!HHIIIIBBH")  # version, count, uptime, secs, nsecs, seq, engine_type, engine_id, sampling
_RECORD = struct.Struct("!4s4s4sHHIIIIHHxBBBHHBBxx")
MAX_PER_DATAGRAM = 30
assert _HEADER.size == 24 and _RECORD.size == 48


def encode(records: List[FlowRecord], export_time: float | None = None, sequence: int = 0) -> bytes:
    """One datagram per <= 30 records, concatenated. IPv6 records are not representable in v5."""
    if not records:
        return b""
    export_time = export_time if export_time is not None else max(r.end for r in records) + 1.0
    uptime_ms = int((export_time - min(r.start for r in records)) * 1000) + 1000
    out = bytearray()
    for i in range(0, len(records), MAX_PER_DATAGRAM):
        chunk = records[i : i + MAX_PER_DATAGRAM]
        secs = int(export_time)
        out += _HEADER.pack(5, len(chunk), uptime_ms, secs, int((export_time - secs) * 1e9), sequence + i, 0, 0, 0)
        for r in chunk:
            src, dst = ipaddress.ip_address(r.src_ip), ipaddress.ip_address(r.dst_ip)
            if src.version != 4 or dst.version != 4:
                raise FlowExportError("NetFlow v5 cannot carry IPv6 flows")
            first = uptime_ms - int(round((export_time - r.start) * 1000))
            last = uptime_ms - int(round((export_time - r.end) * 1000))
            out += _RECORD.pack(
                src.packed, dst.packed, b"\0\0\0\0", 0, 0, r.packets, r.octets, first, last,
                r.src_port, r.dst_port, r.tcp_flags & 0xFF, r.protocol, 0, 0, 0, 0, 0,
            )
    return bytes(out)


def decode(data: bytes) -> List[FlowRecord]:
    """Decode a stream of concatenated v5 datagrams. Raises FlowExportError on anything malformed."""
    records: List[FlowRecord] = []
    pos = 0
    if not data:
        raise FlowExportError("empty NetFlow v5 export")
    while pos < len(data):
        if len(data) - pos < _HEADER.size:
            raise FlowExportError("truncated NetFlow v5 header")
        version, count, uptime, secs, nsecs, *_ = _HEADER.unpack_from(data, pos)
        if version != 5:
            raise FlowExportError(f"not NetFlow v5 (version field {version})")
        if not 1 <= count <= MAX_PER_DATAGRAM:
            raise FlowExportError(f"invalid v5 record count {count}")
        end = pos + _HEADER.size + count * _RECORD.size
        if end > len(data):
            raise FlowExportError("truncated NetFlow v5 datagram")
        export_time = secs + nsecs / 1e9
        for k in range(count):
            f = _RECORD.unpack_from(data, pos + _HEADER.size + k * _RECORD.size)
            src, dst, _nh, _in, _out, pkts, octets, first, last, sport, dport, flags, proto, *_ = f
            if first > uptime or last > uptime or last < first:
                raise FlowExportError("inconsistent v5 first/last timestamps")
            records.append(FlowRecord(
                str(ipaddress.IPv4Address(src)), str(ipaddress.IPv4Address(dst)), sport, dport, proto, pkts, octets,
                export_time - (uptime - first) / 1000.0, export_time - (uptime - last) / 1000.0, flags,
            ))
        pos = end
    return records
