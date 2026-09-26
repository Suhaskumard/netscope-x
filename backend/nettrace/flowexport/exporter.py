"""A software flow exporter (spec Phase 95): pcap -> flow records, the way softflowd-style probes aggregate.

Used to produce NetFlow v5 / IPFIX wire data from a capture for tests, benchmarks and the CLI. It is NOT a vendor
device: it is this project's own implementation of the conventional behaviour (unidirectional five-tuple flows,
inactive/active timeouts, OR of TCP flags, octets = IP-layer bytes).
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple

from scapy.layers.inet import ICMP, IP, TCP, UDP
from scapy.layers.inet6 import IPv6
from scapy.utils import PcapReader

from backend.nettrace.flowexport.records import FlowRecord

INACTIVE_TIMEOUT = 15.0
ACTIVE_TIMEOUT = 1800.0

_Key = Tuple[str, str, int, int, int]


def _flag_bits(pkt) -> int:
    return int(pkt[TCP].flags) & 0xFF if pkt.haslayer(TCP) else 0


def export_pcap(pcap: Path, inactive: float = INACTIVE_TIMEOUT, active: float = ACTIVE_TIMEOUT,
                ipv4_only: bool = False) -> List[FlowRecord]:
    live: Dict[_Key, list] = {}  # key -> [packets, octets, start, end, flags]
    done: List[FlowRecord] = []

    def close(key: _Key) -> None:
        pk, oc, st, en, fl = live.pop(key)
        done.append(FlowRecord(key[0], key[1], key[2], key[3], key[4], pk, oc, st, en, fl))

    with PcapReader(str(pcap)) as reader:
        for pkt in reader:
            if pkt.haslayer(IP):
                ip, length = pkt[IP], pkt[IP].len
            elif pkt.haslayer(IPv6) and not ipv4_only:
                ip, length = pkt[IPv6], pkt[IPv6].plen + 40
            else:
                continue
            if pkt.haslayer(TCP):
                proto, sport, dport = 6, pkt[TCP].sport, pkt[TCP].dport
            elif pkt.haslayer(UDP):
                proto, sport, dport = 17, pkt[UDP].sport, pkt[UDP].dport
            elif pkt.haslayer(ICMP):
                proto, sport, dport = 1, 0, 0
            else:
                proto, sport, dport = int(getattr(ip, "proto", getattr(ip, "nh", 0))), 0, 0
            t = float(pkt.time)
            key = (ip.src, ip.dst, sport, dport, proto)
            cur = live.get(key)
            if cur is not None and (t - cur[3] > inactive or t - cur[2] > active):
                close(key)
                cur = None
            if cur is None:
                live[key] = [1, length, t, t, _flag_bits(pkt)]
            else:
                cur[0] += 1
                cur[1] += length
                cur[3] = t
                cur[4] |= _flag_bits(pkt)
    for key in list(live):
        close(key)
    return sorted(done, key=lambda r: (r.start, r.src_ip, r.dst_ip, r.src_port))
