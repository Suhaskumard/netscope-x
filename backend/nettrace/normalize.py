"""Packet normalization (spec Phase 22, FR-1.2).

Pure, host-agnostic logic, following `backend.nettrace.capture.ingest`'s own
convention: reads a real `captures/<capture_id>/raw.pcap` (already ingested
by Phase 21) via Scapy's streaming `PcapReader`, and produces one frozen
`Packet` (`backend/app/models/packet.py`) per real captured frame.

Scope boundary: `PacketDirection` is documented as relative to the flow a
packet was assigned to, and flows don't exist until Phase 23 groups packets
by five-tuple. So every `Packet` produced here gets
`direction=PacketDirection.UNKNOWN` -- resolving forward/reverse is Phase
23's job, not this one.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from scapy.layers.inet import ICMP, IP, TCP, UDP
from scapy.layers.inet6 import IPv6
from scapy.utils import PcapReader

from backend.app.models.packet import Packet, PacketDirection, TransportProtocol
from experiments.artifacts.io import write_jsonl
from experiments.artifacts.paths import packets_path, pcap_path

# Ascending TCP flag-bit order, matching Scapy's own FlagValue string
# representation (e.g. flags='SA' -> str(flags) == "SA").
_TCP_FLAG_NAMES = {
    "F": "FIN",
    "S": "SYN",
    "R": "RST",
    "P": "PSH",
    "A": "ACK",
    "U": "URG",
    "E": "ECE",
    "C": "CWR",
    "N": "NS",
}


def _tcp_flags_to_string(pkt) -> str:
    letters = str(pkt[TCP].flags)
    return ",".join(_TCP_FLAG_NAMES.get(letter, letter) for letter in letters)


def _extract_ips(pkt) -> Optional[Tuple[str, str]]:
    if pkt.haslayer(IP):
        return pkt[IP].src, pkt[IP].dst
    if pkt.haslayer(IPv6):
        return pkt[IPv6].src, pkt[IPv6].dst
    return None


def _extract_protocol_and_ports(pkt) -> Tuple[TransportProtocol, Optional[int], Optional[int]]:
    if pkt.haslayer(TCP):
        return TransportProtocol.TCP, pkt[TCP].sport, pkt[TCP].dport
    if pkt.haslayer(UDP):
        return TransportProtocol.UDP, pkt[UDP].sport, pkt[UDP].dport
    if pkt.haslayer(ICMP):
        return TransportProtocol.ICMP, None, None
    return TransportProtocol.OTHER, None, None


def normalize_pcap(root: Path, capture_id: str) -> List[Packet]:
    """Reads `pcap_path(root, capture_id)` and returns one `Packet` per real
    captured frame that carries an IP (v4 or v6) layer. Frames without one
    (e.g. bare ARP/Ethernet) cannot be normalized into this schema -- they
    are skipped, not fabricated with placeholder addresses. Also persists
    the result to `packets_path(root, capture_id)` via `write_jsonl`.
    """
    packets: List[Packet] = []
    with PcapReader(str(pcap_path(root, capture_id))) as reader:
        for index, pkt in enumerate(reader):
            ips = _extract_ips(pkt)
            if ips is None:
                continue
            src_ip, dst_ip = ips
            protocol, src_port, dst_port = _extract_protocol_and_ports(pkt)

            packets.append(
                Packet(
                    packet_id=f"{capture_id}:{index}",
                    capture_id=capture_id,
                    timestamp=datetime.fromtimestamp(float(pkt.time), tz=timezone.utc),
                    src_ip=src_ip,
                    dst_ip=dst_ip,
                    src_port=src_port,
                    dst_port=dst_port,
                    protocol=protocol,
                    size_bytes=getattr(pkt, "wirelen", None) or len(bytes(pkt)),
                    direction=PacketDirection.UNKNOWN,
                    tcp_flags=_tcp_flags_to_string(pkt) if protocol == TransportProtocol.TCP else None,
                )
            )

    write_jsonl(packets_path(root, capture_id), packets)
    return packets
