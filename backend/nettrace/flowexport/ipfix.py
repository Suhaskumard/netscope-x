"""IPFIX (NetFlow v10, RFC 7011) codec (spec Phase 95).

Decoder: template sets (id 2) are learned per (observation domain, template id) and applied to data sets; options
templates/sets are skipped; reduced-size unsigned integers are honoured; unknown information elements are skipped by
length; variable-length fields, enterprise-specific fields with unknown meaning (skipped), a data set with no known
template, and truncated or wrong-version messages raise FlowExportError.
Encoder: an IPv4 template (256) and an IPv6 template (257), then data sets.
"""

from __future__ import annotations

import ipaddress
import struct
from typing import Dict, List, Tuple

from backend.nettrace.flowexport.records import FlowExportError, FlowRecord

_MSG = struct.Struct("!HHIII")  # version, length, export time, sequence, domain
_SET = struct.Struct("!HH")

# information element ids
SRC4, DST4, SRC6, DST6 = 8, 12, 27, 28
SPORT, DPORT, PROTO, OCTETS, PACKETS, TCPFLAGS = 7, 11, 4, 1, 2, 6
START_MS, END_MS = 152, 153

_V4 = [(SRC4, 4), (DST4, 4), (SPORT, 2), (DPORT, 2), (PROTO, 1), (PACKETS, 8), (OCTETS, 8), (TCPFLAGS, 2),
       (START_MS, 8), (END_MS, 8)]
_V6 = [(SRC6, 16), (DST6, 16)] + _V4[2:]
_TEMPLATES = {256: _V4, 257: _V6}


def _template_set(domain_templates: Dict[int, list]) -> bytes:
    body = b"".join(
        struct.pack("!HH", tid, len(fields)) + b"".join(struct.pack("!HH", ie, ln) for ie, ln in fields)
        for tid, fields in domain_templates.items()
    )
    return _SET.pack(2, _SET.size + len(body)) + body


def _data_record(rec: FlowRecord, fields) -> bytes:
    out = b""
    for ie, ln in fields:
        if ie in (SRC4, SRC6):
            out += ipaddress.ip_address(rec.src_ip).packed
        elif ie in (DST4, DST6):
            out += ipaddress.ip_address(rec.dst_ip).packed
        else:
            value = {SPORT: rec.src_port, DPORT: rec.dst_port, PROTO: rec.protocol, PACKETS: rec.packets,
                     OCTETS: rec.octets, TCPFLAGS: rec.tcp_flags, START_MS: int(round(rec.start * 1000)),
                     END_MS: int(round(rec.end * 1000))}[ie]
            out += value.to_bytes(ln, "big")
    return out


def encode(records: List[FlowRecord], export_time: float | None = None, domain: int = 1, per_message: int = 20) -> bytes:
    """Template set + data sets; IPv4 and IPv6 records use separate templates. `per_message` bounds message size."""
    if not records:
        return b""
    export_time = export_time if export_time is not None else max(r.end for r in records) + 1.0
    out, seq = bytearray(), 0
    for i in range(0, len(records), per_message):
        chunk = records[i : i + per_message]
        sets = _template_set(_TEMPLATES) if i == 0 else b""
        for tid, version in ((256, 4), (257, 6)):
            group = [r for r in chunk if ipaddress.ip_address(r.src_ip).version == version]
            if group:
                body = b"".join(_data_record(r, _TEMPLATES[tid]) for r in group)
                sets += _SET.pack(tid, _SET.size + len(body)) + body
        out += _MSG.pack(10, _MSG.size + len(sets), int(export_time), seq, domain) + sets
        seq += len(chunk)
    return bytes(out)


def _uint(b: bytes) -> int:
    return int.from_bytes(b, "big")


def decode(data: bytes) -> List[FlowRecord]:
    if not data:
        raise FlowExportError("empty IPFIX export")
    templates: Dict[Tuple[int, int], List[Tuple[int, int]]] = {}
    records: List[FlowRecord] = []
    pos = 0
    while pos < len(data):
        if len(data) - pos < _MSG.size:
            raise FlowExportError("truncated IPFIX message header")
        version, length, _t, _seq, domain = _MSG.unpack_from(data, pos)
        if version != 10:
            raise FlowExportError(f"not IPFIX (version field {version})")
        if length < _MSG.size or pos + length > len(data):
            raise FlowExportError("truncated or invalid IPFIX message length")
        end, p = pos + length, pos + _MSG.size
        while p < end:
            if end - p < _SET.size:
                raise FlowExportError("truncated IPFIX set header")
            set_id, set_len = _SET.unpack_from(data, p)
            if set_len < _SET.size or p + set_len > end:
                raise FlowExportError("invalid IPFIX set length")
            body = data[p + _SET.size : p + set_len]
            if set_id == 2:
                templates.update(_parse_templates(body, domain))
            elif set_id >= 256:
                fields = templates.get((domain, set_id))
                if fields is None:
                    raise FlowExportError(f"IPFIX data set uses unknown template {set_id}")
                records.extend(_parse_data(body, fields))
            elif set_id in (3,):
                pass  # options template set: not needed
            else:
                raise FlowExportError(f"unsupported IPFIX set id {set_id}")
            p += set_len
        pos = end
    return records


def _parse_templates(body: bytes, domain: int):
    out, p = {}, 0
    while p + 4 <= len(body):
        tid, count = struct.unpack_from("!HH", body, p)
        p += 4
        fields = []
        for _ in range(count):
            if p + 4 > len(body):
                raise FlowExportError("truncated IPFIX template")
            ie, ln = struct.unpack_from("!HH", body, p)
            p += 4
            if ie & 0x8000:  # enterprise bit: 4-byte enterprise number follows; we do not know the element
                p += 4
                ie = -1
            if ln == 0xFFFF:
                raise FlowExportError("variable-length IPFIX fields are not supported")
            fields.append((ie, ln))
        out[(domain, tid)] = fields
    return out


def _parse_data(body: bytes, fields) -> List[FlowRecord]:
    size = sum(ln for _, ln in fields)
    if size == 0:
        raise FlowExportError("zero-length IPFIX template")
    out, p = [], 0
    while p + size <= len(body):  # trailing bytes < one record are padding
        v: dict = {}
        for ie, ln in fields:
            raw = body[p : p + ln]
            p += ln
            if ie in (SRC4, SRC6):
                v["src"] = str(ipaddress.ip_address(raw))
            elif ie in (DST4, DST6):
                v["dst"] = str(ipaddress.ip_address(raw))
            elif ie in (SPORT, DPORT, PROTO, OCTETS, PACKETS, TCPFLAGS, START_MS, END_MS):
                v[ie] = _uint(raw)
        missing = [k for k in ("src", "dst", PROTO, PACKETS, OCTETS, START_MS, END_MS) if k not in v]
        if missing:
            raise FlowExportError(f"IPFIX record lacks required elements {missing}")
        out.append(FlowRecord(
            v["src"], v["dst"], v.get(SPORT, 0), v.get(DPORT, 0), v[PROTO], v[PACKETS], v[OCTETS],
            v[START_MS] / 1000.0, v[END_MS] / 1000.0, v.get(TCPFLAGS, 0) & 0xFF,
        ))
    return out
