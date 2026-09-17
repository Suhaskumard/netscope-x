"""Packet and normalized-packet data contracts.

Serves FR-1.1 (capture) and FR-1.2 (normalization) from
docs/requirements/system_requirements.md. A `Packet` is the normalized,
protocol-agnostic representation every later pipeline stage consumes —
NETSCOPE-X never operates on raw capture bytes past this boundary.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, IPvAnyAddress


class TransportProtocol(str, Enum):
    TCP = "TCP"
    UDP = "UDP"
    ICMP = "ICMP"
    OTHER = "OTHER"


class PacketDirection(str, Enum):
    """Direction relative to the flow this packet was assigned to."""

    FORWARD = "forward"
    REVERSE = "reverse"
    UNKNOWN = "unknown"


class Packet(BaseModel):
    """A single normalized packet observation (spec Phase 22)."""

    packet_id: str = Field(..., description="Stable identifier, e.g. capture_id + offset.")
    capture_id: str = Field(..., description="Identifies the PCAP/live-capture session this came from.")
    timestamp: datetime = Field(..., description="Capture timestamp, normalized to UTC.")

    src_ip: IPvAnyAddress
    dst_ip: IPvAnyAddress
    src_port: Optional[int] = Field(default=None, ge=0, le=65535)
    dst_port: Optional[int] = Field(default=None, ge=0, le=65535)

    protocol: TransportProtocol
    size_bytes: int = Field(..., ge=0, description="Total packet size on the wire, in bytes.")
    direction: PacketDirection = PacketDirection.UNKNOWN

    tcp_flags: Optional[str] = Field(
        default=None,
        description="Raw TCP flag string (e.g. 'SYN,ACK'), present only when protocol == TCP.",
    )

    model_config = {"frozen": True}
