"""Flow and flow-feature data contracts.

Serves FR-1.3-1.8 (five-tuple reconstruction, TCP state, UDP sessions,
protocol fingerprinting, encrypted-metadata analysis, flow features).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, IPvAnyAddress, model_validator

from backend.app.models.packet import TransportProtocol


class TCPState(str, Enum):
    """Coarse TCP session state derived from observed flags (spec Phase 24)."""

    SYN_SENT = "syn_sent"
    ESTABLISHED = "established"
    CLOSING = "closing"
    CLOSED = "closed"
    RESET = "reset"
    PARTIAL = "partial"  # session observed without a full handshake/teardown


class FlowFeatures(BaseModel):
    """Derived statistics for a flow (spec Phase 28)."""

    packet_count: int = Field(..., ge=0)
    byte_count: int = Field(..., ge=0)
    duration_seconds: float = Field(..., ge=0)
    burstiness: float = Field(..., description="Coefficient of variation of inter-arrival times.")
    mean_inter_arrival_seconds: float = Field(..., ge=0)
    forward_byte_ratio: float = Field(..., ge=0, le=1, description="Fraction of bytes sent forward.")
    destination_diversity: int = Field(
        ..., ge=0, description="Distinct destination endpoints seen from the flow's source, in window."
    )
    port_diversity: int = Field(
        ..., ge=0, description="Distinct destination ports seen from the flow's source, in window."
    )
    is_persistent: bool = Field(
        ...,
        description=(
            "Whether this flow's five-tuple recurs as more than one Flow within this capture "
            "(spec Phase 28) -- e.g. a UDP five-tuple split into multiple idle-timeout sessions. "
            "True cross-capture persistence isn't tracked."
        ),
    )


class Flow(BaseModel):
    """A reconstructed bidirectional five-tuple flow (spec Phase 23)."""

    flow_id: str
    capture_id: str

    src_ip: IPvAnyAddress
    dst_ip: IPvAnyAddress
    src_port: Optional[int] = Field(default=None, ge=0, le=65535)
    dst_port: Optional[int] = Field(default=None, ge=0, le=65535)
    protocol: TransportProtocol

    first_seen: datetime
    last_seen: datetime

    tcp_state: Optional[TCPState] = Field(
        default=None, description="Only populated when protocol == TCP."
    )
    fingerprinted_protocol: Optional[str] = Field(
        default=None,
        description=(
            "Application-layer protocol inferred from observable evidence (spec Phase 26). "
            "None means 'not confidently fingerprinted' -- never a guess dressed as certainty."
        ),
    )
    tls_version: Optional[str] = Field(
        default=None,
        description=(
            "Real negotiated TLS version from a parsed ServerHello (spec Phase 27, FR-1.7). "
            "Only set when protocol == TCP. None means no ServerHello was observed/parseable "
            "-- never a guess."
        ),
    )

    features: FlowFeatures

    @model_validator(mode="after")
    def _last_not_before_first(self) -> "Flow":
        if self.last_seen < self.first_seen:
            raise ValueError("last_seen cannot precede first_seen")
        return self

    @model_validator(mode="after")
    def _tcp_state_only_for_tcp(self) -> "Flow":
        if self.tcp_state is not None and self.protocol != TransportProtocol.TCP:
            raise ValueError("tcp_state may only be set when protocol == TCP")
        return self

    @model_validator(mode="after")
    def _tls_version_only_for_tcp(self) -> "Flow":
        if self.tls_version is not None and self.protocol != TransportProtocol.TCP:
            raise ValueError("tls_version may only be set when protocol == TCP")
        return self
