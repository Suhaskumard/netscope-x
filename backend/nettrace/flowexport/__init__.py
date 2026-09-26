"""NetFlow v5 / IPFIX ingestion (spec Phase 95)."""

from __future__ import annotations

from typing import List

from backend.nettrace.flowexport import ipfix, netflow_v5
from backend.nettrace.flowexport.records import FlowExportError, FlowRecord, records_to_packets

FORMATS = ("v5", "ipfix")


def decode(data: bytes, fmt: str) -> List[FlowRecord]:
    if fmt == "v5":
        return netflow_v5.decode(data)
    if fmt == "ipfix":
        return ipfix.decode(data)
    raise FlowExportError(f"unsupported flow export format {fmt!r}; expected one of {FORMATS}")


__all__ = ["FORMATS", "FlowExportError", "FlowRecord", "decode", "records_to_packets"]
